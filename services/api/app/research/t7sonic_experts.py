"""T7Sonic research-only market-state and multi-expert hypothesis discovery.

All outputs are unpriced, uncalibrated *watch hypotheses*, NOT signals.
No future candles, order book guesses, probability percentages, orders, DB
writes, existing MV V4 calls or production integration.
"""
from __future__ import annotations

from decimal import Decimal as D
from .t7sonic_perception import REQUIRED_FRAMES, breadth_context, decimal_number

RESEARCH_ONLY_STATUS = "WATCH_RESEARCH_HYPOTHESIS_NOT_ACTIONABLE"
EXPERT_NAMES = (
    "trend_continuation", "range_reversion", "breakout",
    "failed_breakout_reversal", "participation", "volatility_transition",
)


def _number(frame: dict, key: str) -> D:
    return decimal_number(frame[key], key)


def classify_market(perception: dict) -> dict:
    """Heuristic description, not a learned or calibrated market probability."""
    frames = perception["frames"]
    if set(frames) != set(REQUIRED_FRAMES):
        raise ValueError("Missing perception frames")
    h1, h4, m15, m5 = (frames[key] for key in ("1h", "4h", "15m", "5m"))
    h1_dir = _number(h1, "fast_ema8_minus_slow_ema21_atr")
    h4_dir = _number(h4, "fast_ema8_minus_slow_ema21_atr")
    m15_dir = _number(m15, "fast_ema8_minus_slow_ema21_atr")
    m5_impact = _number(m5, "last_close_change_atr")
    range_width = _number(m15, "range_20_completed_atr")

    # Independent hypotheses; one state is a descriptive primary label only.
    directions_agree = h1_dir * h4_dir > 0
    if h1_dir > D("0.2") and h4_dir > D("0.1"):
        primary = "TREND_UP"
    elif h1_dir < D("-0.2") and h4_dir < D("-0.1"):
        primary = "TREND_DOWN"
    elif not directions_agree and abs(h1_dir) >= D("0.15"):
        primary = "TRANSITION_OR_TIMEFRAME_CONFLICT"
    elif abs(m15_dir) <= D("0.15") and range_width < D("5.0"):
        primary = "BALANCED_OR_RANGE"
    else:
        primary = "MIXED_OR_UNRESOLVED"
    return {
        "status": "DESCRIPTIVE_HEURISTIC_NOT_TRAINED_CLASSIFIER",
        "primary": primary,
        "strong_five_minute_move": abs(m5_impact) >= D("0.80"),
        "fast_and_slow_trends_agree": directions_agree,
        "hour_trend_atr": str(h1_dir),
        "four_hour_trend_atr": str(h4_dir),
        "fifteen_minute_trend_atr": str(m15_dir),
        "research_interpretation_only": True,
    }


def hypothesis(p: dict, expert: str, direction: str, reason: str,
               evidence: dict, strength: int) -> dict:
    if expert not in EXPERT_NAMES or direction not in ("LONG", "SHORT"):
        raise ValueError("Invalid expert hypothesis")
    if not 1 <= strength <= 5 or type(strength) is not int:
        raise ValueError("Invalid heuristic evidence strength")
    return {
        "schema": 1,
        "status": RESEARCH_ONLY_STATUS,
        "symbol": p["symbol"],
        "as_of_ms": p["as_of_ms"],
        "source_sha256": p["feature_source_sha256"],
        "expert": expert, "direction": direction,
        "heuristic_evidence_strength_NOT_PROBABILITY": strength,
        "thesis": reason,
        "feature_evidence": evidence,
        "entry_price": None, "stop_loss": None, "take_profit": None,
        "expected_net_r": None, "win_probability": None,
        "publishable_signal": False,
        "executable_order": False,
    }


