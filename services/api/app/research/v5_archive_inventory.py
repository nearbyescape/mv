"""Read-only inventory of the frozen 30-symbol V5 historical archive universe.

This is a coverage gate, NOT a downloader, signal engine, or performance report.
A manifest plus ZIP on disk is PRESENT_UNVERIFIED until the caller explicitly
requests bounded full-content verification. Missing data never implies a listing
date, valid absence, or zero trading opportunities.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from zipfile import BadZipFile

from .v5_archives import (
    FRAME_MS,
    archive_location,
    archive_plan,
    load_spec,
    valid_research_root,
    verify_existing,
)

STATUSES = (
    "MISSING",
    "PRESENT_UNVERIFIED",
    "VERIFIED",
    "REVIEW_REQUIRED",
)
MAX_DEEP_MONTHS = 3
MAX_EXAMPLES = 30


def months_for_spec(spec: dict, first: str | None = None, last: str | None = None) -> list[str]:
    """Calendar months inside the pinned study, without the fetch batch cap."""
    begin = str(spec["history_start"])[:7]
    cutoff = datetime.strptime(spec["cutoff_exclusive"], "%Y-%m-%d")
    final = f"{cutoff.year:04d}-{cutoff.month:02d}"
    if cutoff.day != 1:
        raise ValueError("Pinned cutoff must start at a whole UTC calendar month")
    first = first or begin
    last = last or (
        f"{cutoff.year - 1:04d}-12"
        if cutoff.month == 1 else f"{cutoff.year:04d}-{cutoff.month - 1:02d}"
    )
    for value in (first, last):
        try:
            if datetime.strptime(value, "%Y-%m").strftime("%Y-%m") != value:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Month must use YYYY-MM") from exc
    if not begin <= first <= last < final:
        raise ValueError("Inventory range must be inside frozen completed study months")
    months = []
    current = datetime.strptime(first, "%Y-%m")
    until = datetime.strptime(last, "%Y-%m")
    while current <= until:
        months.append(current.strftime("%Y-%m"))
        year = current.year + (current.month == 12)
        month = current.month % 12 + 1
        current = current.replace(year=year, month=month)
    return months


def inspect_one(root: Path, plan: dict, spec_sha: str, *, deep_verify: bool = False) -> dict:
    """Conservative, filesystem-only status for one pre-approved source cell."""
    archive, sidecar = archive_location(root, plan)
    has_archive, has_manifest = archive.is_file(), sidecar.is_file()
    finding = {
        "symbol": plan["symbol"],
        "timeframe": plan["timeframe"],
        "month": plan["month"],
    }
    if not has_archive and not has_manifest:
        finding["status"] = "MISSING"
        return finding
    if not has_archive or not has_manifest:
        finding.update(
            status="REVIEW_REQUIRED",
            reason="ORPHAN_ZIP" if has_archive else "ORPHAN_MANIFEST",
        )
        return finding
    try:
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("Manifest must be a JSON object")
        for field in (
            "symbol", "timeframe", "month", "start_ms",
            "end_exclusive_ms", "expected_rows", "url",
        ):
            if record.get(field) != plan[field]:
                raise ValueError(f"Manifest field differs from frozen spec: {field}")
        if record.get("spec_sha256") != spec_sha:
            raise ValueError("Manifest research spec SHA-256 differs")
        checksum = record.get("source_sha256")
        if not isinstance(checksum, str) or len(checksum) != 64 or any(
            ch not in "0123456789abcdef" for ch in checksum
        ):
            raise ValueError("Invalid pinned archive SHA-256 format")
        if record.get("verified_rows") != plan["expected_rows"]:
            raise ValueError("Manifest candle count differs from expected full month")
        if deep_verify:
            verify_existing(root, plan, spec_sha)
        finding["status"] = "VERIFIED" if deep_verify else "PRESENT_UNVERIFIED"
        finding["source_sha256"] = checksum
    except (OSError, ValueError, KeyError, TypeError, BadZipFile) as exc:
        finding["status"] = "REVIEW_REQUIRED"
        finding["reason"] = type(exc).__name__ + ": " + str(exc)[:180]
    return finding


def inventory(
    root: Path,
    spec: dict,
    spec_sha: str,
    *,
    symbols: list[str],
    timeframes: list[str],
    months: list[str],
    deep_verify: bool = False,
    include_cells: bool = False,
) -> dict:
    if not symbols or not timeframes or not months:
        raise ValueError("Inventory scope cannot be empty")
    if len(set(symbols)) != len(symbols) or any(s not in spec["symbols"] for s in symbols):
        raise ValueError("Inventory contains duplicate or unapproved symbols")
    if len(set(timeframes)) != len(timeframes) or any(t not in FRAME_MS for t in timeframes):
        raise ValueError("Inventory contains duplicate or unsupported timeframes")
    if deep_verify and (len(symbols) != 1 or len(months) > MAX_DEEP_MONTHS):
        raise ValueError("Deep verification requires one symbol and at most three months")
    if any(m not in months_for_spec(spec) for m in months):
        raise ValueError("Inventory contains a month outside the frozen calendar")

    total = Counter()
    by_symbol = {}
    examples = []
    cells = []
    for symbol in symbols:
        counts = Counter()
        for timeframe in timeframes:
            for month in months:
                plan = archive_plan(spec, symbol, timeframe, month)
                result = inspect_one(root, plan, spec_sha, deep_verify=deep_verify)
                status = result["status"]
                total[status] += 1
                counts[status] += 1
                if include_cells:
                    cells.append(result)
                if status in ("MISSING", "REVIEW_REQUIRED") and len(examples) < MAX_EXAMPLES:
                    examples.append(result)
        by_symbol[symbol] = {
            "counts": {s: counts[s] for s in STATUSES},
            "archive_cells": sum(counts.values()),
            "coverage_complete": (
                counts["MISSING"] == 0 and counts["REVIEW_REQUIRED"] == 0
                and counts["PRESENT_UNVERIFIED"] == 0
            ),
        }
    n = sum(total.values())
    result = {
        "schema": 1,
        "status": (
            "REVIEW_REQUIRED" if total["REVIEW_REQUIRED"]
            else "INCOMPLETE" if total["MISSING"] or total["PRESENT_UNVERIFIED"]
            else "VERIFIED_COMPLETE"
        ),
        "source_spec_sha256": spec_sha,
        "source": "local monthly archive files and pinned manifests; no HTTP or writes",
        "deep_verified": deep_verify,
        "symbols": symbols,
        "timeframes": timeframes,
        "months": months,
        "expected_archive_cells": len(symbols) * len(timeframes) * len(months),
        "observed_archive_cells": n,
        "counts": {s: total[s] for s in STATUSES},
        "by_symbol": by_symbol,
        "actionable_examples": examples,
        "warning": (
            "PRESENT_UNVERIFIED is not source integrity proof. Missing or invalid "
            "archives do not establish inception/delisting or constitute strategy outcomes."
        ),
    }
    if include_cells:
        result["cells"] = cells
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline V5 30-coin archive coverage inventory")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", help="Optional one-symbol scope (default: frozen 30)")
    parser.add_argument("--timeframe", choices=tuple(FRAME_MS), help="Optional one timeframe")
    parser.add_argument("--start-month", help="Inclusive YYYY-MM; default frozen start")
    parser.add_argument("--end-month", help="Inclusive YYYY-MM; default frozen end")
    parser.add_argument("--deep-verify", action="store_true",
                        help="Re-hash and fully parse; at most three months/one symbol")
    parser.add_argument("--include-cells", action="store_true",
                        help="Emit each symbol/timeframe/month status in JSON")
    parser.add_argument("--require-complete", action="store_true",
                        help="Exit code 3 unless every selected archive is deeply verified")
    args = parser.parse_args()
    spec, sha = load_spec()
    root = valid_research_root(args.root)
    months = months_for_spec(spec, args.start_month, args.end_month)
    symbols = [args.symbol] if args.symbol else list(spec["symbols"])
    timeframes = [args.timeframe] if args.timeframe else list(FRAME_MS)
    result = inventory(
        root, spec, sha,
        symbols=symbols,
        timeframes=timeframes,
        months=months,
        deep_verify=args.deep_verify,
        include_cells=args.include_cells,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["counts"]["REVIEW_REQUIRED"] or (
        args.require_complete and result["status"] != "VERIFIED_COMPLETE"
    ):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
