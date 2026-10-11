"""Retrospective T7Sonic directional-watch outcomes, offline and development only.

A separate research *labeling* stage runs after all causal watch decisions
are frozen. No trained forecast, real fills, orders or live signal output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .t7sonic_replay_cli import replay_plan
from .t7sonic_outcomes import research_outcomes


def main():
    parser=argparse.ArgumentParser(
        description="T7Sonic 15/30/60/120 minute historical mark proxy labels"
    )
    parser.add_argument("action",choices=("plan","run"))
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbols",required=True)
    parser.add_argument("--day",required=True)
    parser.add_argument("--max-boundaries",type=int,default=288)
    parser.add_argument("--include-episode-records",action="store_true")
    args=parser.parse_args()
    symbols=tuple(s.strip() for s in args.symbols.split(","))
    root=Path(args.root)
    preflight=replay_plan(root,symbols,args.day,args.max_boundaries)
    # The existing WATCH replay plan checks current source presence.
    # Future 1m labels must independently verify complete month archives
    # (and can additionally require next month at a month boundary).
    if args.action=="plan":
        report=preflight
        report["outcome_extra_source_requirement"]=(
            "Verified 1m bars through max requested event boundary plus "
            "120 minutes; next month if boundary crosses month end"
        )
        report["future_source_presence_not_checked"]=True
    else:
        if preflight["missing_monthly_pairs"]:
            raise FileNotFoundError("Missing causal source month; run plan first")
        report=research_outcomes(
            root,symbols,args.day,maximum=args.max_boundaries,
            include_episode_records=args.include_episode_records
        )
    print(json.dumps(report,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