def discover_hypotheses(p: dict) -> list[dict]:
    """Six opportunity experts independently inspect their own as-of evidence.

    Experts may disagree. Both directions can be recorded as competing
    hypotheses; downstream *future* arbitration must not sum scores to
    manufacture a probability or issue an executable recommendation.
    """
    f = p["frames"]
    if set(f) != set(REQUIRED_FRAMES):
        raise ValueError("Incomplete market-perception features")
    m1, m5, m15, h1, h4 = (f[tf] for tf in ("1m", "5m", "15m", "1h", "4h"))
    delta5 = _number(m5, "last_close_change_atr")
    body5 = _number(m5, "last_body_atr")
    impulse1 = _number(m1, "last_body_atr")
    trend5 = _number(m5, "fast_ema8_minus_slow_ema21_atr")
    trend15 = _number(m15, "fast_ema8_minus_slow_ema21_atr")
    trend1h = _number(h1, "fast_ema8_minus_slow_ema21_atr")
    trend4h = _number(h4, "fast_ema8_minus_slow_ema21_atr")
    extension5 = _number(m5, "price_minus_ema21_atr")
    range15 = _number(m15, "range_20_completed_atr")
    position5 = _number(m5, "position_vs_prev20_range")
    volume5 = (
        _number(m5, "volume_vs_previous20")
        if m5["volume_vs_previous20"] is not None else D(0)
    )
    volume1 = (
        _number(m1, "volume_vs_previous20")
        if m1["volume_vs_previous20"] is not None else D(0)
    )
    out = []

    # 1. Trend continuation: both large frames provide context; recent
    # 5m trend gives a separate, causally closed trigger.
    for sign, label in ((D(1), "LONG"), (D(-1), "SHORT")):
        if (
            sign * trend1h >= D("0.20")
            and sign * trend4h >= D("0.10")
            and sign * trend5 >= D("0.10")
            and D("-0.40") <= sign * extension5 <= D("1.80")
            and sign * delta5 > 0
        ):
            out.append(hypothesis(
                p, "trend_continuation", label,
                "Aligned higher-timeframe trend with renewed 5m continuation",
                {"1h_trend_atr": str(trend1h), "4h_trend_atr": str(trend4h),
                 "5m_ema_extension_atr": str(extension5)}, 3,
            ))

    # 2. Range reversion: no fixed 4h alignment veto. Looks near 5m
    # range boundaries when 15m/1h trends are weak.
    if (
        abs(trend1h) < D("0.30")
        and abs(trend15) < D("0.30")
        and range15 <= D("5.50")
    ):
        if position5 <= D("0.20") and body5 > 0:
            out.append(hypothesis(
                p, "range_reversion", "LONG",
                "Evidence of buying near lower range boundary",
                {"5m_position":str(position5),"15m_range_atr":str(range15)}, 2,
            ))
        elif position5 >= D("0.80") and body5 < 0:
            out.append(hypothesis(
                p, "range_reversion", "SHORT",
                "Evidence of selling near upper range boundary",
                {"5m_position":str(position5),"15m_range_atr":str(range15)}, 2,
            ))

    # 3. Breakouts: deliberate source-close range breakout, not a
    # retrospectively selected wick or intrabar signal.
    if volume5 >= D("1.20"):
        if m5["close_above_previous20_high"]:
            out.append(hypothesis(
                p, "breakout", "LONG",
                "Completed 5m close broke prior 20-bar high on relative volume",
                {"5m_relative_volume":str(volume5),
                 "previous20_high":m5["previous20_high"]}, 3,
            ))
        elif m5["close_below_previous20_low"]:
            out.append(hypothesis(
                p, "breakout", "SHORT",
                "Completed 5m close broke prior 20-bar low on relative volume",
                {"5m_relative_volume":str(volume5),
                 "previous20_low":m5["previous20_low"]}, 3,
            ))

    # 4. Reversal: a *completed* 5m sweep/rejection plus 1m response.
    if m5["rejected_new_high"] and impulse1 < 0:
        out.append(hypothesis(
            p, "failed_breakout_reversal", "SHORT",
            "5m high sweep failed to hold; completed 1m body turned down",
            {"1m_body_atr":str(impulse1),"prior_high":m5["previous20_high"]}, 2,
        ))
    if m5["rejected_new_low"] and impulse1 > 0:
        out.append(hypothesis(
            p, "failed_breakout_reversal", "LONG",
            "5m low sweep reclaimed range; completed 1m body turned up",
            {"1m_body_atr":str(impulse1),"prior_low":m5["previous20_low"]}, 2,
        ))

    # 5. Activity/participation expert: OHLCV body/volume proxy only.
    # NEVER claim this observes true aggressor flow or order-book delta.
    if volume1 >= D("1.50") and volume5 >= D("1.10"):
        if impulse1 > D("0.10") and body5 > D("0.10"):
            direction = "LONG"
        elif impulse1 < D("-0.10") and body5 < D("-0.10"):
            direction = "SHORT"
        else:
            direction = None
        if direction:
            out.append(hypothesis(
                p, "participation", direction,
                "Abnormal completed-candle volume accompanies directional body; not trade-level order flow",
                {"1m_relative_volume":str(volume1),
                 "5m_relative_volume":str(volume5)}, 2,
            ))

    # 6. Volatility expansion: detect an ATR-scaled impulse regardless of
    # 1h/4h orientation; later execution models must penalize chasing.
    if abs(delta5) >= D("0.80") and volume5 >= D("1.10"):
        out.append(hypothesis(
            p, "volatility_transition", "LONG" if delta5 > 0 else "SHORT",
            "Completed 5m movement expanded relative to ATR with participation",
            {"5m_close_change_atr":str(delta5),
             "5m_relative_volume":str(volume5)}, 2,
        ))

    return sorted(
        out, key=lambda r: (
            -r["heuristic_evidence_strength_NOT_PROBABILITY"],
            r["expert"], r["direction"],
        ),
    )


def research_market(snapshot_perceptions: list[dict]) -> dict:
    """Deterministic watch-case output. Cannot form actionable trade plans."""
    breadth = breadth_context(snapshot_perceptions)
    market_results = []
    for perception in sorted(snapshot_perceptions, key=lambda p: p["symbol"]):
        state = classify_market(perception)
        cases = discover_hypotheses(perception)
        market_results.append({
            "symbol":perception["symbol"],
            "state":state,
            "watch_hypotheses":cases,
            "hypothesis_count":len(cases),
            "competing_directions": len({c["direction"] for c in cases}) > 1,
        })
    return {
        "schema":1, "engine":"T7Sonic",
        "status":"RESEARCH_WATCH_ONLY_NO_SIGNAL_PUBLICATION",
        "as_of_ms":breadth["as_of_ms"],
        "market_breadth":breadth,
        "market_reports":market_results,
        "market_count":len(market_results),
        "watch_hypothesis_count":sum(x["hypothesis_count"] for x in market_results),
        "actionable_signal_count":0,
        "probability_model_status":"NOT_TRAINED",
        "risk_and_execution_model_status":"NOT_IMPLEMENTED",
        "performance_status":"NOT_BACKTESTED",
        "limitations":[
            "Opportunity hypotheses are NOT orders or actionable trading signals",
            "Heuristic evidence strength does not represent probability or profitability",
            "The pilot has no bid/ask spread, exchange order-book, liquidation, funding or OI source",
            "Input OHLCV producer/source checksum must be independently authenticated",
            "No 80% accuracy, daily signal count or positive expected return is claimed",
        ],
    }
