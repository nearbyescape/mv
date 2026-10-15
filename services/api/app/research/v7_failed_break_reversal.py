"""Predeclared V7Sonic failed-breakout reversal hypothesis — RESEARCH ONLY.

Motivation: the completed 2026 six-month trend-following and breakout
candidates both showed negative modeled cost-adjusted expectancy.
This hypothesis trades confirmed *failure* of a preceding 16-bar range
break, and only in non-strong four-hour trend conditions.

NO live strategy import, order placement, Telegram API, event publisher,
private broker keys or production database. Next bar open is a historical
hypothetical fill, not an executable price guarantee.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json

from .v7_recovery_archives import MARKETS, STEP_MS
from .v7_recovery_engine import (
    _atr, _ema, _entry_eligible, _validate_bars,
    MAX_OVERLAPPING_PAPER_IDEAS,
)
from .v7_final_breakout import _four_hour, _score_reference, COST_RATE_PER_SIDE

POLICY = "V7_RESEARCH_FAILED_BREAKOUT_RANGE_REVERSAL_V1"
PARAMETERS = {
    "range_15m_bars": 16,
    "trend_regime_four_hour_ema_fast": 8,
    "trend_regime_four_hour_ema_slow": 21,
    "max_four_hour_ema_spread_in_atr": 0.80,
    "min_range_breach_atr15": 0.08,
    "minimum_rejection_wick_atr15": 0.35,
    "maximum_close_distance_inside_range_atr15": 0.90,
    "minimum_relative_volume": 0.90,
    "entry_gap_limit_atr15": 0.35,
    "minimum_stop_width_atr15": 1.10,
    "maximum_stop_width_atr15": 3.0,
    "stop_wick_margin_atr15": 0.15,
    "gross_target_r": 1.60,
    "minimum_modeled_net_r_at_target": 0.90,
    "max_holding_15m_candles": 24,
    "session": "09:00-23:00 Asia/Kolkata",
    "fee_and_slippage_bps_per_side": 8,
    "max_concurrent": 4,
    "symbol_cooldown_minutes": 180,
    "ambiguity_policy": "STOP_FIRST",
}
POLICY_SHA256 = sha256(json.dumps(
    PARAMETERS, sort_keys=True, separators=(",", ":")
).encode()).hexdigest()
START = 560


def proposals_for_symbol(rows, symbol: str):
    if symbol not in MARKETS:
        raise ValueError("Only the six predeclared exchange markets are supported")
    bars = _validate_bars(rows)
    if len(bars) <= START+1 or len(bars)%16:
        raise ValueError("Complete calendar and at least 560 warmup 15m bars required")
    h4 = _four_hour(bars)
    ema_fast = _ema([b.close for b in h4], 8)
    ema_slow = _ema([b.close for b in h4], 21)
    atr_four = _atr(h4, 14)
    atr_15m = _atr(bars, 14)
    proposals = []
    reasons = Counter()

    for i in range(START, len(bars)-1):
        b = bars[i]
        decision_boundary = b.open_ms + STEP_MS
        if not _entry_eligible(decision_boundary):
            reasons["OUTSIDE_SESSION"] += 1
            continue
        four_ix = (i+1)//16-1
        if four_ix < 0:
            reasons["NO_CLOSED_4H"] += 1
            continue
        assert h4[four_ix].open_ms + 16*STEP_MS <= decision_boundary
        f, s, high_vol = (
            ema_fast[four_ix],ema_slow[four_ix],atr_four[four_ix]
        )
        atr = atr_15m[i]
        if any(value is None or value <= 0 for value in (f,s,high_vol,atr)):
            reasons["INDICATOR_WARMUP"] += 1
            continue
        if abs(f-s)/high_vol > PARAMETERS["max_four_hour_ema_spread_in_atr"]:
            reasons["STRONG_TREND_NO_FADE"] += 1
            continue
        preceding = bars[i-16:i]
        range_high=max(x.high for x in preceding)
        range_low=min(x.low for x in preceding)
        up_breach=b.high >= range_high+PARAMETERS["min_range_breach_atr15"]*atr
        down_breach=b.low <= range_low-PARAMETERS["min_range_breach_atr15"]*atr
        if up_breach and down_breach:
            reasons["AMBIGUOUS_DOUBLE_SWEEP"] += 1
            continue

        direction=0
        # Rejection must be explicit in a fully COMPLETED candle.
        if (up_breach and b.close < range_high
                and b.close > range_high-PARAMETERS["maximum_close_distance_inside_range_atr15"]*atr
                and b.close < b.open
                and b.high-max(b.open,b.close) >= PARAMETERS["minimum_rejection_wick_atr15"]*atr):
            direction=-1
        elif (down_breach and b.close > range_low
              and b.close < range_low+PARAMETERS["maximum_close_distance_inside_range_atr15"]*atr
              and b.close > b.open
              and min(b.open,b.close)-b.low >= PARAMETERS["minimum_rejection_wick_atr15"]*atr):
            direction=1
        if direction == 0:
            reasons["NO_CONFIRMED_FALSE_BREAK"] += 1
            continue

        avg_volume=sum(x.volume for x in bars[i-20:i])/20
        if avg_volume<=0 or b.volume < PARAMETERS["minimum_relative_volume"]*avg_volume:
            reasons["INSUFFICIENT_REJECTION_VOLUME"] += 1
            continue

        # Future next-open is used ONLY for historical execution simulation;
        # eligibility at decision_boundary never includes next-bar data.
        next_open=bars[i+1].open
        if abs(next_open-b.close)>PARAMETERS["entry_gap_limit_atr15"]*atr:
            reasons["NEXT_OPEN_OUTSIDE_EXECUTION_WINDOW"] += 1
            continue
        if (direction==-1 and next_open>=range_high
                or direction==1 and next_open<=range_low):
            reasons["RANGE_FAILURE_DID_NOT_PERSIST_TO_OPEN"] += 1
            continue
        if direction==1:
            stop=min(
                b.low-PARAMETERS["stop_wick_margin_atr15"]*atr,
                next_open-PARAMETERS["minimum_stop_width_atr15"]*atr,
            )
        else:
            stop=max(
                b.high+PARAMETERS["stop_wick_margin_atr15"]*atr,
                next_open+PARAMETERS["minimum_stop_width_atr15"]*atr,
            )
        risk=abs(next_open-stop)
        if stop<=0 or risk <= 0 or risk>PARAMETERS["maximum_stop_width_atr15"]*atr:
            reasons["STOP_GEOMETRY_OR_RISK_REJECTED"] += 1
            continue
        target=next_open+direction*PARAMETERS["gross_target_r"]*risk
        if target<=0:
            reasons["NON_POSITIVE_TARGET"] += 1
            continue
        costs=(next_open+target)*COST_RATE_PER_SIDE
        cost_adjusted=(
            PARAMETERS["gross_target_r"]*risk-costs
        )/(risk+next_open*COST_RATE_PER_SIDE)
        if cost_adjusted < PARAMETERS["minimum_modeled_net_r_at_target"]:
            reasons["AFTER_COST_REWARD_TOO_LOW"] += 1
            continue

        proposals.append({
            "symbol":symbol,
            "entry_bar_index":i+1,
            "decision_boundary_ms":decision_boundary,
            "direction":direction,
            "entry":next_open,
            "stop":stop,
            "target":target,
            "risk_price":risk,
            "modeled_target_net_R":cost_adjusted,
            "policy":POLICY,
            "policy_sha256":POLICY_SHA256,
            "decision_uses_completed_bars_only":True,
            "next_open_execution_verified":False,
            "client_publication_authorized":False,
            "exchange_fills_verified":False,
        })
        reasons["QUALIFIED_RESEARCH_REFERENCE"] += 1

    assert sum(reasons.values())==len(bars)-START-1
    return proposals, reasons


def reversal_portfolio(series_by_market: dict) -> dict:
    if set(series_by_market)!=set(MARKETS):
        raise ValueError("All six markets and no others are required")
    validated = {
        symbol:_validate_bars(series_by_market[symbol]) for symbol in MARKETS
    }
    if len({v[0].open_ms for v in validated.values()}) !=1 or (
        len({v[-1].open_ms for v in validated.values()}) !=1
    ):
        raise ValueError("Market data source calendars differ")
    proposals=[]
    counts={}
    for symbol in MARKETS:
        selected, reject=proposals_for_symbol(
            series_by_market[symbol],symbol
        )
        proposals.extend(selected)
        counts[symbol]=dict(sorted(reject.items()))
    proposals.sort(key=lambda x:(x["decision_boundary_ms"],x["symbol"]))
    selected=[]
    active=[]
    last_entry={}
    suppressed=Counter()
    for proposed in proposals:
        ts=proposed["decision_boundary_ms"]
        symbol=proposed["symbol"]
        active=[t for t in active if t["exit_boundary_ms"]>ts]
        if any(x["symbol"]==symbol for x in active):
            suppressed["SAME_SYMBOL_ACTIVE"]+=1
            continue
        if len(active)>=MAX_OVERLAPPING_PAPER_IDEAS:
            suppressed["MAX_ACTIVE_FOUR"]+=1
            continue
        if ts-last_entry.get(symbol,-10**18) < 180*60_000:
            suppressed["THREE_HOUR_COOLDOWN"]+=1
            continue
        outcome=_score_reference(proposed,validated[symbol])
        if outcome["exit_boundary_ms"]<=ts:
            raise AssertionError("Exit must postdate decision")
        selected.append(outcome)
        active.append(outcome)
        last_entry[symbol]=ts
    return {
        "policy":POLICY,"policy_sha256":POLICY_SHA256,
        "candidate_decisions":len(proposals),
        "paper_selected":len(selected),
        "reasons_by_market":counts,
        "suppressed_by_portfolio":dict(sorted(suppressed.items())),
        "references":selected,
        "client_publication_authorized":False,
        "telegram_messages_sent":0,
        "orders_submitted":0,
    }
