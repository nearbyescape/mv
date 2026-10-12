"""Portfolio review for one complete six-market OFFLINE V7Sonic paper cycle.

Sequentially reserves illustrative candidate risk in frozen market order
with no account/broker/Telegram access. This is an INTERNAL PAPER REVIEW,
not a live strategy or proof of any profits. All six markets, current
symbol filters and a complete manually provided account snapshot are
required: a missing source fails closed rather than fabricating zero risk.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D

from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_paper_ledger import validate_internal_batch
from services.t7sonic.forward_risk_gate import (
    paper_position_sizing, _fmt, MAX_AGGREGATE_RISK,
    MAX_GROSS_NOTIONAL_MULTIPLE,
)


def review_six_market_paper_risk(batch: dict, *,
                                 rules_by_symbol: dict,
                                 paper_account: dict) -> dict:
    validated=validate_internal_batch(batch)
    if (not isinstance(rules_by_symbol,dict) or
            set(rules_by_symbol)!=set(MARKETS) or
            not isinstance(paper_account,dict)):
        raise ValueError("Six complete venue filters and portfolio snapshot mandatory")
    state=deepcopy(paper_account)
    outcomes=[]
    for record in validated["records"]:
        symbol=record["symbol"]
        if record["status"]=="NO_CANDIDATE":
            outcomes.append({
                "symbol":symbol, "status":"NO_PAPER_POSITION",
                "reason":record["reason"],
                "client_publication_authorized":False,
                "orders_authorized":False,
            })
            continue
        sizing=paper_position_sizing(record,rules_by_symbol[symbol],state)
        outcomes.append(sizing)
        if sizing["status"]=="SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE":
            state["reserved_loss_usdt"]=_fmt(
                D(state["reserved_loss_usdt"])+
                D(sizing["worst_case_stopped_loss_usdt"])
            )
            state["gross_open_notional_usdt"]=_fmt(
                D(state["gross_open_notional_usdt"])+
                D(sizing["notional_usdt"])
            )
            state["already_active_symbols"].append(symbol)
            state["open_positions"]+=1
    if len(outcomes)!=len(MARKETS):
        raise ValueError("Incomplete risk decisions")
    equity=D(paper_account["equity_usdt"])
    if (D(state["reserved_loss_usdt"]) > equity*MAX_AGGREGATE_RISK or
            D(state["gross_open_notional_usdt"]) >
            equity*MAX_GROSS_NOTIONAL_MULTIPLE):
        raise ValueError("Portfolio paper risk limit violated")
    return {
        "status":"COMPLETE_SIX_MARKET_PAPER_RISK_REVIEW_NOT_ACTIONABLE",
        "source_batch_sha256":validated["digest"],
        "decision_boundary_ms":validated["boundary"],
        "markets_evaluated":len(MARKETS),
        "candidate_count":validated["candidate_count"],
        "paper_sized_count":sum(
            x["status"]=="SIZED_INTERNAL_PAPER_ONLY_NEVER_EXECUTE"
            for x in outcomes
        ),
        "reviews":outcomes,
        "paper_reserved_risk_after_usdt":state["reserved_loss_usdt"],
        "paper_total_gross_notional_after_usdt":
            state["gross_open_notional_usdt"],
        "paper_open_slots_after":state["open_positions"],
        "actual_account_or_positions_authenticated":False,
        "funding_liquidation_and_margin_certified":False,
        "telegram_messages_sent":0,
        "client_publication_authorized":False,
        "real_money_order_submission_authorized":False,
    }
