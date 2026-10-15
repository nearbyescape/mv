"""CLI for V7Sonic prospective microstructure paper-only research.

SAFE DEFAULT: --help / report only. Public network requires two exact
opt-in flags. This CLI has no exchange credential or Telegram facility.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import time

from filelock import FileLock, Timeout

from .core import PARAMETERS, SYMBOLS
from .journal import open_journal, record_snapshot, report
from .quality import quality_report
from .public import capture_all


def _path(value:str) -> Path:
    p=Path(value)
    if not p.is_absolute():
        raise ValueError("Use an absolute path for the isolated journal")
    return p


# We must schedule from PERSISTED receive timestamps, not monotonic time at
# the START of a previous six-market request batch. Network-duration jitter
# otherwise produces 299.9s sample gaps that fail the strict >=300s contract.
# Two seconds is a transport/scheduler guard; the classifier threshold is
# unchanged, and we never invent or timestamp-shift an exchange observation.
CAPTURE_GUARD_MS = 2_000


def _seconds_until_capture(conn, observed_wall_ms: int, cadence_seconds: int) -> float:
    """Use the latest stored sample across ALL markets as the safe boundary.

    Waiting for the maximum prior timestamp guarantees that even the earliest
    market in the NEXT sequential capture starts at least 300 seconds after
    every previously recorded market. It also works across worker restarts,
    existing journals, different REST request durations and clock adjustments.
    """
    if type(observed_wall_ms) is not int or observed_wall_ms <= 0:
        raise ValueError("Invalid wall clock")
    if type(cadence_seconds) is not int or cadence_seconds < 300:
        raise ValueError("Minimum public sampling interval is 300 seconds")
    last = conn.execute(
        "SELECT MAX(observed_at_ms) FROM observations"
    ).fetchone()[0]
    if last is None:
        return 0.0
    required = last + max(
        PARAMETERS["minimum_interval_ms"] + CAPTURE_GUARD_MS,
        cadence_seconds * 1_000,
    )
    return max(0.0, (required - observed_wall_ms) / 1_000)


async def _observe(args):
    if not args.allow_public_market_data or not args.confirm_paper_only:
        raise ValueError("Public network requires both explicit opt-in flags")
    if args.iterations<0 or args.interval_seconds<300:
        raise ValueError("Minimum public sampling interval is 300 seconds")
    dbfile=_path(args.db)
    lock=FileLock(str(dbfile)+".lock",timeout=0)
    try:
        with lock:
            with open_journal(dbfile) as db:
                completed=0
                while args.iterations==0 or completed<args.iterations:
                    # A 300s start-to-start timer is NOT sufficient: the
                    # last observed receive timestamp may shift by ~100ms.
                    # Recheck the journal deadline after each sleep to remain
                    # fail closed if the wall clock is adjusted backwards.
                    while True:
                        remaining = _seconds_until_capture(
                            db, time.time_ns() // 1_000_000,
                            args.interval_seconds,
                        )
                        if remaining <= 0:
                            break
                        await asyncio.sleep(remaining)
                    # No partial six-market batch. An unavailable public
                    # source is not silently turned into a scored candidate.
                    captures=await capture_all()
                    decisions=[]
                    for item in captures:
                        result=record_snapshot(db,item)
                        decisions.append({
                            "symbol":item["symbol"],"stored":result["stored"],
                            "decision":result["decision"]["status"],
                            "reason":result["decision"].get("reason"),
                        })
                    completed+=1
                    print(json.dumps({
                        "kind":"PUBLIC_MARKET_PAPER_CAPTURE","iteration":completed,
                        "decisions":decisions,"client_publication_authorized":False,
                        "submitted_orders":0,"sent_telegram":0,
                    },sort_keys=True),flush=True)
                    if args.iterations==completed:
                        break
                    # The next iteration computes its delay from timestamps
                    # actually committed to SQLite, not this iteration's start.
    except Timeout as exc:
        raise RuntimeError("Another isolated research sampler holds the lock") from exc


def main():
    p=argparse.ArgumentParser(
        description="V7 isolated public-market evidence; NO TRADES OR TELEGRAM",
    )
    p.add_argument("--db",required=True,help="absolute separate SQLite journal path")
    sub=p.add_subparsers(dest="action",required=True)
    observe=sub.add_parser("observe",help="explicitly opt into public Binance REST")
    observe.add_argument("--allow-public-market-data",action="store_true")
    observe.add_argument("--confirm-paper-only",action="store_true")
    observe.add_argument("--iterations",type=int,default=1,
                         help="1 = one six-market capture; 0 = continuous")
    observe.add_argument("--interval-seconds",type=int,default=300)
    sub.add_parser("report",help="offline, read-only, chain-checked report")
    diagnose=sub.add_parser("diagnose",help="offline, causal first-rejection audit")
    diagnose.add_argument(
        "--last-samples-per-symbol",type=int,default=288,
        help="2-2880 most recent observations per coin; no market network",
    )
    args=p.parse_args()
    if args.action=="observe":
        asyncio.run(_observe(args))
    else:
        dbpath=_path(args.db)
        with open_journal(dbpath,readonly=True) as db:
            if args.action=="diagnose":
                payload=quality_report(
                    db,last_samples_per_symbol=args.last_samples_per_symbol,
                )
            else:
                payload=report(db)
            print(json.dumps(payload,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
