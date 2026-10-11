"""Frozen multi-day T7Sonic attribution and matched-direction baselines.

Offline, post-label descriptive research. Never trains, selects experts, or
publishes signals. All reports belong to inspected April/May development.
The original SHA256SUMS digest is externally pinned by the operator.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re

FAV = "FAVORABLE_ABOVE_10BPS"
ADV = "ADVERSE_BELOW_MINUS_10BPS"
NEU = "NEUTRAL_WITHIN_10BPS"
LABELS = frozenset((FAV, ADV, NEU))
HORIZONS = ("15", "30", "60", "120")
HEX = re.compile(r"[0-9a-f]{64}\Z")
DAY = re.compile(r"2026-0[45]-[0-3][0-9]\Z")
LIMIT = 16 * 1024 * 1024
THRESHOLD = Decimal("10")


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _classify(move: Decimal) -> str:
    if not move.is_finite():
        raise ValueError("Nonfinite mark movement")
    return FAV if move > THRESHOLD else ADV if move < -THRESHOLD else NEU


def _counts(records: list[dict]) -> dict:
    c = Counter(record["classification"] for record in records)
    return {
        "episodes": len(records),
        "favorable": c[FAV], "adverse": c[ADV], "neutral": c[NEU],
        "favorable_rate": round(c[FAV] / len(records), 6) if records else None,
    }


def _paired_summary(records: list[dict]) -> dict:
    """Matched onset comparison; no IID or tradability assumptions."""
    actual = _counts([{"classification": r["classification"]} for r in records])
    long = _counts([{"classification": r["long_baseline_class"]} for r in records])
    short = _counts([{"classification": r["short_baseline_class"]} for r in records])
    def pair(key: str) -> dict:
        better = sum(r["classification"] == FAV and r[key] != FAV for r in records)
        worse = sum(r["classification"] != FAV and r[key] == FAV for r in records)
        baseline = long if key == "long_baseline_class" else short
        net = actual["favorable"] - baseline["favorable"]
        if better - worse != net:
            raise ValueError("Paired favorable discordance fails reconciliation")
        return {
            "actual_only_favorable": better,
            "baseline_only_favorable": worse,
            "net_favorable_episodes_actual_minus_baseline": net,
            "favorable_rate_delta_percentage_points": (
                round(100 * net / len(records), 4) if records else None
            ),
        }
    return {
        "actual": actual,
        "matched_long": long,
        "matched_short": short,
        "vs_matched_long": pair("long_baseline_class"),
        "vs_matched_short": pair("short_baseline_class"),
    }


def _report_records(report: dict, day: str) -> list[dict]:
    if (report.get("schema") != 1 or report.get("engine") != "T7Sonic" or
        report.get("day") != day or report.get("symbols") != ["BTCUSDT"] or
        report.get("scope") != "INSPECTED_APRIL_MAY_DEVELOPMENT_ONLY" or
        report.get("status") != "RETROSPECTIVE_DEVELOPMENT_DIRECTIONAL_MARK_PROXY_NOT_TRADES" or
        report.get("completed_five_minute_decision_boundaries") != 288 or
        report.get("actionable_signals") != 0 or
        report.get("trading_wins_claimed") is not False or
        report.get("quotes_slippage_fees_funding_modeled") is not False or
        report.get("all_episode_labels_derived_after_decisions_frozen") is not True):
        raise ValueError("Invalid frozen nontrading report or research scope")
    if any(not isinstance(report.get(k), str) or not HEX.fullmatch(report[k])
           for k in ("decision_stream_sha256", "label_stream_sha256")):
        raise ValueError("Invalid stream digest")
    episodes = report.get("directional_episode_labels")
    if not isinstance(episodes, list):
        raise ValueError("Full episode labels required")
    if len(episodes) != report["directional_grouping"]["directional_episodes"]:
        raise ValueError("Episode count mismatch")
    digest = _sha(b"".join(
        json.dumps(x, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        for x in episodes
    ))
    if digest != report["label_stream_sha256"]:
        raise ValueError("Episode label-stream SHA mismatch")
    seen = set()
    daily = {h: Counter() for h in HORIZONS}
    normalized = []
    for e in episodes:
        if (e.get("id") in seen or not isinstance(e.get("id"), str) or
            e.get("symbol") != "BTCUSDT" or
            e.get("direction") not in ("LONG", "SHORT")):
            raise ValueError("Duplicate or malformed episode")
        seen.add(e["id"])
        onset = e.get("experts_at_onset")
        if not isinstance(onset, list) or not onset or len(set(onset)) != len(onset):
            raise ValueError("Malformed expert attribution")
        outcomes = e.get("horizons_minutes", {})
        for horizon in HORIZONS:
            item = outcomes.get(horizon, {})
            value = Decimal(item["signed_mark_move_bps"])
            label = item.get("classification")
            if label not in LABELS or label != _classify(value):
                raise ValueError("Inconsistent signed mark and classification")
            daily[horizon][label] += 1
        signed = Decimal(outcomes["60"]["signed_mark_move_bps"])
        # Matched baselines use exactly the same expert-selected episode times.
        # This is NOT an unconditional always-long/short market strategy.
        long_move = signed if e["direction"] == "LONG" else -signed
        normalized.append({
            "classification": outcomes["60"]["classification"],
            "long_baseline_class": _classify(long_move),
            "short_baseline_class": _classify(-long_move),
            "direction": e["direction"],
            "experts": onset,
        })
    for h in HORIZONS:
        row = report["horizon_labels"][h]
        if (row["episode_labels"] != len(episodes) or
            row["favorable_above_10bps"] != daily[h][FAV] or
            row["adverse_below_minus_10bps"] != daily[h][ADV] or
            row["neutral_within_10bps"] != daily[h][NEU]):
            raise ValueError("Horizon rollup mismatch")
    return normalized


def analyze(root: Path, start_day: str, days: int,
            ledger_sha: str, anchor_decision_sha: str,
            anchor_label_sha: str) -> dict:
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir() or
        not isinstance(days, int) or type(days) is bool or not 2 <= days <= 31 or
        not isinstance(start_day, str) or not DAY.fullmatch(start_day) or
        any(not isinstance(x, str) or not HEX.fullmatch(x) for x in
            (ledger_sha, anchor_decision_sha, anchor_label_sha))):
        raise ValueError("Invalid explicit development evidence request")
    start = datetime.strptime(start_day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    dates = [(start + timedelta(days=i)).strftime("%Y-%m-%d")
             for i in range(days)]
    if dates[-1] >= "2026-06-01":
        raise ValueError("Development-only April/May reports required")
    expected = {d + ".json" for d in dates} | {"summary.txt"}
    ledger_file = root / "SHA256SUMS"
    if ledger_file.is_symlink() or not ledger_file.is_file():
        raise ValueError("Pinned ledger absent")
    ledger_bytes = ledger_file.read_bytes()
    if len(ledger_bytes) > 4096 or _sha(ledger_bytes) != ledger_sha:
        raise ValueError("Operator-pinned evidence-ledger digest mismatch")
    digest_by_name = {}
    for line in ledger_bytes.decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError("Malformed SHA256SUMS line")
        recorded = Path(match[2])
        name = recorded.name
        if not recorded.is_absolute() or name in digest_by_name:
            raise ValueError("Invalid or duplicate ledger entry")
        digest_by_name[name] = match[1]
    if set(digest_by_name) != expected:
        raise ValueError("Ledger does not cover exactly the requested reports")
    actual = {p.name for p in root.glob("2026-*.json")}
    if actual != expected - {"summary.txt"}:
        raise ValueError("Unexpected or missing research report")
    for name, value in digest_by_name.items():
        p = root / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > LIMIT:
            raise ValueError("Missing/symlinked/oversized evidence member")
        if _sha(p.read_bytes()) != value:
            raise ValueError("Evidence member differs from pinned ledger: " + name)

    per_day = []
    by_expert = defaultdict(list)
    by_expert_pairs = defaultdict(list)
    by_direction = defaultdict(list)
    by_consensus = defaultdict(list)
    all_actual = []
    all_long = []
    all_short = []
    all_pairs = []
    anchor_verified = False
    for day in dates:
        report = json.loads((root / (day + ".json")).read_text(encoding="utf-8"))
        records = _report_records(report, day)
        if day == "2026-04-20":
            if (report["decision_stream_sha256"] != anchor_decision_sha or
                report["label_stream_sha256"] != anchor_label_sha):
                raise ValueError("April 20 original frozen evidence mismatch")
            anchor_verified = True
        actual = [r["classification"] for r in records]
        long = [r["long_baseline_class"] for r in records]
        short = [r["short_baseline_class"] for r in records]
        all_actual.extend(actual)
        all_long.extend(long)
        all_short.extend(short)
        all_pairs.extend(records)
        for r in records:
            by_direction[r["direction"]].append(r["classification"])
            by_consensus["MULTIPLE" if len(r["experts"]) > 1 else "SINGLE"].append(
                r["classification"]
            )
            for expert in r["experts"]:
                by_expert[expert].append((day, r["classification"]))
                by_expert_pairs[expert].append((day, r))
        per_day.append({
            "day": day, "actual": _counts([{"classification": x} for x in actual]),
            "matched_long": _counts([{"classification": x} for x in long]),
            "matched_short": _counts([{"classification": x} for x in short]),
            "paired_favorable": _paired_summary(records),
        })
    if not anchor_verified:
        raise ValueError("Frozen April 20 anchor must be within evaluated days")
    total_counts = _counts([{"classification": x} for x in all_actual])
    if sum(x["actual"]["episodes"] for x in per_day) != total_counts["episodes"]:
        raise ValueError("Day-to-aggregate reconciliation mismatch")
    leave_one_out = []
    for row in per_day:
        numerator = total_counts["favorable"] - row["actual"]["favorable"]
        denominator = total_counts["episodes"] - row["actual"]["episodes"]
        if denominator:
            leave_one_out.append(numerator / denominator)
    expert_out = {}
    for expert, records in sorted(by_expert.items()):
        c = _counts([{"classification": x} for _, x in records])
        c["active_days"] = len({day for day, _ in records})
        expert_out[expert] = c
    expert_paired = {}
    for expert, entries in sorted(by_expert_pairs.items()):
        aligned = [r for _, r in entries]
        stats = _paired_summary(aligned)
        days_by_expert = defaultdict(list)
        for day, record in entries:
            days_by_expert[day].append(record)
        daily = {}
        for day, grouped in sorted(days_by_expert.items()):
            day_stats = _paired_summary(grouped)
            daily[day] = {
                "episodes": len(grouped),
                "actual_favorable": day_stats["actual"]["favorable"],
                "long_favorable": day_stats["matched_long"]["favorable"],
                "short_favorable": day_stats["matched_short"]["favorable"],
                "net_favorable_vs_long": day_stats["vs_matched_long"][
                    "net_favorable_episodes_actual_minus_baseline"
                ],
                "net_favorable_vs_short": day_stats["vs_matched_short"][
                    "net_favorable_episodes_actual_minus_baseline"
                ],
            }
        for side in ("long", "short"):
            vals = [v["net_favorable_vs_" + side] for v in daily.values()]
            stats["active_days_better_than_matched_" + side] = sum(v > 0 for v in vals)
            stats["active_days_worse_than_matched_" + side] = sum(v < 0 for v in vals)
            stats["active_days_tied_with_matched_" + side] = sum(v == 0 for v in vals)
        stats["daily"] = daily
        stats["active_days"] = len(daily)
        if stats["actual"]["episodes"] != expert_out[expert]["episodes"]:
            raise ValueError("Expert attribution to matched-baseline mismatch")
        expert_paired[expert] = stats
    return {
        "engine": "T7Sonic",
        "status": "DESCRIPTIVE_FROZEN_DEVELOPMENT_NO_TRADING_SELECTION",
        "days": days,
        "start_day": start_day, "end_day": dates[-1],
        "evidence_ledger_sha256": ledger_sha,
        "april_20_anchor_verified": True,
        "primary_horizon_minutes": 60,
        "actual_watch_direction": total_counts,
        "paired_onsets": _paired_summary(all_pairs),
        "by_expert_paired_matched_baselines": expert_paired,
        "matched_always_long_on_same_watch_onsets":
            _counts([{"classification": x} for x in all_long]),
        "matched_always_short_on_same_watch_onsets":
            _counts([{"classification": x} for x in all_short]),
        "by_expert_at_onset": expert_out,
        "by_direction": {k: _counts([{"classification": x} for x in v])
                         for k, v in sorted(by_direction.items())},
        "by_consensus": {k: _counts([{"classification": x} for x in v])
                         for k, v in sorted(by_consensus.items())},
        "daily": per_day,
        "leave_one_day_out_favorable_rate_range_NOT_CI": [
            round(min(leave_one_out), 6), round(max(leave_one_out), 6)
        ],
        "limitations": [
            "Market and dates already inspected; NO untouched validation",
            "Episode times were selected by current experts: constant-side baselines are matched only, not market-wide",
            "Overlapping forward horizons and coactivated experts violate independence",
            "Leave-one-day-out range is sensitivity only, NOT a confidence interval",
            "Expert matched baselines share EXACTLY the same onset times as each individual expert cohort",
            "Per-expert day counts and paired discordances are descriptive, not inferential p-values",
            "No executable prices, fees, slippage, latency, funding, SL/TP, trade expectancy",
            "No training, threshold selection, live recommendations or production mutation",
        ],
    }


def main() -> None:
    p = argparse.ArgumentParser(description="T7Sonic frozen multi-day diagnostic, no trading")
    p.add_argument("--report-dir", required=True)
    p.add_argument("--start-day", required=True)
    p.add_argument("--days", type=int, required=True)
    p.add_argument("--ledger-sha", required=True)
    p.add_argument("--anchor-decision-sha", required=True)
    p.add_argument("--anchor-label-sha", required=True)
    a = p.parse_args()
    print(json.dumps(analyze(Path(a.report_dir), a.start_day, a.days,
                             a.ledger_sha, a.anchor_decision_sha,
                             a.anchor_label_sha), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
