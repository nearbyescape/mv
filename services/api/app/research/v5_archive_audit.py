"""Read-only cross-month and cross-timeframe historical source audit.

Verify pinned monthly files before reading any candle, check month seams and
compare native 4h candles to aggregates of *independent* native 1h candles.
Source disagreements are evidence to investigate, never silently corrected.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from pathlib import Path

from .dataset import archive_bars
from .v5_archive_batch import batch_plan
from .v5_archives import (
    FRAME_MS,
    archive_location,
    load_spec,
    valid_research_root,
    verify_existing,
)

FIELDS = ("open", "high", "low", "close", "volume")
MAX_SAMPLES = 8


def audited_bars(root: Path, plans: list[dict], spec_sha: str):
    """Yield only verified, contiguous source bars, crossing month boundaries."""
    if not plans or len(set((p["symbol"], p["timeframe"]) for p in plans)) != 1:
        raise ValueError("Audited bar series must use one symbol and timeframe")
    previous_open = None
    for plan in plans:
        archive, _ = archive_location(root, plan)
        verify_existing(root, plan, spec_sha)
        interval = FRAME_MS[plan["timeframe"]]
        for bar in archive_bars(archive, plan["timeframe"]):
            if previous_open is not None and bar.open_time != previous_open + interval:
                raise ValueError(f"Cross-month discontinuity at {bar.open_time}")
            previous_open = bar.open_time
            yield bar


def audit_continuity(root: Path, plans: list[dict], spec_sha: str) -> dict:
    """Canonical hash binds the full ordered OHLCV series to this audit."""
    if not plans:
        raise ValueError("Empty audit scope")
    rolling = sha256()
    first_open = last_open = None
    rows = 0
    for bar in audited_bars(root, plans, spec_sha):
        if first_open is None:
            first_open = bar.open_time
        last_open = bar.open_time
        canonical = json.dumps(
            [bar.open_time, bar.close_time, *(str(getattr(bar, key)) for key in FIELDS)],
            separators=(",", ":"),
        )
        rolling.update(canonical.encode("utf-8") + b"\n")
        rows += 1
    total_expected = sum(p["expected_rows"] for p in plans)
    step = FRAME_MS[plans[0]["timeframe"]]
    if (
        rows != total_expected
        or first_open != plans[0]["start_ms"]
        or last_open + step != plans[-1]["end_exclusive_ms"]
    ):
        raise ValueError("Audited series is incomplete, even though month manifests verified")
    return {
        "status": "CONTIGUOUS_VERIFIED",
        "symbol": plans[0]["symbol"],
        "timeframe": plans[0]["timeframe"],
        "months": [p["month"] for p in plans],
        "rows": rows,
        "first_open_ms": first_open,
        "end_exclusive_ms": last_open + step,
        "canonical_series_sha256": rolling.hexdigest(),
    }


def audit_one_vs_four(root: Path, one_hour: list[dict], four_hour: list[dict], spec_sha: str) -> dict:
    """Audit source reconciliation without inventing historical corrections.

    Exact decimal equality is intentionally strict. One publisher's native 4h
    candles can differ from aggregation of its independently archived 1h bars.
    Record mismatches rather than treating either source as authoritative.
    """
    if (
        not one_hour or not four_hour
        or [p["month"] for p in one_hour] != [p["month"] for p in four_hour]
        or one_hour[0]["symbol"] != four_hour[0]["symbol"]
        or any(p["timeframe"] != "1h" for p in one_hour)
        or any(p["timeframe"] != "4h" for p in four_hour)
    ):
        raise ValueError("One-hour/four-hour reconciliation requires matching scope")

    one = audited_bars(root, one_hour, spec_sha)
    four = audited_bars(root, four_hour, spec_sha)
    discrepancies = Counter()
    examples = []
    comparisons = 0
    mismatched_rows = 0
    with localcontext() as decimal_context:
        decimal_context.prec = 34
        for native in four:
            group = []
            for offset in range(4):
                source = next(one, None)
                if source is None or source.open_time != native.open_time + offset * FRAME_MS["1h"]:
                    raise ValueError("1h/4h candle timeline mismatch")
                group.append(source)
            aggregate = {
                "open": group[0].open,
                "high": max(b.high for b in group),
                "low": min(b.low for b in group),
                "close": group[-1].close,
                "volume": sum((b.volume for b in group), Decimal(0)),
            }
            mismatched = [key for key in FIELDS if aggregate[key] != getattr(native, key)]
            comparisons += 1
            for key in mismatched:
                discrepancies[key] += 1
            if mismatched:
                mismatched_rows += 1
            if mismatched and len(examples) < MAX_SAMPLES:
                examples.append({
                    "open_ms": native.open_time,
                    "fields": {
                        key: {"from_1h": str(aggregate[key]), "native_4h": str(getattr(native, key))}
                        for key in mismatched
                    },
                })
        if next(one, None) is not None:
            raise ValueError("Unconsumed 1h source bars after all native 4h candles")

    return {
        "status": (
            "SOURCE_DISAGREEMENT_REVIEW_REQUIRED"
            if discrepancies else "SOURCE_AGGREGATION_EXACT_MATCH"
        ),
        "symbol": one_hour[0]["symbol"],
        "months": [p["month"] for p in one_hour],
        "native_4h_rows": comparisons,
        "mismatched_native_4h_rows": mismatched_rows,
        "field_mismatch_counts": dict(discrepancies),
        "sample_limit": MAX_SAMPLES,
        "samples": examples,
    }


def audit_pair(root: Path, one_hour: list[dict], four_hour: list[dict], spec_sha: str) -> dict:
    """One call performs both independent continuity checks and source audit."""
    source_one = audit_continuity(root, one_hour, spec_sha)
    source_four = audit_continuity(root, four_hour, spec_sha)
    comparison = audit_one_vs_four(root, one_hour, four_hour, spec_sha)
    return {
        "schema": 1,
        "source_spec_sha256": spec_sha,
        "one_hour": source_one,
        "four_hour": source_four,
        "comparison": comparison,
        "disposition": (
            "PASS" if comparison["status"] == "SOURCE_AGGREGATION_EXACT_MATCH"
            else "REVIEW_REQUIRED"
        ),
    }



def audit_fifteen_vs_hour(
    root: Path,
    fifteen_minute: list[dict],
    one_hour: list[dict],
    spec_sha: str,
) -> dict:
    """Compare independently pinned 15m archives with native 1h archives.

    Four completed 15m bars, never an in-progress partial bar, must match
    each native 1h bar. Exact Decimal comparisons deliberately flag publisher
    disagreements rather than silently substituting reconstructed values.
    """
    if (
        not fifteen_minute or not one_hour
        or [p["month"] for p in fifteen_minute] != [p["month"] for p in one_hour]
        or fifteen_minute[0]["symbol"] != one_hour[0]["symbol"]
        or any(p["timeframe"] != "15m" for p in fifteen_minute)
        or any(p["timeframe"] != "1h" for p in one_hour)
    ):
        raise ValueError("15m/1h reconciliation requires matching scope")
    smaller = audited_bars(root, fifteen_minute, spec_sha)
    larger = audited_bars(root, one_hour, spec_sha)
    discrepancies = Counter()
    samples = []
    comparisons = 0
    mismatched_rows = 0
    with localcontext() as decimal_context:
        decimal_context.prec = 34
        for native in larger:
            group = []
            for offset in range(4):
                source = next(smaller, None)
                if source is None or source.open_time != native.open_time + offset * FRAME_MS["15m"]:
                    raise ValueError("15m/1h candle timeline mismatch")
                group.append(source)
            aggregate = {
                "open": group[0].open,
                "high": max(b.high for b in group),
                "low": min(b.low for b in group),
                "close": group[-1].close,
                "volume": sum((b.volume for b in group), Decimal(0)),
            }
            mismatched = [key for key in FIELDS if aggregate[key] != getattr(native, key)]
            comparisons += 1
            if mismatched:
                mismatched_rows += 1
            for key in mismatched:
                discrepancies[key] += 1
            if mismatched and len(samples) < MAX_SAMPLES:
                samples.append({
                    "open_ms": native.open_time,
                    "fields": {
                        key: {"from_15m": str(aggregate[key]), "native_1h": str(getattr(native, key))}
                        for key in mismatched
                    },
                })
        if next(smaller, None) is not None:
            raise ValueError("Unconsumed 15m source bars after all native 1h candles")
    return {
        "status": (
            "SOURCE_DISAGREEMENT_REVIEW_REQUIRED"
            if discrepancies else "SOURCE_AGGREGATION_EXACT_MATCH"
        ),
        "symbol": fifteen_minute[0]["symbol"],
        "months": [p["month"] for p in fifteen_minute],
        "native_1h_rows": comparisons,
        "mismatched_native_1h_rows": mismatched_rows,
        "field_mismatch_counts": dict(discrepancies),
        "sample_limit": MAX_SAMPLES,
        "samples": samples,
    }


def audit_quarter_pair(
    root: Path,
    fifteen_minute: list[dict],
    one_hour: list[dict],
    spec_sha: str,
) -> dict:
    """Read-only 15m/1h cross-month continuity and reconciliation evidence."""
    source_fifteen = audit_continuity(root, fifteen_minute, spec_sha)
    source_one = audit_continuity(root, one_hour, spec_sha)
    comparison = audit_fifteen_vs_hour(root, fifteen_minute, one_hour, spec_sha)
    return {
        "schema": 1,
        "source_spec_sha256": spec_sha,
        "fifteen_minute": source_fifteen,
        "one_hour": source_one,
        "comparison": comparison,
        "disposition": (
            "PASS" if comparison["status"] == "SOURCE_AGGREGATION_EXACT_MATCH"
            else "REVIEW_REQUIRED"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline V5 source continuity and reconciliation audit")
    parser.add_argument("action", choices=("continuity", "reconcile-1h-4h", "reconcile-15m-1h"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", choices=FRAME_MS.keys(), default="1h")
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    args = parser.parse_args()
    spec, spec_sha = load_spec()
    root = valid_research_root(args.root)
    plans = batch_plan(spec, args.symbol, args.timeframe, args.start_month, args.end_month)
    if args.action == "continuity":
        result = audit_continuity(root, plans, spec_sha)
    elif args.action == "reconcile-1h-4h":
        one_hour = batch_plan(spec, args.symbol, "1h", args.start_month, args.end_month)
        four_hour = batch_plan(spec, args.symbol, "4h", args.start_month, args.end_month)
        result = audit_pair(root, one_hour, four_hour, spec_sha)
    else:
        fifteen_minute = batch_plan(spec, args.symbol, "15m", args.start_month, args.end_month)
        one_hour = batch_plan(spec, args.symbol, "1h", args.start_month, args.end_month)
        result = audit_quarter_pair(root, fifteen_minute, one_hour, spec_sha)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("disposition") == "REVIEW_REQUIRED":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
