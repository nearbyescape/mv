"""Research-only prospective-reference outcomes for OI-rejected setups.

Select setups using observations already recorded at decision time. Read
later quote snapshots only to measure future point-in-time reference marks.
No journal writes; no fills, stop/target execution or live signals inferred.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D

from .core import HORIZONS_MS, PARAMETERS, SYMBOLS, classify_research_horizon, horizon_mark
from .filter_funnel import _gates
from .journal import checked, verify_chain


def _summarize(values):
    if not values:
        return {
            "count": 0, "mean": None, "median": None,
            "positive_fraction": None, "minimum": None, "maximum": None,
        }
    ordered = sorted(values)
    n = len(ordered)
    mid = (ordered[(n-1)//2] + ordered[n//2])/2
    return {
        "count": n,
        "mean": str(sum(ordered, D(0))/n),
        "median": str(mid),
        "positive_fraction": str(D(sum(v>0 for v in ordered))/n),
        "minimum": str(ordered[0]),
        "maximum": str(ordered[-1]),
    }


def _shadow_idea(current, *, long):
    direction = 1 if long else -1
    side = "LONG" if long else "SHORT"
    entry = D(current["ask"] if long else current["bid"])
    risk = entry * D(PARAMETERS["stop_distance_pct"]) / 100
    stop = entry - direction*risk
    target = entry + direction*risk*D(PARAMETERS["gross_target_R"])
    return {
        "direction": side,
        "entry_reference": str(entry),
        "risk_distance": str(risk),
        "stop": str(stop),
        "target": str(target),
    }


def oi_shadow_outcome_report(db, *, last_samples_per_symbol=288):
    if type(last_samples_per_symbol) is not int or not 2<=last_samples_per_symbol<=2880:
        raise ValueError("Invalid shadow analysis window")
    ledger = {
        h: {
            "considered_pairs": 0, "oi_rejected_shadow_setups": 0,
            "original_classifier_passing_pairs": 0,
            "side_counts": Counter(), "by_symbol": Counter(),
            "no_due_quote_yet_or_gap": 0, "next_funding_reached_before_quote": 0,
            "marked": [], "time_lags_ms": [],
        }
        for h in HORIZONS_MS
    }
    for symbol in SYMBOLS:
        verify_chain(db, symbol)
        rows=db.execute(
            "SELECT * FROM observations WHERE symbol=? ORDER BY observed_at_ms DESC LIMIT ?",
            (symbol,last_samples_per_symbol),
        ).fetchall()
        observations=[checked(row) for row in reversed(rows)]
        for i in range(1,len(observations)):
            previous,current=observations[i-1],observations[i]
            if previous["symbol"]!=symbol or current["symbol"]!=symbol:
                raise ValueError("Journal market identity mismatch")
            for h,stats in ledger.items():
                stats["considered_pairs"]+=1
                stages,oi,long,short=_gates(previous,current,h)
                observed_decision=classify_research_horizon(previous,current,h)
                first_fail=next((name for name,passes in stages if not passes),None)
                if first_fail!=observed_decision.get("reason"):
                    raise ValueError("Shadow analysis disagrees with frozen classifier")
                if observed_decision["status"]=="PAPER_CANDIDATE":
                    stats["original_classifier_passing_pairs"]+=1
                index=next(
                    idx for idx,(name,_) in enumerate(stages)
                    if name=="OPEN_INTEREST_NOT_CONFIRMED"
                )
                # A shadow case must ONLY be rejected by OI. Never relax
                # funding, clock, depth, taker, liquidity or cost controls.
                if stages[index][1] or any(
                    not passes for j,(_,passes) in enumerate(stages) if j!=index
                ):
                    continue
                if not (long or short):
                    raise ValueError("Inconsistent selected direction")
                stats["oi_rejected_shadow_setups"]+=1
                stats["side_counts"]["LONG" if long else "SHORT"]+=1
                stats["by_symbol"][symbol]+=1

                due=current["observed_at_ms"]+h
                future=next((
                    row for row in observations[i+1:]
                    if due<=row["observed_at_ms"]<=due+600_000
                ),None)
                if future is None:
                    stats["no_due_quote_yet_or_gap"]+=1
                    continue
                # A late mark can cross the originally known upcoming
                # funding event even if the requested horizon did not.
                if future["observed_at_ms"] >= current["next_funding_ms"]:
                    stats["next_funding_reached_before_quote"]+=1
                    continue
                snapshot_mark=horizon_mark(_shadow_idea(current,long=long),future)
                if not snapshot_mark["not_a_verified_stop_target_fill"]:
                    raise ValueError("Outcome basis changed unexpectedly")
                stats["marked"].append(D(snapshot_mark["net_reference_R"]))
                stats["time_lags_ms"].append(
                    future["observed_at_ms"]-due
                )
    results={}
    for h,b in ledger.items():
        if b["oi_rejected_shadow_setups"] != (
            len(b["marked"])+b["no_due_quote_yet_or_gap"]
            +b["next_funding_reached_before_quote"]
        ):
            raise ValueError("Non-exhaustive shadow outcome bookkeeping")
        results[str(h//60_000)+"m"]={
            "horizon_minutes":h//60_000,
            "evaluated_pairs":b["considered_pairs"],
            "original_classifier_passing_pairs":b["original_classifier_passing_pairs"],
            "shadow_setups_rejected_only_by_open_interest":b["oi_rejected_shadow_setups"],
            "shadow_long_short":dict(sorted(b["side_counts"].items())),
            "shadow_by_market":dict(sorted(b["by_symbol"].items())),
            "missing_due_quote_or_insufficient_future_data":b["no_due_quote_yet_or_gap"],
            "withheld_mark_because_funding_crossed":b["next_funding_reached_before_quote"],
            "post_cost_book_touch_mark_R":_summarize(b["marked"]),
            "maximum_book_mark_delay_ms":max(b["time_lags_ms"],default=None),
        }
    return {
        "kind":"V7_OI_SHADOW_BOOK_TOUCH_OUTCOME_EXPLORATION",
        "read_only_verified_journal":True,
        "frozen_classifier_policy_unchanged":True,
        "only_OI_requirement_ignored_in_shadow_selection":True,
        "selection_uses_no_future_data":True,
        "outcome_is_single_future_book_touch_not_stop_target_fill":True,
        "not_real_trading_returns":True,
        "not_independent_out_of_sample":True,
        "profitability_or_signal_accuracy_proven":False,
        "subscribers_not_authorized":True,
        "comparisons":results,
    }
