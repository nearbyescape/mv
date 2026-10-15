"""Six-month historical evaluation of ONE frozen alternative versus failed V7.

No tuning, no new source acquisition, no live API, no Telegram, no orders.
All 2026 Apr-Sep inputs have already been inspected in previous MV research:
this comparison is EXPLORATORY and must NEVER be called independent holdout.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

from .v7_recovery_archives import MARKETS, MONTHS, verified_series
from .v7_recovery_engine import portfolio_simulation
from .v7_recovery_study import _summary
from .v7_final_breakout import POLICY, POLICY_SHA256, breakout_portfolio

IST = timezone(timedelta(minutes=330))
BLOCKS = {
    "APR_MAY_DEVELOPMENT": ("2026-04", "2026-05"),
    "JUN_JUL_INSPECTED": ("2026-06", "2026-07"),
    "AUG_SEP_INSPECTED": ("2026-08", "2026-09"),
}


def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms/1000,IST).strftime("%Y-%m-%d")


def _dates(first_ms: int,last_ms: int) -> list[str]:
    first = datetime.fromtimestamp(first_ms/1000,IST).date()
    last = datetime.fromtimestamp((last_ms-1)/1000,IST).date()
    return [
        (first + timedelta(days=i)).isoformat()
        for i in range((last-first).days+1)
    ]


def _summaries(trades:list[dict], days:list[str]) -> dict:
    blocks={}
    for label, months in BLOCKS.items():
        period=[d for d in days if d[:7] in months]
        dayset=set(period)
        selected=[t for t in trades if _date(t["decision_boundary_ms"]) in dayset]
        blocks[label]=_summary(selected,period)
    return blocks


def evaluate_saved_archives(root: Path) -> dict:
    if (not isinstance(root,Path) or not root.is_absolute() or
            root.is_symlink() or not root.is_dir()):
        raise ValueError("Exact existing absolute research archive root required")
    sources={}
    provenance={}
    for symbol in MARKETS:
        sources[symbol],provenance[symbol]=verified_series(root,symbol,MONTHS)
    initial={symbol:len(bars) for symbol,bars in sources.items()}
    if set(initial.values())!={17568}:
        raise ValueError("Expected complete Apr–Sep 2026 source bars")
    baseline=portfolio_simulation(sources)
    challenger=breakout_portfolio(sources)
    if any(
        x["client_publication_authorized"] is not False or
        x["telegram_messages_sent"] != 0 or x["orders_submitted"] != 0
        for x in (baseline,challenger)
    ):
        raise RuntimeError("Research module activated production channel")
    days=_dates(
        sources[MARKETS[0]][0].open_ms,
        sources[MARKETS[0]][-1].open_ms+900_000,
    )
    old=_summary(baseline["modeled_references"],days)
    new=_summary(challenger["modeled_references"],days)
    old_by=_summaries(baseline["modeled_references"],days)
    new_by=_summaries(challenger["modeled_references"],days)
    eligible=(
        new["hypothetical_closed_ideas"]>=100 and
        new["days_with_closed_ideas"]>=30 and
        new["mean_costed_R_per_closed_reference"] is not None and
        new["mean_costed_R_per_closed_reference"]>0 and
        new["day_cluster_bootstrap_mean_R_95pct"][0]>0 and
        new["illustrative_closed_trades_only_max_drawdown"]<=0.25 and
        new_by["APR_MAY_DEVELOPMENT"]["mean_costed_R_per_closed_reference"] is not None and
        new_by["APR_MAY_DEVELOPMENT"]["mean_costed_R_per_closed_reference"]>0 and
        new_by["JUN_JUL_INSPECTED"]["mean_costed_R_per_closed_reference"] is not None and
        new_by["JUN_JUL_INSPECTED"]["mean_costed_R_per_closed_reference"]>0 and
        new_by["AUG_SEP_INSPECTED"]["mean_costed_R_per_closed_reference"] is not None and
        new_by["AUG_SEP_INSPECTED"]["mean_costed_R_per_closed_reference"]>0
    )
    return {
        "status":"V7_FINAL_HISTORICAL_COSTED_COMPARISON_NO_TRADING",
        "schema":1,
        "model_name":POLICY,
        "frozen_policy_sha256":POLICY_SHA256,
        "market_count":len(sources),
        "markets":list(MARKETS),
        "months":list(MONTHS),
        "15m_complete_rows_per_market":initial,
        "source_provenance":provenance,
        "prior_failed_paper_model":{
            "policy":baseline["policy"],
            "proposals":baseline["proposals_before_portfolio_constraints"],
            "selected":baseline["selected_paper_references"],
            "aggregate":old,
            "chronological_blocks":old_by,
        },
        "candidate_breakout_model":{
            "policy":challenger["policy"],
            "proposals":challenger["proposals_before_portfolio_constraints"],
            "selected":challenger["selected_paper_references"],
            "aggregate":new,
            "chronological_blocks":new_by,
            "reasons_by_market":challenger["reasons_by_market"],
            "portfolio_suppression_reasons":challenger["portfolio_suppression_reasons"],
        },
        "research_meets_exploratory_pre_specified_gate":eligible,
        "production_deployment_authorized":False,
        "independent_out_of_sample_proven":False,
        "pre_2026_10_15_historical_development_and_inspected_periods":True,
        "hypothetical_next_15m_open_not_live_entry_fill":True,
        "publisher_checksum_not_exchange_source_signature":True,
        "real_quote_slippage_funding_unverified":True,
        "client_publication_authorized":False,
        "orders_submitted":0,
        "telegram_messages_sent":0,
    }


def main():
    import argparse
    p=argparse.ArgumentParser(description="No-network V7 final research comparison")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",help="Create-only JSON destination")
    args=p.parse_args()
    report=evaluate_saved_archives(Path(args.data_root))
    output=json.dumps(report,sort_keys=True,indent=2)+"\n"
    if args.output:
        target=Path(args.output)
        if not target.is_absolute() or target.is_symlink():
            p.error("Only absolute, non-symlink create-only output paths")
        with target.open("x",encoding="utf-8") as h:
            h.write(output)
    else:
        print(output,end="")


if __name__=="__main__":
    main()
