"""Production V4 strategy wrapper.

V4 preserves the validated V3 setup/risk arithmetic exactly and versions the
live identity so the market-safety governor can evolve without rewriting V3
history.
"""
from .signals import canonical_hash
from .strategy_v3 import (
    EXPIRY_MS,
    QUOTE_AGE_MS,
    STRUCTURE_BARS,
    RECENT_RUN_BARS,
    RECENT_RUN_MAX,
    TP1_R,
    TP2_R,
    TP3_R,
    TP1_ALLOCATION,
    TP2_ALLOCATION,
    TP3_ALLOCATION,
    MAX_SPREAD_BPS,
    LiveSetup,
    evaluate_setup_v3,
    build_plan_v3,
)

LIVE_STRATEGY_ID = "MV-TREND-DUAL-v4"
LIVE_RISK_ID = "RISK-ATR14-SCALED-TP-v4"


def live_decision_id(symbol: str, open_time: int) -> str:
    return canonical_hash([LIVE_STRATEGY_ID, "binance-usdm", symbol, "1h", open_time])


def evaluate_setup_v4(current, previous, confirmation, structure):
    return evaluate_setup_v3(current, previous, confirmation, structure)


def build_plan_v4(symbol, setup, source, quote, price_filter, now):
    plan = build_plan_v3(symbol, setup, source, quote, price_filter, now)
    plan["strategy"] = LIVE_STRATEGY_ID
    plan["risk_policy"] = LIVE_RISK_ID
    return plan
