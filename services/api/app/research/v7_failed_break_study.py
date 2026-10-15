"""Pinned Apr–Sep V7Sonic false-break evaluation versus BOTH failed strategies.

This is an EXPLORATORY comparison because previous MV work inspected the
same period. It must not be described as independent validation or traded.
"""
from __future__ import annotations

from datetime import datetime,timezone,timedelta
from pathlib import Path
import argparse
import json

from .v7_recovery_archives import MARKETS,MONTHS,verified_series
from .v7_recovery_engine import portfolio_simulation
from .v7_final_breakout import breakout_portfolio
from .v7_failed_break_reversal import reversal_portfolio,POLICY,POLICY_SHA256
from .v7_recovery_study import _summary

IST=timezone(timedelta(hours=5,minutes=30))
PERIODS={
    "APR_MAY_2026":("2026-04","2026-05"),
    "JUN_JUL_2026":("2026-06","2026-07"),
    "AUG_SEP_2026":("2026-08","2026-09"),
}


def local_day(t:int) -> str:
    return datetime.fromtimestamp(t/1000,IST).date().isoformat()


def run(root:Path) ->dict:
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Research data root must exist and be absolute")
    sources={}
    manifest={}
    for market in MARKETS:
        sources[market],manifest[market]=verified_series(root,market,MONTHS)
        if len(sources[market])!=17568:
            raise ValueError("Incorrect full six-month market coverage")

    baseline=portfolio_simulation(sources)
    breakout=breakout_portfolio(sources)
    reversal=reversal_portfolio(sources)
    first=datetime.fromtimestamp(sources[MARKETS[0]][0].open_ms/1000,IST).date()
    last=datetime.fromtimestamp(
        (sources[MARKETS[0]][-1].open_ms+900_000-1)/1000,IST
    ).date()
    days=[(first+timedelta(days=i)).isoformat()
          for i in range((last-first).days+1)]

    def summarize(trades):
        per_period={}
        for label,months in PERIODS.items():
            selected_days=[day for day in days if day[:7] in months]
            set_of_days=set(selected_days)
            per_period[label]=_summary(
                [x for x in trades if local_day(x["decision_boundary_ms"]) in set_of_days],
                selected_days
            )
        return {"all":_summary(trades,days),"monthly_groups":per_period}

    old=summarize(baseline["modeled_references"])
    previous=summarize(breakout["modeled_references"])
    new=summarize(reversal["references"])
    econ=new["all"]
    qualifies=bool(
        econ["hypothetical_closed_ideas"]>=100 and
        econ["days_with_closed_ideas"]>=30 and
        econ["mean_costed_R_per_closed_reference"] is not None and
        econ["mean_costed_R_per_closed_reference"]>0 and
        econ["day_cluster_bootstrap_mean_R_95pct"][0]>0 and
        econ["illustrative_closed_trades_only_max_drawdown"]<=0.25 and
        all(
            group["mean_costed_R_per_closed_reference"] is not None and
            group["mean_costed_R_per_closed_reference"]>0
            for group in new["monthly_groups"].values()
        )
    )
    return {
        "schema":1,
        "status":"PAPER_HISTORICAL_ONLY_ECONOMIC_RESEARCH_NOT_AUTHORISATION",
        "policy":POLICY,
        "policy_sha256":POLICY_SHA256,
        "markets":list(MARKETS),
        "months":list(MONTHS),
        "verification_manifest":manifest,
        "prior_pullback":{"selected":baseline["selected_paper_references"],**old},
        "prior_trend_breakout":{"selected":breakout["selected_paper_references"],**previous},
        "new_reversal":{
            "preportfolio_proposals":reversal["candidate_decisions"],
            "selected":reversal["paper_selected"],
            "rejection_reasons":reversal["reasons_by_market"],
            "suppression_reasons":reversal["suppressed_by_portfolio"],
            **new,
        },
        "passes_preregistered_exploratory_economic_thresholds":qualifies,
        "market_data_independently_out_of_sample":False,
        "execution_verified":False,
        "binance_venue_spread_and_funding_verified":False,
        "strategy_profitability_proven":False,
        "client_publication_authorized":False,
        "orders_submitted":0,
        "telegram_messages_sent":0,
    }


def main():
    p=argparse.ArgumentParser(description="V7Sonic no-client reversal hypothesis study")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",help="Create-only absolute JSON report output")
    args=p.parse_args()
    report=run(Path(args.data_root))
    payload=json.dumps(report,sort_keys=True,indent=2)+"\n"
    if args.output:
        dest=Path(args.output)
        if not dest.is_absolute() or dest.is_symlink():
            p.error("Output must be absolute and non-symlink")
        with dest.open("x",encoding="utf-8") as fp:
            fp.write(payload)
    else:
        print(payload,end="")


if __name__=="__main__":
    main()
