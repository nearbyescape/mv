"""V7Sonic paper-only research challenger: a longer-horizon, regime-aware hypothesis.

This is a SEPARATE policy, not an update to the frozen V7 research model.
No network, filesystem, database, Telegram, broker API or production entrypoint.
It makes *unvalidated* conditional reference plans. Neither a qualifying
paper candidate nor passing these tests implies positive expected P&L.
"""
from __future__ import annotations

from decimal import Decimal as D
from hashlib import sha256
import json

from .t7sonic_experts import discover_hypotheses
from .t7sonic_perception import perceive_symbol, decimal_number
from .t7sonic_release_candidate import (
    _quote, _round, TAKER_BPS_PER_SIDE, SLIPPAGE_BPS_PER_SIDE,
)
from .t7sonic_validation_plan import MARKETS

POLICY = "V7SONIC_REGIME_15M_RESEARCH_CHALLENGER_V1"
NOT_FOR_CLIENTS = "RESEARCH_PAPER_NONPUBLISHABLE"
MIN_NET_R = D("1.25")
MIN_STOP_ATR15 = D("1.15")
MAX_STOP_ATR15 = D("2.50")
MAX_ENTRY_DRIFT_ATR15 = D("0.75")
TP1_R = D("1.25")
TP2_R = D("2.75")
PRIORITY = (
    "failed_breakout_reversal",
    "trend_pullback_reentry",
    "trend_continuation",
    "breakout",
    "range_reversion",
    "participation",
    "volatility_transition",
)


def _number(frame: dict, key: str) -> D:
    return decimal_number(frame[key], key)


def _fmt(value: D) -> str:
    return format(value.normalize(), "f")


def _no(symbol: str, boundary: int, reason: str, source: str) -> dict:
    return {
        "policy": POLICY,
        "status": "NO_RESEARCH_CANDIDATE",
        "symbol": symbol,
        "decision_boundary_ms": boundary,
        "source_sha256": source,
        "reason": reason,
        "publishable_signal": False,
        "executable_order": False,
        "client_publication_authorized": False,
    }


def research_hypotheses(perception: dict) -> list[dict]:
    """Uncalibrated as-of hypotheses; no trained probability or trade claim."""
    f = perception["frames"]
    m5, m15, h1, h4 = (f[x] for x in ("5m", "15m", "1h", "4h"))
    h1_t = _number(h1, "fast_ema8_minus_slow_ema21_atr")
    m15_t = _number(m15, "fast_ema8_minus_slow_ema21_atr")
    h4_t = _number(h4, "fast_ema8_minus_slow_ema21_atr")
    body5 = _number(m5, "last_body_atr")
    delta5 = _number(m5, "last_close_change_atr")
    extension5 = _number(m5, "price_minus_ema21_atr")
    volume5 = m5["volume_vs_previous20"]
    volume5 = D("0") if volume5 is None else decimal_number(volume5, "volume5")
    result = [
        {"expert": item["expert"], "direction": item["direction"]}
        for item in discover_hypotheses(perception)
    ]

    # New candidate family: a 15m / 1h directional re-entry with a completed
    # 5m confirming candle; 4h strong opposition is a veto, not a mandatory
    # full-strength alignment. Both sides use exactly symmetric rules.
    for sign, direction in ((D(1), "LONG"), (D(-1), "SHORT")):
        if (
            sign * h1_t >= D("0.12")
            and sign * m15_t >= D("0.07")
            and sign * h4_t >= D("-0.20")
            and sign * body5 >= D("0.08")
            and sign * delta5 >= D("0.06")
            and D("-0.60") <= sign * extension5 <= D("1.25")
            and volume5 >= D("0.80")
        ):
            result.append({
                "expert": "trend_pullback_reentry", "direction": direction,
            })

    # A 15m breakout is only eligible exactly when its 15m bar completed;
    # do not infer an intrabar breakout from the next two 5m decisions.
    if m15["last_completed_boundary_ms"] == perception["as_of_ms"]:
        vol15 = m15["volume_vs_previous20"]
        vol15 = D("0") if vol15 is None else decimal_number(vol15, "volume15")
        if vol15 >= D("1.10"):
            if m15["close_above_previous20_high"]:
                result.append({
                    "expert": "breakout", "direction": "LONG",
                })
            if m15["close_below_previous20_low"]:
                result.append({
                    "expert": "breakout", "direction": "SHORT",
                })

    return sorted(result, key=lambda x: (
        PRIORITY.index(x["expert"]), x["direction"],
    ))


