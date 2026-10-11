"""T7Sonic one-boundary historical development pilot; no network or writes.

Plan command reports presence only (never claims source integrity).
Run command verifies *complete* pinned source ZIPs and manifest sidecars
before computing descriptive WATCH-only hypotheses.
Example:
  python -m app.research.t7sonic_history_cli plan --root /research \
    --symbols BTCUSDT --at 2026-04-20T12:00:00Z
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .t7sonic_history import (
    FROZEN_MARKETS, HISTORICAL_FRAMES, INTERVAL_MS, MAX_INPUT_SYMBOLS,
    _calendar_months, _necessary_first_ms, _source_location,
    historical_research_case,
)

ISO_UTC = re.compile(r"2026-(?:04|05)-\d\dT\d\d:\d\d:00Z\Z")


def _date_ms(value: str) -> int:
    if not isinstance(value, str) or not ISO_UTC.fullmatch(value):
        raise ValueError("Require explicit April–May UTC YYYY-MM-DDTHH:MM:00Z")
    date = datetime.fromisoformat(value.replace("Z","+00:00"))
    if date.tzinfo != timezone.utc:
        raise ValueError("UTC as-of timestamp mandatory")
    t = int(date.timestamp()*1000)
    if t % INTERVAL_MS["5m"]:
        raise ValueError("Research boundary must align to completed five-minute data")
    return t


def plan_history(root: Path, symbols: tuple[str, ...], as_of_ms: int) -> dict:
    if not isinstance(symbols, tuple) or not 1 <= len(symbols) <= MAX_INPUT_SYMBOLS:
        raise ValueError("Only explicit 1–6 market smoke subsets accepted")
    if len(set(symbols)) != len(symbols) or any(s not in FROZEN_MARKETS for s in symbols):
        raise ValueError("Duplicate/unfrozen source market")
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Research root must be an existing absolute real directory")
    missing = []
    expected = {}
    for symbol in symbols:
        expected[symbol] = {}
        for frame in HISTORICAL_FRAMES:
            begin, end = _necessary_first_ms(frame,as_of_ms)
            months = _calendar_months(begin,end)
            expected[symbol][frame] = list(months)
            for month in months:
                source, sidecar = _source_location(root,symbol,frame,month)
                if source.is_symlink() or sidecar.is_symlink():
                    raise ValueError("Symbolic archive link forbidden")
                if not source.is_file() or not sidecar.is_file():
                    missing.append({
                        "symbol":symbol,"frame":frame,"month":month,
                        "archive_present":source.is_file(),
                        "manifest_present":sidecar.is_file(),
                    })
    return {
        "schema":1,
        "action":"PRESENCE_CHECK_ONLY",
        "as_of_ms":as_of_ms, "symbols":list(symbols),
        "required_source_months_by_market_frame":expected,
        "missing_pinned_month_pairs":missing,
        "ready_for_complete_checksum_validation":len(missing)==0,
        "source_integrity_not_tested":True,
        "development_only":True,
        "publication_authorized":False,
    }


def main():
    parser = argparse.ArgumentParser(description="T7Sonic isolated historical snapshot")
    parser.add_argument("action",choices=("plan","run"))
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbols",required=True,
                        help="Explicit 1–6 frozen symbols, comma separated")
    parser.add_argument("--at",required=True,
                        help="April or May 2026 UTC five-minute cutoff, ISO8601 Z")
    args = parser.parse_args()
    root = Path(args.root)
    markets = tuple(s.strip() for s in args.symbols.split(","))
    when = _date_ms(args.at)
    if args.action == "plan":
        result = plan_history(root,markets,when)
    else:
        planned = plan_history(root,markets,when)
        if not planned["ready_for_complete_checksum_validation"]:
            raise FileNotFoundError(
                "Missing pinned source archive/sidecar; run plan for exact required months"
            )
        result = historical_research_case(root,markets,when)
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__ == "__main__":
    main()
