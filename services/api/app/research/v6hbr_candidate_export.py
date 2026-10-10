"""Offline V6HBR candidate stream, pinned to the inherited V5 replay semantics.

Decision-only evidence. Does NOT place orders, construct executable fills,
apply portfolio safety, or infer net P&L. V5 source modules remain immutable.
The output includes EVERY candidate event rather than eight sample records.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from mv_strategy.indicators import INTERVAL_MS, confirmation_open_time
from mv_strategy.strategy_v4 import evaluate_setup_v4
from mv_strategy.strategy_v5 import evaluate_context_v5, evaluate_trigger_v5

from .dataset import timestamp
from .v5_archive_batch import batch_plan
from .v5_archives import load_spec, valid_research_root
from .v5_decision_replay import (
    FRAMES, HOUR, MIN15, WARMUP, _session, _structures,
    first_possible_boundary, replay_decisions, snapshots_from_pinned,
)


def _hash_rows(rows: list[dict]) -> str:
    digest = sha256()
    for row in rows:
        digest.update(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    return digest.hexdigest()


def export_events(maps: dict, symbol: str, start_ms: int, end_ms: int) -> dict:
    """Emit V4 base + first completed-15m rescue without future observations.

    Compare exact candidate digest and counts against original replay_decisions.
    Any behavioral divergence fails closed before the stream can be consumed.
    """
    if start_ms >= end_ms:
        raise ValueError("Empty evaluation window")
    eligible_start = max(start_ms, first_possible_boundary(maps))
    events: list[dict] = []
    canonical_candidates: list[dict] = []
    for open_ms, hour in sorted(maps["1h"].items()):
        boundary = hour.bar.close_time + 1
        if not eligible_start <= boundary < end_ms or not _session(boundary):
            continue
        previous = maps["1h"].get(open_ms - HOUR)
        four_open = confirmation_open_time(boundary)
        four = maps["4h"].get(four_open)
        structure = _structures(maps["1h"], open_ms, HOUR)
        if hour.bar.close_time >= boundary or (
            four is not None and four.bar.close_time + 1 > boundary
        ):
            raise ValueError("Future/incomplete hourly or 4h candle")
        setup = evaluate_setup_v4(hour, previous, four, structure)
        if setup.outcome in ("LONG_SETUP", "SHORT_SETUP"):
            ref = {
                "lane": "v4_base", "symbol": symbol,
                "at_ms": boundary, "context_open_ms": open_ms,
                "direction": setup.direction, "setup_type": setup.setup_type,
                "status": "RULES_QUALIFIED_NOT_PRICED",
            }
            canonical_candidates.append(ref)
            events.append({
                **ref, "regime": setup.regime,
                "source_1h_open_ms": open_ms,
                "source_1h_lineage": hour.lineage,
                "confirmation_4h_open_ms": four_open,
                "confirmation_4h_lineage": four.lineage if four else None,
                "trigger_15m_open_ms": None,
                "trigger_15m_lineage": None,
            })
            continue
        if not (
            setup.outcome == "NO_SETUP"
            and setup.reason == "NO_PULLBACK_OR_BREAKOUT_TRIGGER"
            and setup.direction in ("long", "short")
            and setup.regime is not None
        ):
            continue
        armed = evaluate_context_v5(hour, previous, four, structure)
        if armed.outcome != "ARMED":
            continue
        for offset in range(4):
            trigger_open = boundary + offset * MIN15
            published_at = trigger_open + MIN15
            if published_at >= end_ms or not _session(published_at):
                break
            trigger_snap = maps["15m"].get(trigger_open)
            trigger_previous = maps["15m"].get(trigger_open - MIN15)
            trigger_structure = _structures(maps["15m"], trigger_open, MIN15)
            if (
                trigger_snap is None or trigger_previous is None
                or any(item is None for item in trigger_structure)
            ):
                continue
            if (
                trigger_snap.bar.close_time + 1 != published_at
                or trigger_previous.bar.close_time + 1 != trigger_open
            ):
                raise ValueError("Future/incomplete 15m trigger candle")
            trigger = evaluate_trigger_v5(
                armed.direction, trigger_snap, trigger_previous, trigger_structure
            )
            if trigger.outcome != "TRIGGER":
                continue
            if not boundary < published_at <= boundary + HOUR:
                raise ValueError("15m rescue outside armed hour")
            ref = {
                "lane": "15m_rescue", "symbol": symbol,
                "at_ms": published_at, "context_open_ms": open_ms,
                "trigger_open_ms": trigger_open,
                "direction": armed.direction, "setup_type": trigger.trigger_type,
                "status": "TRIGGER_ONLY_NOT_PRICED",
            }
            canonical_candidates.append(ref)
            events.append({
                **ref, "regime": armed.regime,
                "source_1h_open_ms": open_ms,
                "source_1h_lineage": hour.lineage,
                "confirmation_4h_open_ms": four_open,
                "confirmation_4h_lineage": four.lineage if four else None,
                "trigger_15m_open_ms": trigger_open,
                "trigger_15m_lineage": trigger_snap.lineage,
            })
            break

    reference = replay_decisions(maps, symbol, start_ms, end_ms)
    digest = _hash_rows(canonical_candidates)
    expected = reference["candidate_stream_sha256"]
    if digest != expected:
        raise ValueError("Candidate stream diverges from frozen original V5 replay")
    base_count = sum(x["lane"] == "v4_base" for x in events)
    rescue_count = sum(x["lane"] == "15m_rescue" for x in events)
    if (
        base_count != reference["counts"]["v4_base_qualifiers"]
        or rescue_count != reference["counts"]["v5_rescue_trigger_references"]
    ):
        raise ValueError("Candidate counts diverge from frozen replay")
    events.sort(key=lambda x: (
        x["at_ms"], 0 if x["lane"] == "v4_base" else 1,
        x["symbol"], x["context_open_ms"], x.get("trigger_open_ms", -1),
    ))
    return {
        "schema": 1,
        "status": "COMPLETE_CANDIDATE_EXPORT_NO_PNL",
        "symbol": symbol,
        "start_ms": start_ms,
        "end_exclusive_ms": end_ms,
        "eligible_start_ms": eligible_start,
        "candidates": len(events),
        "v4_base": base_count,
        "15m_rescue": rescue_count,
        "reference_candidate_stream_sha256": digest,
        "export_stream_sha256": _hash_rows(events),
        "boundary_semantics": "Inherited offset 0..3 permits trigger at next hourly boundary; not policy-certified",
        "limitations": [
            "No BTC timing/risk veto or historical price filters",
            "No execution fills, fees, funding, portfolio state or returns",
            "Events are not profitable/executable trades",
        ],
        "events": events,
    }


def export_development(root: Path, *, symbol: str, start: str, end: str) -> dict:
    """Strictly April–May development: no validation/holdout access."""
    if symbol != "BTCUSDT" or (start, end) != ("2026-04-01", "2026-06-01"):
        raise ValueError("Pilot permits BTCUSDT April-May development only")
    spec, spec_sha = load_spec()
    maps = {}
    sources = {}
    for frame in FRAMES:
        plans = batch_plan(spec, symbol, frame, "2026-01", "2026-05")
        maps[frame], sources[frame] = snapshots_from_pinned(root, plans, spec_sha)
    result = export_events(maps, symbol, timestamp(start), timestamp(end))
    return {
        "source_spec_sha256": spec_sha,
        "source_series_sha256": {
            frame: sources[frame]["canonical_series_sha256"]
            for frame in FRAMES
        },
        "partition": "development",
        "execution_data_required": "BTCUSDT 1m April-May verified separately; this export does not read it",
        **result,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline complete BTC V6HBR candidate export, NO PNL")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--start", default="2026-04-01")
    parser.add_argument("--end", default="2026-06-01")
    args = parser.parse_args()
    report = export_development(
        valid_research_root(args.root), symbol=args.symbol, start=args.start, end=args.end
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
