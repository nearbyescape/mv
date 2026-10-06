"""Production V3 setup selection and immutable risk-plan construction.

V1 remains in signals.py for exact historical reproducibility.  This module is
the live strategy authority for MV-TREND-DUAL-v3.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN

from .indicators import INTERVAL_MS, PRECISION, confirmation_open_time
from .signals import Snapshot, Quote, PriceFilter, PlanRejected, canonical_hash

LIVE_STRATEGY_ID = "MV-TREND-DUAL-v3"
LIVE_RISK_ID = "RISK-ATR14-SCALED-TP-v3"
STRUCTURE_BARS = 12
EXPIRY_MS = 300_000
QUOTE_AGE_MS = 5_000

PULLBACK_DEPTH_MAX = Decimal("0.75")
PULLBACK_RECLAIM_MIN = Decimal("0.10")
PULLBACK_BODY_MIN = Decimal("0.20")
PULLBACK_CLOSE_LOCATION_MIN = Decimal("0.60")
PULLBACK_SOURCE_EXTENSION_MAX = Decimal("1.00")
PULLBACK_ENTRY_DRIFT_MAX = Decimal("0.50")
PULLBACK_ENTRY_EXTENSION_MAX = Decimal("1.00")

BREAKOUT_DISTANCE_MIN = Decimal("0.05")
BREAKOUT_BODY_MIN = Decimal("0.35")
BREAKOUT_CLOSE_LOCATION_MIN = Decimal("0.70")
BREAKOUT_SOURCE_EXTENSION_MAX = Decimal("1.50")
BREAKOUT_ENTRY_DRIFT_MAX = Decimal("0.75")
BREAKOUT_ENTRY_EXTENSION_MAX = Decimal("1.50")

RECENT_RUN_BARS = 6
RECENT_RUN_MAX = Decimal("2.50")

TP1_R = Decimal("1.0")
TP2_R = Decimal("1.5")
TP3_R = Decimal("2.0")
TP1_ALLOCATION = Decimal("0.30")
TP2_ALLOCATION = Decimal("0.30")
TP3_ALLOCATION = Decimal("0.40")

MAX_SPREAD_BPS = Decimal("10")


@dataclass(frozen=True)
class LiveSetup:
    outcome: str
    reason: str
    direction: str | None
    setup_type: str | None
    regime: str | None
    checks: list[dict]
    structure_level: Decimal | None = None
    recent_run_anchor: Decimal | None = None


def live_decision_id(symbol: str, open_time: int) -> str:
    return canonical_hash([LIVE_STRATEGY_ID, "binance-usdm", symbol, "1h", open_time])


def _check(name: str, passed: bool, value: Decimal | str | None = None, minimum: Decimal | None = None, maximum: Decimal | None = None):
    row = {"id": name, "passed": bool(passed)}
    if value is not None:
        row["value"] = str(value)
    if minimum is not None:
        row["minimum"] = str(minimum)
    if maximum is not None:
        row["maximum"] = str(maximum)
    return row


def _directional(direction: str) -> Decimal:
    return Decimal(1) if direction == "long" else Decimal(-1)


def _validate_context(current: Snapshot, previous: Snapshot | None, confirmation: Snapshot | None, structure: list[Snapshot] | None):
    current.validate()
    if current.timeframe != "1h" or current.count < 500:
        return "WARMUP_1H"
    if previous is None:
        return "MISSING_PREVIOUS_1H"
    previous.validate()
    if previous.timeframe != "1h" or previous.bar.open_time + INTERVAL_MS["1h"] != current.bar.open_time or previous.history_origin != current.history_origin:
        return "NONCONTIGUOUS_PREVIOUS_1H"
    if confirmation is None:
        return "WAITING_EXPECTED_4H"
    confirmation.validate()
    expected = confirmation_open_time(current.bar.close_time + 1)
    if confirmation.timeframe != "4h" or confirmation.bar.open_time != expected:
        return "WAITING_EXPECTED_4H"
    if confirmation.count < 500:
        return "WARMUP_4H"
    if not structure or len(structure) != STRUCTURE_BARS:
        return "MISSING_STRUCTURE_HISTORY"
    expected_times = [current.bar.open_time - n * INTERVAL_MS["1h"] for n in range(STRUCTURE_BARS, 0, -1)]
    for snap, expected_time in zip(structure, expected_times):
        if snap is None:
            return "MISSING_STRUCTURE_HISTORY"
        snap.validate()
        if snap.timeframe != "1h" or snap.bar.open_time != expected_time or snap.history_origin != current.history_origin:
            return "NONCONTIGUOUS_STRUCTURE_HISTORY"
    if structure[-1].bar.open_time != previous.bar.open_time or structure[-1].lineage != previous.lineage:
        return "STRUCTURE_PREVIOUS_MISMATCH"
    return None


def _regime(current: Snapshot, previous: Snapshot, confirmation: Snapshot, direction: str):
    sign = _directional(direction)
    one_fast = sign * (current.ema20 - current.ema50) > 0
    one_full = one_fast and sign * (current.ema50 - current.sma200) > 0
    one_slope = sign * (current.ema50 - previous.ema50) > 0
    one_price_sma = sign * (current.bar.close - current.sma200) > 0
    one_emerging = one_fast and one_slope and one_price_sma

    four_fast = sign * (confirmation.ema20 - confirmation.ema50) > 0
    four_close = sign * (confirmation.bar.close - confirmation.ema20) > 0
    four_full = four_fast and sign * (confirmation.ema50 - confirmation.sma200) > 0 and four_close
    four_emerging = four_fast and four_close

    one_ready = one_full or one_emerging
    four_ready = four_full or four_emerging
    regime = "established" if one_full and four_full else "emerging" if one_ready and four_ready else None

    # Persist only conditions that are actually required by the selected regime.
    # This keeps published rule evidence unambiguous: an optional emerging-regime
    # slope test cannot appear as a failed requirement on an established setup.
    if regime == "established":
        checks = [
            _check(f"{direction}.ema20_ema50_1h", one_fast),
            _check(f"{direction}.established_1h", one_full),
            _check(f"{direction}.ema20_ema50_4h", four_fast),
            _check(f"{direction}.ema20_side_4h", four_close),
            _check(f"{direction}.established_4h", four_full),
        ]
    elif regime == "emerging":
        checks = [
            _check(f"{direction}.ema20_ema50_1h", one_fast),
            _check(f"{direction}.ema50_slope_1h", one_slope),
            _check(f"{direction}.price_sma200_1h", one_price_sma),
            _check(f"{direction}.ema20_ema50_4h", four_fast),
            _check(f"{direction}.ema20_side_4h", four_close),
        ]
    else:
        checks = [
            _check(f"{direction}.ema20_ema50_1h", one_fast),
            _check(f"{direction}.established_1h", one_full),
            _check(f"{direction}.ema50_slope_1h", one_slope),
            _check(f"{direction}.price_sma200_1h", one_price_sma),
            _check(f"{direction}.ema20_ema50_4h", four_fast),
            _check(f"{direction}.ema20_side_4h", four_close),
            _check(f"{direction}.established_4h", four_full),
        ]
    return one_ready, four_ready, regime, checks


def _candle_quality(current: Snapshot, direction: str):
    sign = _directional(direction)
    span = current.bar.high - current.bar.low
    if span <= 0 or current.atr <= 0:
        return Decimal(0), Decimal(0), False
    body_atr = abs(current.bar.close - current.bar.open) / current.atr
    close_location = (
        (current.bar.close - current.bar.low) / span
        if direction == "long"
        else (current.bar.high - current.bar.close) / span
    )
    directional_body = sign * (current.bar.close - current.bar.open) > 0
    return body_atr, close_location, directional_body


def evaluate_setup_v3(current: Snapshot, previous: Snapshot | None, confirmation: Snapshot | None, structure: list[Snapshot] | None):
    """Select one deterministic production setup from completed candles only."""
    blocked = _validate_context(current, previous, confirmation, structure)
    if blocked:
        return LiveSetup("BLOCKED_DATA", blocked, None, None, None, [])

    assert previous is not None and confirmation is not None and structure is not None
    if current.atr <= 0 or previous.atr <= 0:
        return LiveSetup("BLOCKED_DATA", "NONPOSITIVE_ATR", None, None, None, [])

    long_one, long_four, long_regime, long_checks = _regime(current, previous, confirmation, "long")
    short_one, short_four, short_regime, short_checks = _regime(current, previous, confirmation, "short")

    if long_one:
        direction, four_ready, regime, checks = "long", long_four, long_regime, long_checks
    elif short_one:
        direction, four_ready, regime, checks = "short", short_four, short_regime, short_checks
    else:
        return LiveSetup(
            "NO_SETUP",
            "TREND_REGIME_NOT_READY",
            None,
            None,
            None,
            [*long_checks, *short_checks],
        )

    if not four_ready or regime is None:
        return LiveSetup("NO_SETUP", "4H_TREND_NOT_ALIGNED", direction, None, None, checks)

    sign = _directional(direction)
    body_atr, close_location, directional_body = _candle_quality(current, direction)
    source_extension = sign * (current.bar.close - current.ema20) / current.atr
    recent = structure[-RECENT_RUN_BARS:]
    recent_run_anchor = (
        min(s.bar.low for s in recent)
        if direction == "long"
        else max(s.bar.high for s in recent)
    )
    recent_run_atr = sign * (current.bar.close - recent_run_anchor) / current.atr
    recent_run_check = _check(
        f"{direction}.recent_run_atr",
        recent_run_atr <= RECENT_RUN_MAX,
        recent_run_atr,
        maximum=RECENT_RUN_MAX,
    )
    checks = [*checks, recent_run_check]

    previous_on_pullback_side = sign * (previous.ema20 - previous.bar.close) >= 0
    pullback_depth = abs(previous.bar.close - previous.ema20) / previous.atr
    reclaim_strength = sign * (current.bar.close - current.ema20) / current.atr
    pullback_checks = [
        _check(f"{direction}.pullback_side", previous_on_pullback_side),
        _check(f"{direction}.pullback_depth_atr", previous_on_pullback_side and pullback_depth <= PULLBACK_DEPTH_MAX, pullback_depth, maximum=PULLBACK_DEPTH_MAX),
        _check(f"{direction}.reclaim_strength_atr", reclaim_strength >= PULLBACK_RECLAIM_MIN, reclaim_strength, minimum=PULLBACK_RECLAIM_MIN),
        _check(f"{direction}.directional_body", directional_body),
        _check(f"{direction}.body_atr", body_atr >= PULLBACK_BODY_MIN, body_atr, minimum=PULLBACK_BODY_MIN),
        _check(f"{direction}.close_location", close_location >= PULLBACK_CLOSE_LOCATION_MIN, close_location, minimum=PULLBACK_CLOSE_LOCATION_MIN),
        _check(f"{direction}.source_extension_atr", 0 < source_extension <= PULLBACK_SOURCE_EXTENSION_MAX, source_extension, maximum=PULLBACK_SOURCE_EXTENSION_MAX),
    ]
    pullback_ok = all(item["passed"] for item in pullback_checks)

    structure_level = (
        max(s.bar.high for s in structure)
        if direction == "long"
        else min(s.bar.low for s in structure)
    )
    breakout_distance = sign * (current.bar.close - structure_level) / current.atr
    breakout_checks = [
        _check(f"{direction}.structure_break", breakout_distance >= BREAKOUT_DISTANCE_MIN, breakout_distance, minimum=BREAKOUT_DISTANCE_MIN),
        _check(f"{direction}.directional_body", directional_body),
        _check(f"{direction}.body_atr", body_atr >= BREAKOUT_BODY_MIN, body_atr, minimum=BREAKOUT_BODY_MIN),
        _check(f"{direction}.close_location", close_location >= BREAKOUT_CLOSE_LOCATION_MIN, close_location, minimum=BREAKOUT_CLOSE_LOCATION_MIN),
        _check(f"{direction}.source_extension_atr", 0 < source_extension <= BREAKOUT_SOURCE_EXTENSION_MAX, source_extension, maximum=BREAKOUT_SOURCE_EXTENSION_MAX),
    ]
    breakout_ok = all(item["passed"] for item in breakout_checks)

    # Structural breakout gets precedence when the same candle also completes a pullback.
    if breakout_ok:
        return LiveSetup(
            direction.upper() + "_SETUP",
            "RULES_PASSED",
            direction,
            "momentum_breakout",
            regime,
            [*checks, *breakout_checks],
            structure_level,
            recent_run_anchor,
        )
    if pullback_ok:
        return LiveSetup(
            direction.upper() + "_SETUP",
            "RULES_PASSED",
            direction,
            "pullback_continuation",
            regime,
            [*checks, *pullback_checks],
            None,
            recent_run_anchor,
        )
    return LiveSetup(
        "NO_SETUP",
        "NO_PULLBACK_OR_BREAKOUT_TRIGGER",
        direction,
        None,
        regime,
        [*checks, *pullback_checks, *breakout_checks],
        structure_level,
        recent_run_anchor,
    )


def build_plan_v3(
    symbol: str,
    setup: LiveSetup,
    source: Snapshot,
    quote: Quote,
    price_filter: PriceFilter,
    now: int,
):
    """Build a frozen V3 plan.  No position sizing or exchange order is produced."""
    source.validate()
    if setup.outcome not in ("LONG_SETUP", "SHORT_SETUP") or setup.direction not in ("long", "short"):
        raise PlanRejected("INVALID_SETUP")
    if setup.setup_type not in ("pullback_continuation", "momentum_breakout"):
        raise PlanRejected("INVALID_SETUP_TYPE")
    if setup.regime not in ("established", "emerging"):
        raise PlanRejected("INVALID_TREND_REGIME")

    direction = setup.direction
    boundary = source.bar.close_time + 1
    if now < boundary:
        raise PlanRejected("SOURCE_NOT_CLOSED")
    if now >= boundary + EXPIRY_MS:
        raise PlanRejected("EXPIRED_ENTRY_WINDOW")
    if quote.symbol != symbol:
        raise PlanRejected("QUOTE_SYMBOL_MISMATCH")

    values = (quote.bid, quote.ask, quote.bid_qty, quote.ask_qty)
    if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in values) or quote.bid > quote.ask:
        raise PlanRejected("INVALID_QUOTE", True)
    if (
        any(type(v) is not int for v in (quote.time, quote.received_at, now))
        or not boundary <= quote.time <= quote.received_at <= now
        or now - quote.time > QUOTE_AGE_MS
        or now - quote.received_at > QUOTE_AGE_MS
    ):
        raise PlanRejected("STALE_OR_FUTURE_QUOTE", True)

    with localcontext() as ctx:
        ctx.prec, ctx.rounding = PRECISION, ROUND_HALF_EVEN
        price_filter.validate()
        if not price_filter.allows(quote.bid) or not price_filter.allows(quote.ask):
            raise PlanRejected("QUOTE_OFF_TICK_OR_BOUNDS")

        midpoint = (quote.bid + quote.ask) / Decimal(2)
        spread = quote.ask - quote.bid
        spread_bps = spread / midpoint * Decimal(10_000)
        if spread_bps > MAX_SPREAD_BPS:
            raise PlanRejected("SPREAD_TOO_WIDE")

        entry = quote.ask if direction == "long" else quote.bid
        atr = source.atr
        if atr <= 0:
            raise PlanRejected("NONPOSITIVE_ATR")

        drift = abs(entry - source.bar.close)
        drift_limit = PULLBACK_ENTRY_DRIFT_MAX if setup.setup_type == "pullback_continuation" else BREAKOUT_ENTRY_DRIFT_MAX
        if drift > drift_limit * atr:
            raise PlanRejected("MISSED_ENTRY_PRICE_DRIFT")

        sign = Decimal(1) if direction == "long" else Decimal(-1)
        entry_extension = sign * (entry - source.ema20) / atr
        extension_limit = PULLBACK_ENTRY_EXTENSION_MAX if setup.setup_type == "pullback_continuation" else BREAKOUT_ENTRY_EXTENSION_MAX
        if entry_extension <= 0:
            raise PlanRejected("ENTRY_LOST_EMA20_SIDE")
        if entry_extension > extension_limit:
            raise PlanRejected("ENTRY_OVEREXTENDED")
        if setup.recent_run_anchor is None:
            raise PlanRejected("MISSING_RECENT_RUN_ANCHOR")
        recent_run_entry_atr = sign * (entry - setup.recent_run_anchor) / atr
        if recent_run_entry_atr > RECENT_RUN_MAX:
            raise PlanRejected("RECENT_RUN_OVEREXTENDED")

        upwards = direction == "short"
        raw_stop = entry + (Decimal(2) * atr if upwards else -Decimal(2) * atr)
        units = ((raw_stop - price_filter.minimum) / price_filter.tick).to_integral_value(
            rounding=ROUND_CEILING if upwards else ROUND_FLOOR
        )
        stop = price_filter.minimum + units * price_filter.tick
        risk = abs(entry - stop)

        def target_at(multiple):
            raw = entry + (-multiple * risk if upwards else multiple * risk)
            units = ((raw - price_filter.minimum) / price_filter.tick).to_integral_value(
                rounding=ROUND_CEILING if upwards else ROUND_FLOOR
            )
            return price_filter.minimum + units * price_filter.tick

        tp1 = target_at(TP1_R)
        tp2 = target_at(TP2_R)
        tp3 = target_at(TP3_R)
        geometry = (
            stop < entry < tp1 < tp2 < tp3
            if direction == "long"
            else tp3 < tp2 < tp1 < entry < stop
        )
        if risk <= 0 or not geometry or not all(
            price_filter.allows(p) for p in (entry, stop, tp1, tp2, tp3)
        ):
            raise PlanRejected("INVALID_RISK_GEOMETRY_OR_BOUNDS")

        tp1_r = abs(tp1 - entry) / risk
        tp2_r = abs(tp2 - entry) / risk
        tp3_r = abs(tp3 - entry) / risk
        reward = abs(tp3 - entry)
        return {
            "strategy": LIVE_STRATEGY_ID,
            "risk_policy": LIVE_RISK_ID,
            "symbol": symbol,
            "direction": direction,
            "setup_type": setup.setup_type,
            "trend_regime": setup.regime,
            "structure_level": str(setup.structure_level) if setup.structure_level is not None else None,
            **{
                k: str(v)
                for k, v in {
                    "entry": entry,
                    "stop": stop,
                    "frozen_atr": atr,
                    "risk_distance": risk,
                    "reward_distance": reward,
                    "reward_risk": tp3_r,
                    "tp1": tp1,
                    "tp2": tp2,
                    "tp3": tp3,
                    "target": tp3,
                    "tp1_r": tp1_r,
                    "tp2_r": tp2_r,
                    "tp3_r": tp3_r,
                    "entry_drift": drift,
                    "entry_drift_limit_atr": drift_limit,
                    "entry_extension_atr": entry_extension,
                    "recent_run_entry_atr": recent_run_entry_atr,
                    "recent_run_anchor": setup.recent_run_anchor,
                    "spread": spread,
                    "spread_bps": spread_bps,
                    "tick_size": price_filter.tick,
                }.items()
            },
            "source_open_time": source.bar.open_time,
            "source_close_boundary": boundary,
            "published_at": now,
            "expires_at": boundary + EXPIRY_MS,
            "quote_time": quote.time,
            "quote_received_at": quote.received_at,
            "entry_side": "ask" if direction == "long" else "bid",
            "exit_management": {
                "tp1_allocation": str(TP1_ALLOCATION),
                "tp2_allocation": str(TP2_ALLOCATION),
                "tp3_allocation": str(TP3_ALLOCATION),
                "after_tp1": "move_remaining_stop_to_entry",
                "after_tp2": "move_remaining_stop_to_tp1",
                "maximum_realized_r": str(
                    TP1_ALLOCATION * tp1_r
                    + TP2_ALLOCATION * tp2_r
                    + TP3_ALLOCATION * tp3_r
                ),
                "reference_only": True,
            },
            "execution": "signal-reference-only",
        }
