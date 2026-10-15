"""Offline, read-only V7 research funnel: no threshold tuning or publication.

Counts ordered gating failures and separately measures the OI distribution.
The 'ignore OI' diagnostic is NOT a candidate policy or profitability claim.
"""
from collections import Counter
from datetime import datetime
from decimal import Decimal as D

from .core import IST, SYMBOLS, HORIZONS_MS, PARAMETERS, classify_research_horizon
from .journal import checked, verify_chain


def _percentiles(values):
    if not values:
        return {"n": 0, "min": None, "p10": None, "p25": None,
                "median": None, "p75": None, "p90": None, "max": None}
    v = sorted(values)
    def value(p):
        index = D(len(v)-1) * D(str(p))
        lo = int(index)
        fraction = index - lo
        return str(v[lo] * (1-fraction) + v[min(lo+1,len(v)-1)]*fraction)
    return {
        "n":len(v),"min":str(v[0]),"p10":value("0.10"),
        "p25":value("0.25"),"median":value("0.50"),
        "p75":value("0.75"),"p90":value("0.90"),"max":str(v[-1]),
    }


def _gates(previous, current, funding_horizon_ms):
    """Ordered gates mirroring the FROZEN classifier without changing it."""
    params=PARAMETERS
    at=current["observed_at_ms"]
    duration=at-previous["observed_at_ms"]
    spread=D(current["spread_bps"])
    funding=D(current["funding_rate"])
    oi=(D(current["open_interest"])-D(previous["open_interest"])) / D(previous["open_interest"])*100
    imbalance=D(current["book_imbalance"])
    taker=D(current["taker_ratio"])
    long=taker>=D(params["minimum_taker_buy_sell_ratio_for_long"]) and imbalance>=D(params["minimum_book_imbalance_abs"])
    short=taker<=D(params["maximum_taker_buy_sell_ratio_for_short"]) and imbalance<=-D(params["minimum_book_imbalance_abs"])
    direction=1 if long else -1
    entry=D(current["ask"] if long else current["bid"])
    impact=D(current["buy_impact_bps"] if long else current["sell_impact_bps"])
    risk=entry*D(params["stop_distance_pct"])/100
    stop=entry-direction*risk
    target=entry+direction*risk*D(params["gross_target_R"])
    per_side=D(params["per_side_fee_slippage_bps"])/10000
    modeled_profit=(target-entry)*direction-(entry+target)*per_side-entry*spread/10000
    modeled_r=modeled_profit/(risk+entry*per_side)
    stages=[
        ("SYMBOL_MISMATCH",previous["symbol"]==current["symbol"] and current["symbol"] in SYMBOLS),
        ("NONCONTIGUOUS_OBSERVATIONS",params["minimum_interval_ms"]<=duration<=params["maximum_interval_ms"]),
        ("STALE_TAKER_PERIOD",current["taker_period_start_ms"]>previous["taker_period_start_ms"]),
        ("STALE_DEPTH",current["depth_last_update_id"]>previous["depth_last_update_id"]),
        ("OUTSIDE_SIGNAL_SESSION",9<=datetime.fromtimestamp(at/1000,IST).hour<23),
        ("SPREAD_TOO_WIDE",spread<=D(params["maximum_spread_bps"])),
        ("EXTREME_FUNDING",abs(funding)<=D(params["maximum_abs_funding_rate"])),
        ("FUNDING_WINDOW_UNMODELED",
            type(current.get("next_funding_ms")) is int and current["next_funding_ms"]>at+funding_horizon_ms),
        ("OPEN_INTEREST_NOT_CONFIRMED",D(params["minimum_open_interest_increase_pct"])<=oi<=D(params["maximum_open_interest_jump_pct"])),
        ("TAKER_AND_BOOK_DISAGREE",long or short),
        ("INSUFFICIENT_VISIBLE_LIQUIDITY",impact<=D(params["maximum_book_impact_bps"])),
        ("INVALID_PRICE_GEOMETRY",stop>0 and target>0),
        ("AFTER_COST_TARGET_TOO_WEAK",modeled_r>=D(params["minimum_cost_adjusted_target_R"])),
    ]
    return stages,oi,long,short


