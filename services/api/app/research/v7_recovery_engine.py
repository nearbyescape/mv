"""V7 recovery: FROZEN independent 1h-trend / 15m-entry costed PAPER strategy.

Not the failed six-expert V7 planner. No market network, Telegram, broker,
database, provider account, or executable release. Never pass a model output
to the V7 production signed-outbox. Source bars are completed 15m candles.
A hypothetical next-bar open is NOT a proven executable 30-second fill.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
import math

from .v7_recovery_archives import STEP_MS

POLICY = "V7_RECOVERY_HOURLY_TREND_15M_REENTRY_PAPER_V1"
FEE_BPS_PER_SIDE = 4.0
SLIPPAGE_BPS_PER_SIDE = 4.0
COST_RATE_PER_SIDE = (FEE_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE) / 10_000
MIN_MODELED_NET_R = 1.25
TARGET_GROSS_R = 2.25
MAX_HOLD_BARS = 20
MAX_OVERLAPPING_PAPER_IDEAS = 4
MAX_REFERENCE_RISK_PER_IDEA_PCT = 0.5
MIN_WARMUP_15M = 220
FIXED_RULES = {
    "hourly_ema_fast": 20, "hourly_ema_slow": 50,
    "entry_ema_fast": 20, "entry_ema_slow": 50,
    "hourly_trend_min_atr": 0.15,
    "pullback_completed_bars": 4,
    "pullback_near_ema_atr": 0.60,
    "max_extension_atr15": 1.20,
    "minimum_volume_ratio": 0.70,
    "min_stop_atr15": 1.25,
    "min_stop_atr1h": 0.75,
    "max_stop_atr1h": 3.0,
    "max_entry_gap_atr15": 0.35,
    "target_gross_R": TARGET_GROSS_R,
    "min_net_R_at_target": MIN_MODELED_NET_R,
    "max_hold_15m_bars": MAX_HOLD_BARS,
    "fee_bps_each_side": FEE_BPS_PER_SIDE,
    "slippage_bps_each_side": SLIPPAGE_BPS_PER_SIDE,
    "max_concurrent": MAX_OVERLAPPING_PAPER_IDEAS,
}
POLICY_SHA256 = sha256(json.dumps(FIXED_RULES, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
_IST_OFFSET_MIN = 330


@dataclass(frozen=True)
class PriceBar:
    open_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


def _validate_bars(bars) -> list[PriceBar]:
    if len(bars) < 1:
        raise ValueError("Empty source series")
    output = []
    previous = None
    for item in bars:
        row = PriceBar(
            int(item.open_ms), float(item.opening), float(item.high),
            float(item.low), float(item.close), float(item.volume),
        )
        if (any(not math.isfinite(v) for v in (
            row.open, row.high, row.low, row.close, row.volume
        )) or row.low <= 0 or row.volume < 0 or
            not row.low <= min(row.open, row.close) <= max(row.open, row.close) <= row.high or
            row.open_ms % STEP_MS or
            (previous is not None and row.open_ms != previous + STEP_MS)):
            raise ValueError("Invalid, unaligned or non-contiguous source bars")
        previous = row.open_ms
        output.append(row)
    return output


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    level = sum(values[:period]) / period
    result[period-1] = level
    alpha = 2.0 / (period + 1)
    for i in range(period, len(values)):
        level += (values[i] - level) * alpha
        result[i] = level
    return result


def _atr(bars: list[PriceBar], length: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(bars)
    if len(bars) < length:
        return result
    trs = [
        max(
            row.high-row.low,
            abs(row.high-bars[i-1].close) if i else row.high-row.low,
            abs(row.low-bars[i-1].close) if i else row.high-row.low,
        )
        for i,row in enumerate(bars)
    ]
    value = sum(trs[:length]) / length
    result[length-1] = value
    for i in range(length, len(bars)):
        value = (value * (length-1) + trs[i]) / length
        result[i] = value
    return result


def _hourly(bars: list[PriceBar]) -> list[PriceBar]:
    out = []
    if bars[0].open_ms % 3_600_000:
        raise ValueError("15m series must start at a completed UTC hour")
    if len(bars) % 4:
        raise ValueError("15m study must end at an hourly boundary")
    for i in range(0, len(bars), 4):
        b = bars[i:i+4]
        out.append(PriceBar(
            b[0].open_ms, b[0].open, max(x.high for x in b),
            min(x.low for x in b), b[-1].close,
            sum(x.volume for x in b),
        ))
    return out


def _session_minute(timestamp_ms: int) -> int:
    return (timestamp_ms // 60_000 + _IST_OFFSET_MIN) % 1440


def _entry_eligible(timestamp_ms: int) -> bool:
    minute = _session_minute(timestamp_ms)
    return 9*60 <= minute <= 22*60+30


def _session_final_bar(bar: PriceBar) -> bool:
    return _session_minute(bar.open_ms + STEP_MS) == 23*60


def generate_decisions(bars_input, *, symbol: str) -> tuple[list[dict], Counter]:
    """Generate next-bar-entry references using only bars closed at decision."""
    bars = _validate_bars(bars_input)
    if len(bars) < MIN_WARMUP_15M+1:
        raise ValueError("Insufficient research history")
    hourly = _hourly(bars)
    close15 = [b.close for b in bars]
    ema15fast = _ema(close15, 20)
    ema15slow = _ema(close15, 50)
    atr15 = _atr(bars)
    ema1fast = _ema([b.close for b in hourly], 20)
    ema1slow = _ema([b.close for b in hourly], 50)
    atr1 = _atr(hourly)
    proposals = []
    reasons: Counter = Counter()

    for i in range(MIN_WARMUP_15M, len(bars)-1):
        bar, following = bars[i], bars[i+1]
        boundary = bar.open_ms + STEP_MS
        if not _entry_eligible(boundary):
            reasons["OUTSIDE_ENTRY_SESSION"] += 1
            continue
        hi = ((i+1)//4) - 1
        if hi < 0:
            reasons["NO_COMPLETED_HOURLY_FRAME"] += 1
            continue
        hf, hs, ha = ema1fast[hi], ema1slow[hi], atr1[hi]
        ef, es, av = ema15fast[i], ema15slow[i], atr15[i]
        if any(v is None or v <= 0 for v in (hf, hs, ha, ef, es, av)):
            reasons["INDICATOR_WARMUP"] += 1
            continue
        # Every hourly input is from bars with end_ms <= boundary.
        assert hourly[hi].open_ms + 3_600_000 <= boundary
        # Price and trend alignment, not six legacy experts.
        strength = (hf-hs)/ha
        direction = (
            1 if strength >= FIXED_RULES["hourly_trend_min_atr"] and ef > es
            else -1 if strength <= -FIXED_RULES["hourly_trend_min_atr"] and ef < es
            else 0
        )
        if direction == 0:
            reasons["NO_ALIGNED_HOURLY_TREND"] += 1
            continue
        ext = direction * (bar.close-ef)/av
        if not 0 <= ext <= FIXED_RULES["max_extension_atr15"]:
            reasons["NO_CONTROLLED_REENTRY"] += 1
            continue
        if direction * (bar.close-bars[i-1].close) <= 0 or (
            direction * (bar.close-bar.open) <= 0
        ):
            reasons["NO_COMPLETED_DIRECTIONAL_CONFIRMATION"] += 1
            continue
        history = bars[i-4:i]
        near = (
            min(x.low for x in history) <= ef + FIXED_RULES["pullback_near_ema_atr"]*av
            if direction == 1 else
            max(x.high for x in history) >= ef - FIXED_RULES["pullback_near_ema_atr"]*av
        )
        if not near:
            reasons["NO_RECENT_PULLBACK"] += 1
            continue
        reference_volume = sum(x.volume for x in bars[i-20:i]) / 20
        if reference_volume <= 0 or bar.volume < FIXED_RULES["minimum_volume_ratio"]*reference_volume:
            reasons["LOW_COMPLETED_CANDLE_PARTICIPATION"] += 1
            continue

        entry = following.open
        if abs(entry-bar.close) > FIXED_RULES["max_entry_gap_atr15"]*av:
            reasons["UNMODELED_ENTRY_GAP"] += 1
            continue
        min_risk = max(
            FIXED_RULES["min_stop_atr15"]*av,
            FIXED_RULES["min_stop_atr1h"]*ha,
        )
        if direction == 1:
            stop = min(
                min(x.low for x in bars[i-5:i+1]) - .15*av,
                entry-min_risk,
            )
        else:
            stop = max(
                max(x.high for x in bars[i-5:i+1]) + .15*av,
                entry+min_risk,
            )
        risk = abs(entry-stop)
        if (stop <= 0 or risk <= 0 or risk > FIXED_RULES["max_stop_atr1h"]*ha or
                (direction == 1 and stop >= entry) or
                (direction == -1 and stop <= entry)):
            reasons["STOP_GEOMETRY_OR_WIDTH"] += 1
            continue
        target = entry + direction * risk * TARGET_GROSS_R
        if target <= 0:
            reasons["NEGATIVE_TARGET"] += 1
            continue
        assumed_exit_cost = (entry+target) * COST_RATE_PER_SIDE
        model_r = (
            TARGET_GROSS_R*risk-assumed_exit_cost
        ) / (risk+entry*COST_RATE_PER_SIDE)
        if model_r < MIN_MODELED_NET_R:
            reasons["INSUFFICIENT_AFTER_COST_REFERENCE"] += 1
            continue

        proposals.append({
            "symbol": symbol, "entry_bar_index": i+1,
            "decision_boundary_ms": boundary, "direction": direction,
            "entry": entry, "stop": stop, "target": target,
            "risk_price": risk, "modeled_target_net_R": model_r,
            "policy": POLICY, "policy_sha256": POLICY_SHA256,
            "client_publication_authorized": False,
            "exchange_fills_verified": False,
        })
        reasons["QUALIFYING_PAPER_REFERENCE"] += 1
    return proposals, reasons


def simulated_exit(trade: dict, bars_input) -> dict:
    """Stop first on ambiguous OHLC, gap-through-stop adverse, no best-price fill."""
    bars = bars_input
    i = trade["entry_bar_index"]
    entry, direction = trade["entry"], trade["direction"]
    stop, target = trade["stop"], trade["target"]
    if i >= len(bars):
        raise ValueError("Entry outside historical series")
    end = min(i+MAX_HOLD_BARS-1, len(bars)-1)
    outcome = "CENSORED"
    exited = None
    index = None
    for j in range(i, end+1):
        bar = bars[j]
        if direction == 1:
            stop_hit, target_hit = bar.low <= stop, bar.high >= target
        else:
            stop_hit, target_hit = bar.high >= stop, bar.low <= target
        if stop_hit:
            # If the candle opens across stop, assume worse opening price.
            exited = min(stop, bar.open) if direction == 1 else max(stop, bar.open)
            outcome = "AMBIGUOUS_STOP_FIRST" if target_hit else "STOP"
        elif target_hit:
            exited = target  # No hypothetical favorable price improvement.
            outcome = "TARGET"
        elif j == end or _session_final_bar(bar):
            # Entire remaining 15m candle must be completed to infer this close.
            exited = bar.close
            outcome = "TIME_EXIT" if j == end else "SESSION_EXIT"
        else:
            continue
        index = j
        break
    if exited is None or index is None:
        raise AssertionError("Missing modeled exit")
    gross = direction * (exited-entry)
    costs = (entry+exited)*COST_RATE_PER_SIDE
    initial_loss_budget = trade["risk_price"] + entry*COST_RATE_PER_SIDE
    result = dict(trade)
    result.update({
        "exit": exited,
        "exit_bar_index": index,
        "exit_boundary_ms": bars[index].open_ms+STEP_MS,
        "outcome": outcome,
        "gross_price_pnl_per_unit": gross,
        "modeled_fee_slippage_price_per_unit": costs,
        "net_R": (gross-costs)/initial_loss_budget,
        "actual_fill_verified": False,
        "intrabar_touch_order_verified": False,
        "next_open_execution_verified": False,
        "orders_submitted": 0,
        "telegram_messages_sent": 0,
    })
    return result


def portfolio_simulation(series_by_market: dict) -> dict:
    """Time-ordered paper-only reference portfolio, maximum four active ideas."""
    if len(series_by_market) != 6:
        raise ValueError("All six frozen V7 markets required for comparability")
    from .v7_recovery_archives import MARKETS
    if set(series_by_market) != set(MARKETS):
        raise ValueError("Wrong market membership")
    validated = {s: _validate_bars(v) for s,v in series_by_market.items()}
    starts = {x[0].open_ms for x in validated.values()}
    ends = {x[-1].open_ms for x in validated.values()}
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("Mixed calendar coverage would create portfolio lookahead")
    decisions = []
    reasons = {}
    for symbol in MARKETS:
        made, counted = generate_decisions(series_by_market[symbol], symbol=symbol)
        decisions.extend(made)
        reasons[symbol] = dict(sorted(counted.items()))
    decisions.sort(key=lambda x: (x["decision_boundary_ms"], x["symbol"]))
    active = []
    last_entry = {}
    selected = []
    suppressed = Counter()
    for candidate in decisions:
        ts, sym = candidate["decision_boundary_ms"], candidate["symbol"]
        active = [t for t in active if t["exit_boundary_ms"] > ts]
        if any(t["symbol"] == sym for t in active):
            suppressed["SAME_SYMBOL_OPEN_REFERENCE"] += 1
            continue
        if len(active) >= MAX_OVERLAPPING_PAPER_IDEAS:
            suppressed["FOUR_SLOT_REFERENCE_CAP"] += 1
            continue
        # Prevent correlated 5m/15m chatter: 3h cooldown from entry.
        if sym in last_entry and ts - last_entry[sym] < 3*3_600_000:
            suppressed["THREE_HOUR_SYMBOL_COOLDOWN"] += 1
            continue
        modeled = simulated_exit(candidate, validated[sym])
        if modeled["exit_boundary_ms"] <= ts:
            raise ValueError("Historical exit precedes entry")
        selected.append(modeled)
        active.append(modeled)
        last_entry[sym] = ts
    assert all(x["client_publication_authorized"] is False for x in selected)
    return {
        "policy": POLICY, "policy_sha256": POLICY_SHA256,
        "source_15m_bars_per_market": len(next(iter(validated.values()))),
        "proposals_before_portfolio_constraints": len(decisions),
        "selected_paper_references": len(selected),
        "reasons_by_market": reasons,
        "portfolio_suppression_reasons": dict(sorted(suppressed.items())),
        "modeled_references": selected,
        "reference_max_concurrent_slots": MAX_OVERLAPPING_PAPER_IDEAS,
        "illustrative_max_risk_per_trade_pct": MAX_REFERENCE_RISK_PER_IDEA_PCT,
        "client_publication_authorized": False,
        "execution_verified": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
        "not_independent_forward_validation": True,
    }
