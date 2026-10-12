"""V7Sonic deterministic *paper-only* release-candidate decision and risk logic.

Six existing expert rules remain frozen. An injected completed-five-frame
snapshot + fresh quote can yield ENTRY, SL, TP1, TP2 for evaluation only.
No API, network, database, Telegram, executable order, auto publication,
win-probability claim or source authentication occurs in this module.
"""
from __future__ import annotations

from decimal import Decimal as D, ROUND_CEILING, ROUND_FLOOR
from hashlib import sha256
import json

from .t7sonic_perception import decimal_number, perceive_symbol
from .t7sonic_experts import discover_hypotheses
from .t7sonic_validation_plan import MARKETS

POLICY = "V7SONIC_PAPER_CANDIDATE_V1"
QUOTE_MAX_AGE_MS = 5_000
MAX_DECISION_LAG_MS = 30_000
MAX_ENTRY_DRIFT_ATR = D("0.5")
MAX_SPREAD_BPS = D("15")
MIN_STOP_ATR = D("0.9")
MAX_STOP_ATR = D("3")
MIN_NET_RR = D("1.5")
TAKER_BPS_PER_SIDE = D("5")
SLIPPAGE_BPS_PER_SIDE = D("5")
PRIORITY = (
    "failed_breakout_reversal", "trend_continuation", "breakout",
    "range_reversion", "participation", "volatility_transition",
)


def _decimal(obj: dict, key: str) -> D:
    if key not in obj or not isinstance(obj[key], str):
        raise ValueError("Missing decimal quote or bar field: " + key)
    val = decimal_number(obj[key], key)
    if val <= 0:
        raise ValueError("Nonpositive " + key)
    return val


def _fmt(d: D) -> str:
    return format(d.normalize(), "f")


def _round(d: D, tick: D, up: bool) -> D:
    return (d/tick).to_integral_value(
        rounding=ROUND_CEILING if up else ROUND_FLOOR
    )*tick


def _quote(q: dict, symbol: str, as_of_ms: int) -> tuple[D, D, D, D]:
    keys = {
        "symbol", "decision_boundary_ms", "observed_at_ms",
        "evaluated_at_ms", "bid", "ask", "tick_size",
    }
    if not isinstance(q, dict) or set(q) != keys:
        raise ValueError("Exact bid/ask quote schema required")
    if q["symbol"] != symbol or q["decision_boundary_ms"] != as_of_ms:
        raise ValueError("Wrong symbol/decision cutoff")
    observed, evaluated = q["observed_at_ms"], q["evaluated_at_ms"]
    if (type(observed) is not int or type(evaluated) is not int or
            not as_of_ms <= observed <= evaluated <=
            as_of_ms + MAX_DECISION_LAG_MS or
            evaluated-observed > QUOTE_MAX_AGE_MS):
        raise ValueError("Stale, premature or late quote")
    bid, ask, tick = (_decimal(q, key) for key in ("bid", "ask", "tick_size"))
    if bid >= ask or tick >= bid or bid % tick or ask % tick:
        raise ValueError("Invalid or non-tick-aligned quote")
    spread = (ask-bid) * D("10000") / ((ask+bid)/2)
    if spread > MAX_SPREAD_BPS:
        raise ValueError("Spread too wide")
    return bid, ask, tick, spread


