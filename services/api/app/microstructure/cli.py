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

from .core import SYMBOLS
from .journal import open_journal, record_snapshot, report
from .public import capture_all


def _path(value:str) -> Path:
    p=Path(value)
    if not p.is_absolute():
        raise ValueError("Use an absolute path for the isolated journal")
    return p


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
                    started=time.monotonic()
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
                    await asyncio.sleep(max(0,args.interval_seconds-(time.monotonic()-started)))
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
    args=p.parse_args()
    if args.action=="observe":
        asyncio.run(_observe(args))
    else:
        dbpath=_path(args.db)
        with open_journal(dbpath,readonly=True) as db:
            print(json.dumps(report(db),sort_keys=True,indent=2))


if __name__=="__main__":
    main()