def propose_paper_challenger(
    snapshot: dict, quote: dict, *, active_symbols: tuple[str, ...] = (),
) -> dict:
    """Compute one deterministic nonpublishable reference; fail closed."""
    perception = perceive_symbol(snapshot)
    symbol, boundary = perception["symbol"], perception["as_of_ms"]
    if symbol not in MARKETS or type(boundary) is not int or boundary % 300_000:
        raise ValueError("Frozen six markets and completed 5m boundary required")
    if (not isinstance(active_symbols, tuple)
            or len(set(active_symbols)) != len(active_symbols)
            or any(x not in MARKETS for x in active_symbols)):
        raise ValueError("Explicit valid active-symbol snapshot required")

    # Strict original top-of-book, tick geometry, freshness and spread gate.
    bid, ask, tick, spread = _quote(quote, symbol, boundary)
    no = lambda reason: _no(
        symbol, boundary, reason, perception["feature_source_sha256"]
    )
    if symbol in active_symbols:
        return no("ACTIVE_SYMBOL_LOCK")

    hypotheses = research_hypotheses(perception)
    if not hypotheses:
        return no("NO_RESEARCH_EXPERT")
    if len({item["direction"] for item in hypotheses}) != 1:
        return no("CONFLICTING_RESEARCH_DIRECTIONS")
    chosen = hypotheses[0]
    is_long = chosen["direction"] == "LONG"

    f = perception["frames"]
    atr15 = _number(f["15m"], "atr14")
    last_close = _number(f["5m"], "last_close")
    entry = ask if is_long else bid
    if abs(entry - last_close) > MAX_ENTRY_DRIFT_ATR15 * atr15:
        return no("ENTRY_DRIFT")
    last5 = snapshot["bars"]["5m"][-1]
    extreme = decimal_number(last5["low" if is_long else "high"], "5m extreme")
    structural = (
        min(extreme - D("0.10") * atr15, entry - MIN_STOP_ATR15 * atr15)
        if is_long else
        max(extreme + D("0.10") * atr15, entry + MIN_STOP_ATR15 * atr15)
    )
    stop = _round(structural, tick, up=not is_long)
    if stop <= 0 or (is_long and stop >= entry) or (not is_long and stop <= entry):
        return no("INVALID_STRUCTURAL_STOP")
    risk = abs(entry - stop)
    if risk > MAX_STOP_ATR15 * atr15:
        return no("STRUCTURAL_STOP_TOO_WIDE")

    tp1 = _round(entry + (TP1_R*risk if is_long else -TP1_R*risk),
                 tick, up=is_long)
    tp2 = _round(entry + (TP2_R*risk if is_long else -TP2_R*risk),
                 tick, up=is_long)
    if (is_long and not stop < entry < tp1 < tp2) or (
        not is_long and not D("0") < tp2 < tp1 < entry < stop
    ):
        return no("INVALID_REFERENCE_TARGETS")

    bps = TAKER_BPS_PER_SIDE + SLIPPAGE_BPS_PER_SIDE
    cost_tp1 = (entry + tp1) * bps / D("10000")
    cost_tp2 = (entry + tp2) * bps / D("10000")
    weighted_cost = (cost_tp1 + cost_tp2) / 2
    weighted_gross = (abs(tp1-entry) + abs(tp2-entry)) / 2
    net_r = (weighted_gross-weighted_cost)/(risk+weighted_cost)
    if net_r < MIN_NET_R:
        return {
            **no("AFTER_COST_REWARD_TOO_LOW"),
            "modeled_net_r": _fmt(net_r),
            "modeled_cost_to_price_risk": _fmt(weighted_cost/risk),
        }

    identity = {
        "policy": POLICY, "symbol": symbol, "boundary": boundary,
        "source": perception["feature_source_sha256"],
        "expert": chosen["expert"], "direction": chosen["direction"],
    }
    candidate_id = sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()

    return {
        "policy": POLICY,
        "status": NOT_FOR_CLIENTS,
        "candidate_id": candidate_id,
        "symbol": symbol,
        "direction": chosen["direction"],
        "expert": chosen["expert"],
        "decision_boundary_ms": boundary,
        "expires_at_ms": boundary + 30_000,
        "source_sha256": perception["feature_source_sha256"],
        "entry": _fmt(entry),
        "stop_loss": _fmt(stop),
        "take_profit_1": _fmt(tp1),
        "take_profit_2": _fmt(tp2),
        "weighted_exit_net_r_if_filled": _fmt(net_r),
        "modeled_cost_to_price_risk": _fmt(weighted_cost/risk),
        "spread_bps": _fmt(spread),
        "timeframe_for_stop": "15m_ATR_WITH_5m_STRUCTURE",
        "reference_exit_split": "50/50",
        "assumed_fees_bps_per_side": _fmt(TAKER_BPS_PER_SIDE),
        "assumed_slippage_bps_per_side": _fmt(SLIPPAGE_BPS_PER_SIDE),
        "illustrative_risk_budget_pct": "0.5",
        "position_size_or_subscriber_exposure_verified": False,
        "post_tp1_stop_policy": "MOVE_REMAINING_STOP_TO_ENTRY_REFERENCE_ONLY",
        "accuracy_established": False,
        "venue_execution_or_fills_verified": False,
        "client_publication_authorized": False,
        "publishable_signal": False,
        "executable_order": False,
    }