def indicative_plan(snapshot: dict, quote: dict, *,
                    active_symbols: tuple[str, ...] = ()) -> dict:
    """Compute one deterministic conditional paper plan, never authorize a trade."""
    perception = perceive_symbol(snapshot)
    symbol, boundary = perception["symbol"], perception["as_of_ms"]
    if symbol not in MARKETS or type(boundary) is not int or boundary % 300_000:
        raise ValueError("Frozen six USD-M symbols and five-minute decisions only")
    if (not isinstance(active_symbols, tuple) or
            any(s not in MARKETS for s in active_symbols) or
            len(set(active_symbols)) != len(active_symbols)):
        raise ValueError("Bad active-position snapshot")
    bid, ask, tick, spread = _quote(quote, symbol, boundary)
    common = {
        "schema": 1, "policy": POLICY,
        "status": "NO_CANDIDATE", "symbol": symbol,
        "decision_boundary_ms": boundary,
        "source_sha256": perception["feature_source_sha256"],
        "source_origin_independently_verified": False,
        "quote_timestamp_independently_verified": False,
        "publishable_signal": False, "executable_order": False,
    }
    if symbol in active_symbols:
        return {**common, "reason": "ACTIVE_POSITION_LOCK"}
    hypotheses = discover_hypotheses(perception)
    if not hypotheses:
        return {**common, "reason": "NO_QUALIFYING_EXPERT"}
    if len({h["direction"] for h in hypotheses}) != 1:
        return {**common, "reason": "CONFLICTING_EXPERTS"}
    chosen = min(hypotheses, key=lambda h: (
        PRIORITY.index(h["expert"]), h["direction"]
    ))
    direction = chosen["direction"]
    if direction not in ("LONG", "SHORT"):
        raise ValueError("Unrecognized expert direction")
    long = direction == "LONG"
    last_frame = perception["frames"]["5m"]
    atr, last_close = (_decimal(last_frame, k) for k in ("atr14", "last_close"))
    entry = ask if long else bid
    if abs(entry-last_close) > MAX_ENTRY_DRIFT_ATR*atr:
        return {**common, "reason": "ENTRY_DRIFT_TOO_LARGE"}
    last_bar = snapshot["bars"]["5m"][-1]
    extreme = _decimal(last_bar, "low" if long else "high")
    stop_unrounded = (
        min(extreme-D("0.10")*atr, entry-MIN_STOP_ATR*atr)
        if long else
        max(extreme+D("0.10")*atr, entry+MIN_STOP_ATR*atr)
    )
    stop = _round(stop_unrounded, tick, up=not long)
    if stop <= 0 or (long and stop >= entry) or (not long and stop <= entry):
        return {**common, "reason": "INVALID_STOP"}
    risk = abs(entry-stop)
    if risk > MAX_STOP_ATR*atr:
        return {**common, "reason": "STOP_TOO_WIDE"}
    tp1 = _round(entry+(risk if long else -risk), tick, up=long)
    tp2 = _round(entry+(D("2.5")*risk if long else -D("2.5")*risk), tick, up=long)
    if (long and not (entry < tp1 < tp2)) or (
        not long and not (D("0") < tp2 < tp1 < entry)
    ):
        return {**common, "reason": "INVALID_TARGET"}
    assumed_cost = (entry+tp2) * (
        TAKER_BPS_PER_SIDE+SLIPPAGE_BPS_PER_SIDE
    ) / D("10000")
    net_r = (abs(tp2-entry)-assumed_cost)/(risk+assumed_cost)
    if net_r < MIN_NET_RR:
        return {**common, "reason": "INSUFFICIENT_AFTER_COST_REWARD"}
    plan = {
        **common,
        "status": "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION",
        "direction": direction, "expert": chosen["expert"],
        "thesis": chosen["thesis"],
        "heuristic_strength_not_probability":
            chosen["heuristic_evidence_strength_NOT_PROBABILITY"],
        "entry_type": "BID_ASK_INDICATIVE_NOT_FILLED",
        "entry": _fmt(entry), "stop_loss": _fmt(stop),
        "take_profit_1": _fmt(tp1), "take_profit_2": _fmt(tp2),
        "estimated_gross_rr_tp2": _fmt(abs(tp2-entry)/risk),
        "estimated_net_rr_tp2": _fmt(net_r),
        "estimated_round_trip_cost_per_unit": _fmt(assumed_cost),
        "assumed_fee_bps_per_side": _fmt(TAKER_BPS_PER_SIDE),
        "assumed_slippage_bps_per_side": _fmt(SLIPPAGE_BPS_PER_SIDE),
        "observed_spread_bps": _fmt(spread),
        "max_equity_risk_percent": "0.5",
        "exit_policy": "TP1 50%, TP2 50%; then stop to entry for remainder",
        "stop_invalidation": "Do not widen stop; source data revision invalidates",
        "expires_at_ms": boundary+MAX_DECISION_LAG_MS,
        "win_probability": None, "actual_fill_verified": False,
        "lot_size_and_notional_verified": False,
    }
    identity = {
        "policy": POLICY, "symbol": symbol,
        "boundary": boundary, "source": perception["feature_source_sha256"],
        "expert": chosen["expert"], "direction": direction,
    }
    plan["candidate_id"] = sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    plan["candidate_sha256"] = sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    return plan