def funnel_report(db, *, last_samples_per_symbol=288):
    if type(last_samples_per_symbol) is not int or not 2<=last_samples_per_symbol<=2880:
        raise ValueError("Invalid audit window")
    summaries={
        h:{"total":0,"passed_stages":Counter(),"first_rejection":Counter(),
           "oi_pre_gate_values":[],"oi_pass":0,"buy_flow_book_agreement":0,
           "sell_flow_book_agreement":0,
           "would_pass_with_oi_ignored":0,
           "by_symbol_oi_values":{s:[] for s in SYMBOLS}}
        for h in HORIZONS_MS
    }
    for symbol in SYMBOLS:
        verify_chain(db,symbol)
        rows=db.execute("SELECT * FROM observations WHERE symbol=? ORDER BY observed_at_ms DESC LIMIT ?",
                        (symbol,last_samples_per_symbol)).fetchall()
        snapshots=[checked(r) for r in reversed(rows)]
        for previous,current in zip(snapshots,snapshots[1:]):
            for h,stat in summaries.items():
                stat["total"]+=1
                stages,oi,long,short=_gates(previous,current,h)
                expected=classify_research_horizon(previous,current,h)
                first=next((reason for reason,ok in stages if not ok),None)
                expected_first=expected.get("reason")
                if first!=expected_first or (first is None)!=(expected["status"]=="PAPER_CANDIDATE"):
                    raise ValueError("Audit diverged from frozen classifier; abort")
                if first is not None:
                    stat["first_rejection"][first]+=1
                passed=True
                for name,ok in stages:
                    passed=passed and ok
                    if passed:
                        stat["passed_stages"][name]+=1
                # The distribution reflects ONLY pairs passing every
                # prerequisite BEFORE the OI gate, not later filter outcomes.
                oi_index=next(i for i,(name,_) in enumerate(stages) if name=="OPEN_INTEREST_NOT_CONFIRMED")
                if all(ok for _,ok in stages[:oi_index]):
                    stat["oi_pre_gate_values"].append(oi)
                    stat["by_symbol_oi_values"][symbol].append(oi)
                    if stages[oi_index][1]:
                        stat["oi_pass"]+=1
                    if long:
                        stat["buy_flow_book_agreement"]+=1
                    if short:
                        stat["sell_flow_book_agreement"]+=1
                    if all(ok for index,(_,ok) in enumerate(stages) if index!=oi_index):
                        stat["would_pass_with_oi_ignored"]+=1
    results={}
    for h,s in summaries.items():
        results[str(h//60_000)+"m"]={
            "adjacent_pairs":s["total"],
            "first_rejection_counts":dict(sorted(s["first_rejection"].items())),
            "cumulative_passed_stages":dict(s["passed_stages"]),
            "pre_oi_gate_pairs":len(s["oi_pre_gate_values"]),
            "oi_change_pct_distribution_after_prerequisites":_percentiles(s["oi_pre_gate_values"]),
            "oi_ge_original_threshold_pairs":s["oi_pass"],
            "directional_flow_book_agreement_long_pairs":s["buy_flow_book_agreement"],
            "directional_flow_book_agreement_short_pairs":s["sell_flow_book_agreement"],
            "shadow_all_other_gates_pass_if_oi_ignored":s["would_pass_with_oi_ignored"],
            "oi_change_pct_by_market":{
                market:_percentiles(values) for market,values in s["by_symbol_oi_values"].items()
            },
        }
    return {
        "kind":"V7_RESEARCH_FROZEN_FILTER_FUNNEL",
        "research_only":True,
        "journal_read_only":True,
        "source_hash_chains_verified":True,
        "no_threshold_changes":True,
        "original_strategy_unchanged":True,
        "shadow_oi_bypass_not_a_recommended_strategy":True,
        "profitability_or_trade_fills_proven":False,
        "multiple_comparison_risk":True,
        "comparisons":results,
    }
