"""Strict read-only T7Sonic episode diagnostics on *frozen* historical labels.

This runner requires both operator-verified source SHA256 digests. It
refuses changes to the pre-label decision stream or the retrospective
label stream; no trading decisions are changed by these diagnostics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .t7sonic_replay_cli import replay_plan
from .t7sonic_outcomes import research_outcomes
from .t7sonic_diagnostics import summarize_attribution

SHA = re.compile(r"[0-9a-f]{64}\Z")


def verified_diagnostics(root:Path, symbols:tuple[str,...], day:str,
                         expected_decision_sha:str, expected_label_sha:str,
                         maximum:int=288) -> dict:
    if not isinstance(expected_decision_sha,str) or not SHA.fullmatch(expected_decision_sha):
        raise ValueError("Exact 64-character pre-outcome decision SHA256 required")
    if not isinstance(expected_label_sha,str) or not SHA.fullmatch(expected_label_sha):
        raise ValueError("Exact 64-character retrospective label SHA256 required")
    plan=replay_plan(root,symbols,day,maximum)
    if plan["missing_monthly_pairs"]:
        raise FileNotFoundError("Missing verified source month pair")
    report=research_outcomes(
        root,symbols,day,maximum=maximum,include_episode_records=True
    )
    if report["decision_stream_sha256"]!=expected_decision_sha:
        raise ValueError("STOP: causal decision stream differs from frozen evidence")
    if report["label_stream_sha256"]!=expected_label_sha:
        raise ValueError("STOP: retrospective label stream differs from frozen evidence")
    result=summarize_attribution(report)
    result["verified_existing_decision_and_label_shas"]=True
    result["original_watches"]=report["watch_observations_repeated_same_setups"]
    result["original_expert_activations"]=report["expert_activation_episodes"]
    return result


def main() -> None:
    parser=argparse.ArgumentParser(
        description="T7Sonic after-label descriptive diagnostic, no trading actions"
    )
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbols",required=True)
    parser.add_argument("--day",required=True)
    parser.add_argument("--max-boundaries",type=int,default=288)
    parser.add_argument("--expected-decision-sha",required=True)
    parser.add_argument("--expected-label-sha",required=True)
    args=parser.parse_args()
    output=verified_diagnostics(
        Path(args.root),
        tuple(s.strip() for s in args.symbols.split(",")),
        args.day,args.expected_decision_sha,args.expected_label_sha,
        maximum=args.max_boundaries
    )
    print(json.dumps(output,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
