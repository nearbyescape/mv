"""Explicit one-day T7Sonic *watch* replay CLI (read-only; never publishes).

Plan only checks which already-pinned monthly source files exist.
Run performs complete source integrity & cross-resolution verification
before counting opportunities from 5-minute decision boundaries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .t7sonic_history import (
    FROZEN_MARKETS, HISTORICAL_FRAMES, MAX_INPUT_SYMBOLS,
    _calendar_months, _necessary_first_ms, _source_location,
)
from .t7sonic_replay import bounded_boundaries, replay_day


def replay_plan(root: Path, symbols: tuple[str,...], day: str,
                maximum: int=288) -> dict:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Real absolute preexisting archive root required")
    if (not isinstance(symbols,tuple) or not 1<=len(symbols)<=MAX_INPUT_SYMBOLS
        or len(set(symbols))!=len(symbols)
        or any(s not in FROZEN_MARKETS for s in symbols)):
        raise ValueError("Explicit 1–6 symbol subset required")
    boundaries=bounded_boundaries(day,maximum=maximum)
    targets=[]
    missing=[]
    for symbol in symbols:
        for frame in HISTORICAL_FRAMES:
            begin,_=_necessary_first_ms(frame,boundaries[0])
            step={"1m":60_000,"15m":900_000,"1h":3_600_000,
                  "4h":14_400_000}[frame]
            end=(boundaries[-1]//step)*step
            for month in _calendar_months(begin,end):
                source,sidecar=_source_location(root,symbol,frame,month)
                if any(p.is_symlink() for p in (source.parent,source,sidecar)):
                    raise ValueError("Symlinked research source forbidden")
                current={
                    "symbol":symbol,"frame":frame,"month":month,
                    "source_present":source.is_file(),
                    "sidecar_present":sidecar.is_file(),
                }
                targets.append(current)
                if not current["source_present"] or not current["sidecar_present"]:
                    missing.append(current)
    return {
        "schema":1,"status":"PRESENCE_ONLY_NOT_SOURCE_CHECKSUM_VALIDATION",
        "partition":"APRIL_MAY_DEVELOPMENT_ONLY",
        "date":day,"symbols":list(symbols),
        "requested_five_minute_decisions":len(boundaries),
        "required_monthly_pairs":targets,
        "missing_monthly_pairs":missing,
        "ready_for_full_source_verification":not missing,
        "market_data_download_performed":False,
        "production_mutation":False,
    }


def main():
    parser=argparse.ArgumentParser(description="T7Sonic development WATCH replay")
    parser.add_argument("action",choices=("plan","run"))
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbols",required=True)
    parser.add_argument("--day",required=True,
                        help="Single April–May 2026 UTC development day")
    parser.add_argument("--max-boundaries",type=int,default=288,
                        help="1..288 completed 5m decision periods")
    args=parser.parse_args()
    symbols=tuple(part.strip() for part in args.symbols.split(","))
    root=Path(args.root)
    preflight=replay_plan(root,symbols,args.day,args.max_boundaries)
    if args.action=="run":
        if preflight["missing_monthly_pairs"]:
            raise FileNotFoundError("Source archive/sidecar missing; run plan first")
        result=replay_day(root,symbols,args.day,maximum=args.max_boundaries)
    else:
        result=preflight
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
