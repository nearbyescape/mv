"""V7Sonic FINAL RESEARCH hypothesis: 4h regime / 15m closed-range breakout.

PAPER RESEARCH ONLY. This is deliberately independent from the six original
V7 experts and from the failed hourly EMA pullback system.

- 4h regime is computed from completed 15m candles only.
- Signal is a completed 15m close outside the preceding 4h 15m range.
- Next 15m OPEN is used for retrospective *hypothetical* execution only.
  The future opening price is never included in the decision features.
- No ticker quotes, fills, funding, broker account, production DB,
  Telegram channel or live publication path.
- Frozen once in source; 2026 Apr-Sep is exploratory, NOT a holdout.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math

from .v7_recovery_archives import MARKETS, STEP_MS
from .v7_recovery_engine import (
    PriceBar, _atr, _ema, _entry_eligible, _session_final_bar,
    _validate_bars, simulated_exit, MAX_OVERLAPPING_PAPER_IDEAS,
)

POLICY = "V7_FINAL_FOUR_HOUR_REGIME_FIFTEEN_MINUTE_BREAKOUT_RESEARCH_V1"
FEE_AND_SLIPPAGE_BPS_PER_SIDE = 8.0
COST_RATE_PER_SIDE = FEE_AND_SLIPPAGE_BPS_PER_SIDE / 10_000
RULES = {
    "regime": "4h_EMA8_EMA21_ATR14_ONLY_CLOSED_CANDLES",
    "minimum_4h_ema_gap_atr": 0.12,
    "breakout_lookback_15m_bars": 16,
    "completed_body_min_atr15": 0.15,
    "completed_range_min_atr15": 0.40,
    "completed_range_max_atr15": 2.80,
    "minimum_relative_volume": 1.10,
    "maximum_next_open_gap_atr15": 0.40,
    "min_stop_atr15": 1.25,
    "max_stop_atr15": 3.50,
    "target_gross_R": 2.25,
    "min_cost_adjusted_net_R_at_target": 1.25,
    "max_hold_15m_bars": 24,
    "max_active_reference_ideas": 4,
    "same_symbol_cooldown_minutes": 180,
    "fee_and_slippage_bps_per_side": FEE_AND_SLIPPAGE_BPS_PER_SIDE,
    "session_ist": "09:00–23:00",
    "ambiguous_stop_target": "STOP_FIRST",
}
POLICY_SHA256 = sha256(json.dumps(
    RULES, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
).encode()).hexdigest()
REGIME_BARS_15M = 16
STARTUP_BARS_15M = 16 * 35
MAX_HOLD = 24


def _four_hour(bars: list[PriceBar]) -> list[PriceBar]:
    if not bars or bars[0].open_ms % (REGIME_BARS_15M * STEP_MS) != 0:
        raise ValueError("4h source must begin on an exact UTC 4h boundary")
    if len(bars) % REGIME_BARS_15M:
        raise ValueError("Incomplete final 4h source window")
    out = []
    for i in range(0, len(bars), REGIME_BARS_15M):
        block = bars[i:i+REGIME_BARS_15M]
        out.append(PriceBar(
            open_ms=block[0].open_ms,
            open=block[0].open,
            high=max(b.high for b in block),
            low=min(b.low for b in block),
            close=block[-1].close,
            volume=sum(b.volume for b in block),
        ))
    return out


def _reference_decisions(bars_input, symbol: str) -> tuple[list[dict], Counter]:
    if symbol not in MARKETS:
        raise ValueError("Only six frozen research markets")
    bars = _validate_bars(bars_input)
    if len(bars) < STARTUP_BARS_15M + 2:
        raise ValueError("Insufficient completed research candles")
    if len(bars) % REGIME_BARS_15M:
        raise ValueError("Need complete four-hour study source")
    h4 = _four_hour(bars)
    h4fast = _ema([b.close for b in h4], 8)
    h4slow = _ema([b.close for b in h4], 21)
    h4atr = _atr(h4, 14)
    atr15 = _atr(bars, 14)
    proposals = []
    reasons = Counter()

    for i in range(STARTUP_BARS_15M, len(bars)-1):
        bar = bars[i]
        boundary = bar.open_ms + STEP_MS
        if not _entry_eligible(boundary):
            reasons["OUTSIDE_IST_SESSION"] += 1
            continue

        # (i+1) completed fifteen-minute bars as of boundary; exclude
        # any four-hour bar that ends AFTER that exact boundary.
        h4_ix = (i+1)//REGIME_BARS_15M - 1
        if h4_ix < 0:
            reasons["NO_CLOSED_FOUR_HOUR"] += 1
            continue
        assert h4[h4_ix].open_ms + REGIME_BARS_15M*STEP_MS <= boundary
        fast, slow, volatility = (
            h4fast[h4_ix], h4slow[h4_ix], h4atr[h4_ix]
        )
        av = atr15[i]
        if (fast is None or slow is None or volatility is None or
                av is None or volatility <= 0 or av <= 0):
            reasons["INDICATOR_WARMUP"] += 1
            continue
        trend = (fast - slow) / volatility
        if abs(trend) < RULES["minimum_4h_ema_gap_atr"]:
            reasons["WEAK_FOUR_HOUR_TREND"] += 1
            continue
        direction = 1 if trend > 0 else -1
        previous = bars[i-RULES["breakout_lookback_15m_bars"]:i]
        top = max(x.high for x in previous)
        bottom = min(x.low for x in previous)
        if not ((direction == 1 and bar.close > top) or
                (direction == -1 and bar.close < bottom)):
            reasons["NO_FOUR_HOUR_RANGE_BREAK"] += 1
            continue
        body = direction * (bar.close-bar.open)
        size = bar.high-bar.low
        if (body < RULES["completed_body_min_atr15"]*av or
                size < RULES["completed_range_min_atr15"]*av or
                size > RULES["completed_range_max_atr15"]*av):
            reasons["BREAKOUT_CANDLE_QUALITY"] += 1
            continue
        avg_volume = sum(x.volume for x in bars[i-20:i]) / 20
        if avg_volume <= 0 or bar.volume < RULES["minimum_relative_volume"]*avg_volume:
            reasons["INSUFFICIENT_RELATIVE_VOLUME"] += 1
            continue

        # RETROSPECTIVE next-open check: observable *after* decision.
        # This cannot be treated as a live executable pre-approval.
        opening = bars[i+1].open
        if abs(opening-bar.close) > RULES["maximum_next_open_gap_atr15"]*av:
            reasons["NEXT_OPEN_GAP_OUT_OF_BOUNDS"] += 1
            continue
        if (direction == 1 and opening <= top) or (
            direction == -1 and opening >= bottom
        ):
            reasons["BREAKOUT_FAILED_BEFORE_NEXT_OPEN"] += 1
            continue
        if direction == 1:
            stop = min(bar.low-0.15*av, opening-RULES["min_stop_atr15"]*av)
        else:
            stop = max(bar.high+0.15*av, opening+RULES["min_stop_atr15"]*av)
        risk = abs(opening-stop)
        if (stop <= 0 or risk > RULES["max_stop_atr15"]*av or
                risk <= 0 or (direction == 1 and stop >= opening) or
                (direction == -1 and stop <= opening)):
            reasons["INVALID_STOP_OR_WIDTH"] += 1
            continue
        target = opening + direction * risk * RULES["target_gross_R"]
        if target <= 0:
            reasons["INVALID_TARGET"] += 1
            continue
        cost_at_target = (opening + target)*COST_RATE_PER_SIDE
        model_r = (RULES["target_gross_R"]*risk-cost_at_target)/(
            risk+opening*COST_RATE_PER_SIDE
        )
        if model_r < RULES["min_cost_adjusted_net_R_at_target"]:
            reasons["AFTER_COST_REFERENCE_REJECTED"] += 1
            continue
        proposals.append({
            "symbol": symbol,
            "entry_bar_index": i+1,
            "decision_boundary_ms": boundary,
            "direction": direction,
            "entry": opening,
            "stop": stop,
            "target": target,
            "risk_price": risk,
            "modeled_target_net_R": model_r,
            "policy": POLICY,
            "policy_sha256": POLICY_SHA256,
            "entry_window_claim": "HYPOTHETICAL_NEXT_15M_OPEN_NOT_VERIFIED_FILL",
            "data_at_decision_contains_future_bar": False,
            "client_publication_authorized": False,
            "exchange_fills_verified": False,
        })
        reasons["QUALIFYING_HISTORICAL_REFERENCE"] += 1
    return proposals, reasons


def _score_reference(trade: dict, source: list[PriceBar]) -> dict:
    # Reuse the fail-closed source reference barrier ordering; apply
    # this candidate's six-hour maximum rather than old five-hour horizon.
    # Existing simulator exits at session boundary and assumes worst-side
    # open on stop gaps. Tail-censored trades are excluded from mean R.
    # Copy-free truncation is NOT safe, because a shorter source segment
    # would convert a true time exit into an artificial censored exit.
    # The standalone evaluator below explicitly enforces MAX_HOLD.
    i = trade["entry_bar_index"]
    last = min(i + MAX_HOLD-1, len(source)-1)
    outcome = None
    exit_price = None
    j = None
    for ix in range(i, last+1):
        b = source[ix]
        is_long = trade["direction"] == 1
        hit_stop = b.low <= trade["stop"] if is_long else b.high >= trade["stop"]
        hit_target = b.high >= trade["target"] if is_long else b.low <= trade["target"]
        if hit_stop:
            exit_price = (min(trade["stop"], b.open) if is_long
                          else max(trade["stop"], b.open))
            outcome = "AMBIGUOUS_STOP_FIRST" if hit_target else "STOP"
        elif hit_target:
            exit_price = trade["target"]
            outcome = "TARGET"
        elif _session_final_bar(b):
            exit_price = b.close
            outcome = "SESSION_EXIT"
        elif ix == last:
            exit_price = b.close
            outcome = ("CENSORED" if last == len(source)-1 and
                       last < i + MAX_HOLD-1 else "TIME_EXIT")
        else:
            continue
        j = ix
        break
    if exit_price is None or j is None:
        raise AssertionError("Missing modeled exit")
    denom = trade["risk_price"] + trade["entry"]*COST_RATE_PER_SIDE
    net_r = (
        trade["direction"]*(exit_price-trade["entry"])
        - (trade["entry"]+exit_price)*COST_RATE_PER_SIDE
    ) / denom
    return {
        **trade,
        "exit": exit_price,
        "exit_bar_index": j,
        "exit_boundary_ms": source[j].open_ms + STEP_MS,
        "outcome": outcome,
        "net_R": net_r,
        "actual_fill_verified": False,
        "intrabar_touch_order_verified": False,
        "orders_submitted": 0,
        "telegram_messages_sent": 0,
    }


def breakout_portfolio(series_by_market: dict) -> dict:
    if set(series_by_market) != set(MARKETS):
        raise ValueError("Complete frozen six-market portfolio required")
    bars = {symbol: _validate_bars(series_by_market[symbol]) for symbol in MARKETS}
    if (len({arr[0].open_ms for arr in bars.values()}) != 1 or
            len({arr[-1].open_ms for arr in bars.values()}) != 1):
        raise ValueError("Unequal historical source calendars")
    proposals = []
    reject = {}
    for symbol in MARKETS:
        rows, counts = _reference_decisions(series_by_market[symbol],symbol)
        reject[symbol] = dict(sorted(counts.items()))
        proposals.extend(rows)
    proposals.sort(key=lambda x:(x["decision_boundary_ms"],x["symbol"]))
    open_ideas = []
    selected = []
    last_entry = {}
    skipped = Counter()
    for candidate in proposals:
        ts, symbol = candidate["decision_boundary_ms"], candidate["symbol"]
        open_ideas = [x for x in open_ideas if x["exit_boundary_ms"] > ts]
        if any(x["symbol"] == symbol for x in open_ideas):
            skipped["ACTIVE_SAME_SYMBOL"] += 1
            continue
        if len(open_ideas) >= MAX_OVERLAPPING_PAPER_IDEAS:
            skipped["REFERENCE_PORTFOLIO_FULL"] += 1
            continue
        if symbol in last_entry and ts-last_entry[symbol] < 180*60_000:
            skipped["THREE_HOUR_COOLDOWN"] += 1
            continue
        simulated = _score_reference(candidate,bars[symbol])
        if simulated["exit_boundary_ms"] <= ts:
            raise ValueError("Exit before candidate decision")
        selected.append(simulated)
        open_ideas.append(simulated)
        last_entry[symbol] = ts
    return {
        "policy": POLICY,
        "policy_sha256": POLICY_SHA256,
        "source_15m_bars_per_market": len(next(iter(bars.values()))),
        "proposals_before_portfolio_constraints":len(proposals),
        "selected_paper_references":len(selected),
        "reasons_by_market":reject,
        "portfolio_suppression_reasons":dict(sorted(skipped.items())),
        "modeled_references":selected,
        "reference_max_concurrent_slots":MAX_OVERLAPPING_PAPER_IDEAS,
        "client_publication_authorized":False,
        "exchange_fills_verified":False,
        "orders_submitted":0,
        "telegram_messages_sent":0,
    }
