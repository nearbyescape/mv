"""Chronological *decision-only* V4 / V5 Hybrid replay on pinned archives.

One BTC research symbol, March-May development only. This does not create
publishable trade signals, price entries, apply portfolio safety, or model P&L.
It reuses the actual V4 and V5 pure strategy evaluators on candle-close
snapshots reconstructed from January's common fixed indicator origin.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from mv_strategy.indicators import IndicatorState, INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import Snapshot
from mv_strategy.strategy_v3 import STRUCTURE_BARS
from mv_strategy.strategy_v4 import evaluate_setup_v4
from mv_strategy.strategy_v5 import evaluate_context_v5, evaluate_trigger_v5

from .dataset import timestamp
from .v5_archive_audit import audit_continuity, audited_bars
from .v5_archive_batch import batch_plan
from .v5_archives import load_spec, valid_research_root

IST = ZoneInfo("Asia/Kolkata")
HOUR = INTERVAL_MS["1h"]
MIN15 = INTERVAL_MS["15m"]
FRAMES = ("15m", "1h", "4h")
WARMUP = 500
SAMPLE_LIMIT = 8


def _event_hash_update(digest, row: dict) -> None:
    digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")


def snapshots_from_pinned(root: Path, plans: list[dict], spec_sha: str):
    """Fail closed on source integrity before returning deterministic snapshots."""
    if not plans or plans[0]["timeframe"] not in FRAMES:
        raise ValueError("Only indicator timeframes are accepted")
    history = audit_continuity(root, plans, spec_sha)
    frame = plans[0]["timeframe"]
    state = IndicatorState(frame)
    rows: dict[int, Snapshot] = {}
    for bar in audited_bars(root, plans, spec_sha):
        values = state.advance(bar)
        if any(value is None for value in values.values()):
            continue
        snapshot = Snapshot(
            frame, bar, values["ema20"], values["ema50"],
            values["sma200"], values["atr"],
            state.count, state.history_origin, state.lineage,
        )
        snapshot.validate()
        rows[bar.open_time] = snapshot
    if history["rows"] != state.count:
        raise ValueError("Indicator series/source row count disagreement")
    if not rows or rows[max(rows)].bar.close_time + 1 != history["end_exclusive_ms"]:
        raise ValueError("Latest snapshot does not match verified history end")
    return rows, history


def _session(t_ms: int) -> bool:
    clock = datetime.fromtimestamp(t_ms / 1000, IST)
    return 9 <= clock.hour < 23


def _structures(rows: dict[int, Snapshot], current_open: int, step: int):
    """All structure bars must precede the current candle."""
    return [
        rows.get(current_open - j * step)
        for j in range(STRUCTURE_BARS, 0, -1)
    ]


def first_possible_boundary(maps: dict[str, dict[int, Snapshot]]) -> int:
    """Minimum completed 1H boundary after 500 bars on all three frames."""
    required = []
    for frame in FRAMES:
        ready = [
            snapshot.bar.close_time + 1
            for snapshot in maps[frame].values()
            if snapshot.count >= WARMUP
        ]
        boundary = min(ready) if ready else None
        if boundary is None:
            raise ValueError(f"No {frame} candle satisfies 500-bar warmup")
        required.append(boundary)
    return (max(required) + HOUR - 1) // HOUR * HOUR


def replay_decisions(
    maps: dict[str, dict[int, Snapshot]],
    symbol: str,
    start_ms: int,
    end_ms: int,
) -> dict:
    """Evaluate immutable completed context, then only future 15m closes.

    A V5 rescue is evaluated *only* after a V4 trend-aligned
    NO_PULLBACK_OR_BREAKOUT_TRIGGER; qualified V4 base rows cannot be replaced.
    Potential triggers are research references, never actual executions.
    """
    if start_ms >= end_ms:
        raise ValueError("Empty research evaluation interval")
    first_ready = first_possible_boundary(maps)
    effective_start = max(start_ms, first_ready)
    stats = Counter()
    reasons_v4 = Counter()
    reasons_context = Counter()
    reasons_trigger = Counter()
    stream_digest = sha256()
    candidate_digest = sha256()
    samples = []
    last_boundary = None
    for open_time, current in sorted(maps["1h"].items()):
        boundary = current.bar.close_time + 1
        if not effective_start <= boundary < end_ms or not _session(boundary):
            continue
        if last_boundary is not None and boundary <= last_boundary:
            raise ValueError("Nonchronological completed hourly evaluation")
        last_boundary = boundary
        if current.bar.close_time >= boundary:
            raise ValueError("Current hourly candle is not complete")
        previous = maps["1h"].get(open_time - HOUR)
        four_open = confirmation_open_time(boundary)
        four = maps["4h"].get(four_open)
        structure = _structures(maps["1h"], open_time, HOUR)
        if four is not None and four.bar.close_time + 1 > boundary:
            raise ValueError("Future 4h confirmation would leak into a decision")

        v4 = evaluate_setup_v4(current, previous, four, structure)
        stats["hourly_contexts"] += 1
        reasons_v4[v4.reason] += 1
        _event_hash_update(stream_digest, {
            "event": "v4_context", "at_ms": boundary,
            "source_open_ms": open_time, "source_lineage": current.lineage,
            "confirmation_open_ms": four_open,
            "confirmation_lineage": four.lineage if four is not None else None,
            "outcome": v4.outcome, "reason": v4.reason,
            "direction": v4.direction,
        })

        if v4.outcome in ("LONG_SETUP", "SHORT_SETUP"):
            stats["v4_base_qualifiers"] += 1
            stats["v5_base_preserved_pre_safety"] += 1
            candidate = {
                "lane": "v4_base", "symbol": symbol,
                "at_ms": boundary, "context_open_ms": open_time,
                "direction": v4.direction, "setup_type": v4.setup_type,
                "status": "RULES_QUALIFIED_NOT_PRICED",
            }
            _event_hash_update(candidate_digest, candidate)
            if len(samples) < SAMPLE_LIMIT:
                samples.append(candidate)
            continue

        if (
            v4.outcome != "NO_SETUP"
            or v4.reason != "NO_PULLBACK_OR_BREAKOUT_TRIGGER"
            or v4.direction not in ("long", "short")
            or v4.regime is None
        ):
            continue

        stats["v4_trend_aligned_no_trigger"] += 1
        context = evaluate_context_v5(current, previous, four, structure)
        reasons_context[context.reason] += 1
        if context.outcome != "ARMED":
            continue
        stats["armed_rescue_hours"] += 1

        for offset in range(4):
            trigger_open = boundary + offset * MIN15
            publication = trigger_open + MIN15
            if publication >= end_ms or not _session(publication):
                break
            trigger_snapshot = maps["15m"].get(trigger_open)
            trigger_previous = maps["15m"].get(trigger_open - MIN15)
            trigger_structure = _structures(maps["15m"], trigger_open, MIN15)
            if trigger_snapshot is None or trigger_previous is None or any(
                snap is None for snap in trigger_structure
            ):
                reasons_trigger["MISSING_15M_CONTEXT"] += 1
                continue
            if trigger_snapshot.bar.close_time + 1 != publication:
                raise ValueError("Trigger tried to use an incomplete 15m candle")
            if trigger_previous.bar.close_time + 1 != trigger_open:
                raise ValueError("Previous trigger candle is not yet complete")
            trigger = evaluate_trigger_v5(
                context.direction, trigger_snapshot, trigger_previous,
                trigger_structure,
            )
            stats["completed_15m_trigger_checks"] += 1
            reasons_trigger[trigger.reason] += 1
            _event_hash_update(stream_digest, {
                "event": "v5_trigger", "at_ms": publication,
                "context_open_ms": open_time,
                "trigger_open_ms": trigger_open,
                "trigger_lineage": trigger_snapshot.lineage,
                "outcome": trigger.outcome, "reason": trigger.reason,
            })
            if trigger.outcome != "TRIGGER":
                continue
            if publication <= boundary or publication > boundary + HOUR:
                raise ValueError("Rescue publication lies outside armed hour")
            stats["v5_rescue_trigger_references"] += 1
            candidate = {
                "lane": "15m_rescue", "symbol": symbol,
                "at_ms": publication, "context_open_ms": open_time,
                "trigger_open_ms": trigger_open,
                "direction": context.direction,
                "setup_type": trigger.trigger_type,
                "status": "TRIGGER_ONLY_NOT_PRICED",
            }
            _event_hash_update(candidate_digest, candidate)
            if len(samples) < SAMPLE_LIMIT:
                samples.append(candidate)
            # The first completed 15m trigger wins this context hour;
            # no future candle may be used to choose an alternative.
            break

    if stats["v4_base_qualifiers"] != stats["v5_base_preserved_pre_safety"]:
        raise ValueError("V4 base candidate was lost in V5 research replay")
    return {
        "status": "DECISION_ONLY_REPLAY",
        "symbol": symbol,
        "requested_start_ms": start_ms,
        "eligible_start_ms": effective_start,
        "end_exclusive_ms": end_ms,
        "counts": {
            key: stats.get(key, 0)
            for key in (
                "hourly_contexts",
                "v4_base_qualifiers",
                "v5_base_preserved_pre_safety",
                "v4_trend_aligned_no_trigger",
                "armed_rescue_hours",
                "completed_15m_trigger_checks",
                "v5_rescue_trigger_references",
            )
        },
        "v4_reason_counts": dict(sorted(reasons_v4.items())),
        "v5_context_reason_counts": dict(sorted(reasons_context.items())),
        "v5_trigger_reason_counts": dict(sorted(reasons_trigger.items())),
        "decision_stream_sha256": stream_digest.hexdigest(),
        "candidate_stream_sha256": candidate_digest.hexdigest(),
        "candidate_samples": samples,
        "limitations": [
            "Single-symbol decision-only development diagnostic, not portfolio replay.",
            "V4 base qualifiers are preserved only BEFORE pricing and market safety.",
            "No BTC veto, portfolio concentration, circuit state, session dedupe, price filters or contract inception checks.",
            "No 1m execution entry, fee, funding, slippage, latency, stop/target or P&L simulation.",
            "Reference Binance candles do not establish actual Lighter fills.",
        ],
    }


def replay_development(
    root: Path, spec: dict, spec_sha: str, symbol: str,
    start_month: str, end_month: str,
) -> dict:
    if symbol not in spec["symbols"]:
        raise ValueError("Requested symbol not in pinned research specification")
    development = next(part for part in spec["partitions"] if part["name"] == "development")
    if start_month != "2026-01" or end_month != "2026-05":
        raise ValueError("Pilot must use Jan-May only; validation and holdout are excluded")
    maps = {}
    sources = {}
    for frame in FRAMES:
        plans = batch_plan(spec, symbol, frame, start_month, end_month)
        maps[frame], sources[frame] = snapshots_from_pinned(root, plans, spec_sha)
    result = replay_decisions(
        maps, symbol,
        timestamp(development["start"]),
        timestamp(development["end"]),
    )
    return {
        "schema": 1,
        "spec_sha256": spec_sha,
        "partition": "development",
        "source_months": [p["month"] for p in plans],
        "source_sha256": {
            frame: sources[frame]["canonical_series_sha256"]
            for frame in FRAMES
        },
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline, development-only V4 vs V5 setup replay")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    args = parser.parse_args()
    spec, spec_sha = load_spec()
    root = valid_research_root(args.root)
    report = replay_development(
        root, spec, spec_sha, args.symbol, args.start_month, args.end_month,
    )
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
