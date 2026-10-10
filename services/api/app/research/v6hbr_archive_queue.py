"""Bounded, operator-approved one-series-at-a-time V6HBR archive queue.

Plan is local and read-only. Fetch uses the inherited V5 downloader's
publisher SHA256, frozen manifest contract, complete candle counts and
append-only batch ledger. NEVER download the whole 30-coin backlog in one
action. Missing files are never synthesized. Partial ZIP/manifest pairs
fail closed rather than being overwritten.

No production integration, no broker API, no trade/Telegram actions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .v5_archives import archive_location, load_spec, valid_research_root
from .v5_archive_batch import MIB, batch_plan, fetch_batch

FRAMES = ("15m", "1h", "4h")
FIRST = "2026-01"
LAST = "2026-05"
MAX_NEW_MIB = 64
MIN_FREE_MIB = 2048


def next_missing_series(root: Path, spec: dict, *,
                        symbol: str | None = None) -> dict:
    frozen = spec.get("symbols")
    if not isinstance(frozen, list) or len(frozen) != 30 or len(set(frozen)) != 30:
        raise ValueError("Unreviewed frozen 30-symbol universe")
    if not root.is_absolute() or not root.is_dir():
        raise ValueError("Existing absolute research archive root required")
    if symbol is not None and symbol not in frozen:
        raise ValueError("Symbol absent from frozen archive contract")

    ordered = [symbol] if symbol else frozen
    present_pairs = 0
    for market in ordered:
        for frame in FRAMES:
            plans = batch_plan(spec, market, frame, FIRST, LAST)
            missing = []
            paired = []
            for plan in plans:
                archive, manifest = archive_location(root, plan)
                # Never trust symlink or incomplete half-written archive pair.
                if archive.is_symlink() or manifest.is_symlink():
                    raise ValueError("Refuse symlinked archive/manifest path")
                zip_exists = archive.is_file()
                sidecar_exists = manifest.is_file()
                if zip_exists != sidecar_exists:
                    raise ValueError(
                        "Partial archive/manifest pair requires operator review: "
                        f"{market} {frame} {plan['month']}"
                    )
                if zip_exists:
                    paired.append(plan["month"])
                else:
                    missing.append(plan["month"])
            present_pairs += len(paired)
            if missing:
                return {
                    "status": "ONE_SERIES_NEEDS_OPERATOR_APPROVED_FETCH",
                    "selected_symbol": market,
                    "selected_timeframe": frame,
                    "start_month": FIRST,
                    "end_month": LAST,
                    "series_months": len(plans),
                    "missing_months": missing,
                    "present_pair_months_to_verify_again": paired,
                    "max_new_mib": MAX_NEW_MIB,
                    "min_free_mib": MIN_FREE_MIB,
                    "plan_only": True,
                    "limitations": [
                        "Inventory checks presence only, not publisher SHA or candle integrity",
                        "The inherited fetch verifies every existing and newly acquired month",
                        "A source HTTP 404 or publisher checksum change stops the series and requires review",
                        "No more than five months in one requested symbol-timeframe batch",
                    ],
                }
    return {
        "status": "NO_MISSING_SOURCE_PAIRS_IN_SELECTED_SCOPE",
        "selected_symbol": symbol,
        "present_pair_months_examined": present_pairs,
        "plan_only": True,
        "limitations": [
            "Complete archive pair presence still requires full SHA and timeline verification"
        ],
    }


def acquire_planned_series(root: Path, spec: dict, spec_sha: str,
                           plan: dict, *, confirm_fetch: bool) -> dict:
    if not confirm_fetch:
        raise ValueError("Explicit --confirm-fetch required")
    if plan["status"] != "ONE_SERIES_NEEDS_OPERATOR_APPROVED_FETCH":
        raise ValueError("No missing series to fetch")
    series = batch_plan(
        spec, plan["selected_symbol"], plan["selected_timeframe"],
        plan["start_month"], plan["end_month"]
    )
    result = fetch_batch(
        root, series, spec_sha,
        max_new_bytes=MAX_NEW_MIB*MIB,
        min_free_bytes=MIN_FREE_MIB*MIB,
        delay_seconds=1.25,
    )
    return {
        "status": "ONE_SERIES_ACQUIRED_AND_VERIFIED",
        "symbol": plan["selected_symbol"],
        "timeframe": plan["selected_timeframe"],
        "series": result,
        "fetch_is_exclusively_research_archive_io": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V6HBR bounded 5-month research-data acquisition")
    parser.add_argument("action", choices=("plan", "fetch"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", help="Optional one symbol from frozen research contract")
    parser.add_argument("--confirm-fetch", action="store_true")
    args = parser.parse_args()
    if args.action == "fetch" and not args.confirm_fetch:
        parser.error("fetch requires --confirm-fetch")
    if args.action == "plan" and args.confirm_fetch:
        parser.error("--confirm-fetch is only valid for fetch")
    spec, sha = load_spec()
    root = valid_research_root(args.root)
    queue = next_missing_series(root, spec, symbol=args.symbol)
    if args.action == "plan":
        output = {"schema": 1, "frozen_spec_sha256": sha, **queue}
    elif queue["status"] != "ONE_SERIES_NEEDS_OPERATOR_APPROVED_FETCH":
        output = {"schema": 1, **queue}
    else:
        output = {
            "schema": 1, "frozen_spec_sha256": sha,
            **acquire_planned_series(root, spec, sha, queue,
                                     confirm_fetch=args.confirm_fetch),
        }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
