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

import httpx

from filelock import FileLock, Timeout

from .core import PARAMETERS, SYMBOLS
from .journal import open_journal, record_snapshot, report
from .quality import quality_report
from .strict_backtest import backtest_from_journal
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

# A bounded number of failed FULL-BATCH observations may be retried at the
# normal five-minute cadence. Legal/rate-limit errors ALWAYS halt; SQLite
# writes and unexpected programming/runtime errors also halt immediately.
MAX_CONSECUTIVE_TRANSIENT_GAPS = 3


def _transient_market_data_gap(exc: Exception) -> bool:
    """Recognize only recoverable public reads and invalid transient snapshots.

    Never retry rate limits (418/429), region restrictions (451), other 4xx,
    DB or programming faults; no fallback host or exchange order endpoint.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code <= 599
    return isinstance(exc, (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.RemoteProtocolError,
        ValueError,
    ))


def _market_gap_label(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP_{exc.response.status_code}"
    return type(exc).__name__



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
                consecutive_gaps=0
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
                    try:
                        captures=await capture_all()
                    except Exception as exc:
                        if args.iterations != 0 or not _transient_market_data_gap(exc):
                            raise
                        # The collector may continue after a transient network
                        # or data-quality gap, but NEVER commits a partial
                        # six-coin batch or invents a replacement observation.
                        consecutive_gaps+=1
                        will_retry=consecutive_gaps<MAX_CONSECUTIVE_TRANSIENT_GAPS
                        print(json.dumps({
                            "kind":"PUBLIC_MARKET_PAPER_COLLECTION_GAP",
                            "error_code":_market_gap_label(exc),
                            "consecutive_gaps":consecutive_gaps,
                            "retry_after_seconds":args.interval_seconds if will_retry else None,
                            "observations_committed":0,
                            "client_publication_authorized":False,
                            "submitted_orders":0,"sent_telegram":0,
                        },sort_keys=True),flush=True)
                        if not will_retry:
                            raise RuntimeError(
                                "PUBLIC_RESEARCH_COLLECTION_HALTED_REQUIRES_OPERATOR_REVIEW"
                            ) from exc
                        # Do not retry within a five-minute candle. This
                        # deliberate gap makes subsequent classifier windows
                        # fail closed until two valid fresh samples exist.
                        await asyncio.sleep(args.interval_seconds)
                        continue
                    consecutive_gaps=0
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
    backtest=sub.add_parser(
        "backtest",
        help="strict source-verified causal replay; NOT executable trading P&L",
    )
    backtest.add_argument("--max-observations",type=int,default=75000)
    args=p.parse_args()
    if args.action=="observe":
        asyncio.run(_observe(args))
    elif args.action=="backtest":
        # Opens existing live journal in read-only mode; all replication
        # writes target a self-cleaning temporary DB only.
        payload=backtest_from_journal(
            _path(args.db),max_observations=args.max_observations,
        )
        print(json.dumps(payload,sort_keys=True,indent=2))
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
