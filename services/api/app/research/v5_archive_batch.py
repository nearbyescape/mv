"""Bounded one-symbol/month-series pilot for immutable V5 research archives.

This is *not* an unattended full-watchlist downloader. It never accesses the MV
database or live collector. A failed month is recorded and halts the batch.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time

import httpx

from .v5_archives import (
    MAX_COMPRESSED_BYTES,
    acquire_one,
    archive_location,
    archive_plan,
    load_spec,
    single_archive_lock,
    valid_research_root,
    verify_existing,
)

MIB = 1024 * 1024
MAX_BATCH_ARCHIVES = 6
MAX_BATCH_NEW_MIB = 256


def months_inclusive(first: str, last: str) -> list[str]:
    """Enumerate whole calendar months without relying on wall-clock locale."""
    try:
        start = datetime.strptime(first, "%Y-%m")
        end = datetime.strptime(last, "%Y-%m")
    except ValueError as exc:
        raise ValueError("Month range must be YYYY-MM") from exc
    if start.strftime("%Y-%m") != first or end.strftime("%Y-%m") != last or end < start:
        raise ValueError("Month range invalid or reversed")
    result = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        result.append(f"{year:04d}-{month:02d}")
        year, month = year + (month == 12), month % 12 + 1
        if len(result) > MAX_BATCH_ARCHIVES:
            raise ValueError("Batch exceeds six-month safety limit")
    return result


def batch_plan(spec: dict, symbol: str, timeframe: str, first: str, last: str) -> list[dict]:
    return [archive_plan(spec, symbol, timeframe, month) for month in months_inclusive(first, last)]


def _event_log(root: Path, plans: list[dict]) -> Path:
    first = plans[0]
    return (
        root / "batch-ledgers"
        / f"{first['symbol']}-{first['timeframe']}-{plans[0]['month']}-to-{plans[-1]['month']}.jsonl"
    )


def _record(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _failure_kind(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        # HTTP 404 is *not* evidence of listing date or non-tradability.
        return "SOURCE_HTTP_404_REQUIRES_REVIEW"
    return "ACQUISITION_OR_VERIFICATION_FAILURE"


def fetch_batch(
    root: Path,
    plans: list[dict],
    spec_sha: str,
    *,
    max_new_bytes: int,
    min_free_bytes: int,
    delay_seconds: float,
) -> dict:
    """Serial, bounded, resumable acquisition with append-only local audit.

    A previously validated archive is verified again against the current
    publisher checksum. Downloads do not touch the output archive path until
    the current month's full digest and continuity checks have passed.
    """
    if not plans or len(plans) > MAX_BATCH_ARCHIVES:
        raise ValueError("Batch must contain 1..6 archives")
    if type(max_new_bytes) is not int or not 0 < max_new_bytes <= MAX_BATCH_NEW_MIB * MIB:
        raise ValueError("Batch compressed-byte budget must be 1..256 MiB")
    if type(min_free_bytes) is not int or min_free_bytes < MIB:
        raise ValueError("Minimum free storage must be at least 1 MiB")
    if not 0.5 <= delay_seconds <= 60:
        raise ValueError("Polite request delay must be between 0.5 and 60 seconds")
    if not root.is_dir():
        raise FileNotFoundError("Research archive root must already exist")
    ledger = _event_log(root, plans)
    new_bytes = 0
    states = []
    # Concurrent invocations for this particular symbol/month-series cannot
    # race to append to the same ledger or exceed the same budget.
    with single_archive_lock(ledger.with_suffix(".lock")):
        for index, plan in enumerate(plans):
            archive, _ = archive_location(root, plan)
            was_present = archive.is_file()
            event = {
                "time_utc": datetime.now(timezone.utc).isoformat(),
                "spec_sha256": spec_sha,
                "symbol": plan["symbol"],
                "timeframe": plan["timeframe"],
                "month": plan["month"],
                "source_url": plan["url"],
            }
            try:
                if not was_present:
                    available = shutil.disk_usage(root).free
                    if available < min_free_bytes + min(MAX_COMPRESSED_BYTES, max_new_bytes - new_bytes):
                        raise OSError("Research disk free-space safety floor not met")
                    if new_bytes >= max_new_bytes:
                        raise ValueError("Batch compressed-byte budget exhausted")
                # Enforce the remaining *overall* budget during each streamed
                # download, before the ZIP and evidence manifest are published.
                cap = max(1, min(MAX_COMPRESSED_BYTES, max_new_bytes - new_bytes))
                record = acquire_one(root, plan, spec_sha, max_archive_bytes=cap)
                status = "VERIFIED_EXISTING" if was_present else "ACQUIRED_AND_VERIFIED"
                if not was_present:
                    new_bytes += record["compressed_bytes"]
                event.update({
                    "status": status,
                    "sha256": record["source_sha256"],
                    "rows": record["verified_rows"],
                    "compressed_bytes": record["compressed_bytes"],
                })
                _record(ledger, event)
                states.append(event)
            except Exception as exc:
                event.update({
                    "status": _failure_kind(exc),
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:250],
                })
                _record(ledger, event)
                raise
            if index + 1 < len(plans):
                time.sleep(delay_seconds)
    return {
        "status": "COMPLETE",
        "archives_verified": len(states),
        "new_compressed_bytes": new_bytes,
        "audit_ledger": str(ledger),
        "results": states,
    }


def verify_batch(root: Path, plans: list[dict], spec_sha: str) -> dict:
    """Filesystem-only, read-only verification; no HTTP or ledger changes."""
    results = []
    for plan in plans:
        record = verify_existing(root, plan, spec_sha)
        results.append({
            "month": plan["month"],
            "status": "VERIFIED",
            "rows": record["verified_rows"],
            "sha256": record["source_sha256"],
        })
    return {"status": "COMPLETE", "archives_verified": len(results), "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="V5 research: at most six monthly archives per batch")
    parser.add_argument("action", choices=("plan", "fetch", "verify"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True)
    parser.add_argument("--start-month", required=True)
    parser.add_argument("--end-month", required=True)
    parser.add_argument("--max-new-mib", type=int, default=64)
    parser.add_argument("--min-free-mib", type=int, default=2048)
    parser.add_argument("--delay-seconds", type=float, default=1.25)
    parser.add_argument("--confirm-fetch", action="store_true")
    args = parser.parse_args()
    spec, spec_sha = load_spec()
    root = valid_research_root(args.root)
    plans = batch_plan(spec, args.symbol, args.timeframe, args.start_month, args.end_month)
    if args.action == "plan":
        result = {
            "status": "PLANNED_ONLY",
            "spec_sha256": spec_sha,
            "root": str(root),
            "archives": [{
                "month": p["month"],
                "expected_rows": p["expected_rows"],
                "url": p["url"],
            } for p in plans],
        }
    elif args.action == "verify":
        result = verify_batch(root, plans, spec_sha)
    else:
        if not args.confirm_fetch:
            parser.error("fetch requires explicit --confirm-fetch (plan first)")
        result = fetch_batch(
            root, plans, spec_sha,
            max_new_bytes=args.max_new_mib * MIB,
            min_free_bytes=args.min_free_mib * MIB,
            delay_seconds=args.delay_seconds,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
