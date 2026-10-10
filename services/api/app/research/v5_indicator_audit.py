"""Reconstruct MV's *live* indicator implementation from pinned offline archives.

Strict no-lookahead: each checkpoint/snapshot uses only a completed source bar
and its predecessors; the same persistent history origin crosses month seams.
No databases, exchange HTTP requests, orders, signals, or report writes.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path

from mv_strategy.indicators import IndicatorState, INTERVAL_MS
from mv_strategy.signals import Snapshot

from .v5_archive_audit import audit_continuity, audited_bars
from .v5_archive_batch import batch_plan
from .v5_archives import load_spec, valid_research_root

TIMEFRAMES = ("15m", "1h", "4h")
REQUIRED_BARS = 500
INDICATOR_KEYS = ("ema20", "ema50", "sma200", "atr")


def _fingerprint(value: dict) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _checkpoint_evidence(state: IndicatorState) -> dict:
    checkpoint = state.dump()
    rebuilt = IndicatorState.restore(checkpoint)
    if rebuilt.dump() != checkpoint:
        raise ValueError("Indicator checkpoint failed deterministic restore")
    return {
        "count": checkpoint["count"],
        "last_open_ms": checkpoint["last_open_time"],
        "history_origin_ms": checkpoint["history_origin"],
        "state_sha256": _fingerprint(checkpoint),
        "lineage": checkpoint["lineage"],
    }


def reconstruct_stream(bars, timeframe: str, *, month_boundary_ms: set[int]) -> dict:
    """Audit one continuous bar stream with exact close availability evidence.

    On every month boundary, restore the prior month's state and run both
    original and restored IndicatorState implementations in lockstep.
    Comparison covers all derived values, lineage and checkpoints, not merely
    whether the strategy produces the same final signal.
    """
    if timeframe not in TIMEFRAMES:
        raise ValueError("Only indicator-bearing 15m, 1h, 4h frames are supported")
    if not month_boundary_ms:
        raise ValueError("Month boundaries must be supplied")
    step = INTERVAL_MS[timeframe]
    primary = IndicatorState(timeframe)
    resumed = None
    first_snapshot = first_ready = last_snapshot = None
    first_as_of_ms = last_as_of_ms = None
    checkpoint_evidence = []
    status_counts = {"no_sma200": 0, "has_sma200_below_v5_warmup": 0, "v5_warm": 0}
    warm_samples = {"sma200_first_close_ms": None, "v5_500_first_close_ms": None}
    snapshot_hash = sha256()
    seen_bar = False
    for bar in bars:
        if bar.open_time in month_boundary_ms:
            if primary.count:
                checkpoint_evidence.append({
                    "next_month_open_ms": bar.open_time,
                    **_checkpoint_evidence(primary),
                })
                resumed = IndicatorState.restore(primary.dump())
            elif bar.open_time != min(month_boundary_ms):
                raise ValueError("First candle did not start at the first month boundary")
        if primary.count == 0 and bar.open_time != min(month_boundary_ms):
            raise ValueError("Indicator lineage must originate at the first archived month")
        values = primary.advance(bar)
        if resumed is not None:
            matched = resumed.advance(bar)
            if matched != values or resumed.dump() != primary.dump():
                raise ValueError(f"Indicator checkpoint replay mismatch at {bar.open_time}")
        close_boundary = bar.close_time + 1
        if close_boundary != bar.open_time + step:
            raise ValueError("Snapshot was not aligned to a completed candle")
        if first_as_of_ms is None:
            first_as_of_ms = close_boundary
        last_as_of_ms = close_boundary
        seen_bar = True
        if primary.count < 200:
            if values["sma200"] is not None:
                raise ValueError("SMA200 became available before 200 closed candles")
            status_counts["no_sma200"] += 1
            continue
        if any(values[field] is None for field in INDICATOR_KEYS):
            raise ValueError("Incomplete derived indicators after SMA200 warmup")
        snapshot = Snapshot(
            timeframe, bar,
            values["ema20"], values["ema50"], values["sma200"], values["atr"],
            primary.count, primary.history_origin, primary.lineage,
        )
        snapshot.validate()
        evidence = snapshot.evidence()
        if evidence["close_boundary"] != close_boundary:
            raise ValueError("Snapshot is not available at its completed-candle boundary")
        snapshot_hash.update(json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        if first_snapshot is None:
            first_snapshot = evidence
            warm_samples["sma200_first_close_ms"] = close_boundary
        last_snapshot = evidence
        if primary.count < REQUIRED_BARS:
            status_counts["has_sma200_below_v5_warmup"] += 1
        else:
            status_counts["v5_warm"] += 1
            if first_ready is None:
                first_ready = evidence
                warm_samples["v5_500_first_close_ms"] = close_boundary
    if not seen_bar:
        raise ValueError("No historical candles available")
    if first_snapshot is None:
        raise ValueError("Insufficient history for SMA200")
    if first_ready is None:
        raise ValueError("Insufficient history for V5 500-candle warmup")
    checkpoint_evidence.append({"next_month_open_ms": None, **_checkpoint_evidence(primary)})
    if resumed is not None and resumed.dump() != primary.dump():
        raise ValueError("Final reconstructed checkpoint differs")
    return {
        "status": "DETERMINISTIC_INDICATORS_VERIFIED",
        "timeframe": timeframe,
        "history_origin_ms": primary.history_origin,
        "last_open_ms": primary.last_open_time,
        "total_bars": primary.count,
        "first_candle_available_at_ms": first_as_of_ms,
        "last_candle_available_at_ms": last_as_of_ms,
        "warmup": warm_samples,
        "counts": status_counts,
        "sma200_ready_snapshots_sha256": snapshot_hash.hexdigest(),
        "first_sma200_snapshot": first_snapshot,
        "first_v5_500_snapshot": first_ready,
        "last_snapshot": last_snapshot,
        "month_seam_checkpoints": checkpoint_evidence,
        "snapshot_policy": "after bar.close_time + 1 only; completed candles; no future source inputs",
    }


def reconstruct_one(root: Path, spec_sha: str, plans: list[dict]) -> dict:
    """Verify complete source chain, then reconstruct indicators in one stream."""
    history = audit_continuity(root, plans, spec_sha)
    if plans[0]["timeframe"] == "1m":
        raise ValueError("The 1m source is execution reference, not MV indicator state")
    frames = [p["start_ms"] for p in plans]
    result = reconstruct_stream(
        audited_bars(root, plans, spec_sha),
        plans[0]["timeframe"],
        month_boundary_ms=set(frames),
    )
    if result["total_bars"] != history["rows"]:
        raise ValueError("Reconstructed indicators have incorrect source row count")
    return {"source": history, "indicators": result}


def reconstruct_all(root: Path, spec: dict, spec_sha: str, symbol: str, first: str, last: str) -> dict:
    reports = {}
    for timeframe in TIMEFRAMES:
        plans = batch_plan(spec, symbol, timeframe, first, last)
        reports[timeframe] = reconstruct_one(root, spec_sha, plans)
    # Earliest potential evaluation time is a completed hourly decision at
    # which 1H and last completed 4H and 15m are *all* 500-candle warm.
    # It is not an entry decision or profitability evidence.
    first_eligible = max(
        reports[frame]["indicators"]["warmup"]["v5_500_first_close_ms"]
        for frame in TIMEFRAMES
    )
    one_hour_first = reports["1h"]["source"]["first_open_ms"]
    last_complete_hour = reports["1h"]["source"]["end_exclusive_ms"]
    earliest_hour_boundary = max(
        one_hour_first + 500 * INTERVAL_MS["1h"],
        first_eligible,
    )
    if earliest_hour_boundary % INTERVAL_MS["1h"] != 0:
        earliest_hour_boundary = (
            (earliest_hour_boundary + INTERVAL_MS["1h"] - 1)
            // INTERVAL_MS["1h"] * INTERVAL_MS["1h"]
        )
    if earliest_hour_boundary > last_complete_hour:
        raise ValueError("No historically complete V5-ready 1H context boundaries")
    return {
        "schema": 1,
        "status": "PASS",
        "symbol": symbol,
        "spec_sha256": spec_sha,
        "months": [p["month"] for p in batch_plan(spec, symbol, "1h", first, last)],
        "timeframes": reports,
        "first_potential_complete_1h_context_ms": earliest_hour_boundary,
        "available_completed_1h_context_boundaries": (
            (last_complete_hour - earliest_hour_boundary) // INTERVAL_MS["1h"] + 1
        ),
        "evaluation_warning": (
            "Historical warm-up starts at the first archived month; research periods "
            "before the 500-closed-4H gate are not eligible. This is not a strategy backtest."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only MV V5 live-indicator parity reconstruction")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    args = parser.parse_args()
    spec, spec_sha = load_spec()
    root = valid_research_root(args.root)
    report = reconstruct_all(root, spec, spec_sha, args.symbol, args.start_month, args.end_month)
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
