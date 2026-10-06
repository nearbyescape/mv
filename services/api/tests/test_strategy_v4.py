from decimal import Decimal as D

from mv_strategy.signals import PriceFilter
from mv_strategy.strategy_v3 import (
    LIVE_STRATEGY_ID as V3_STRATEGY_ID,
    build_plan_v3,
    evaluate_setup_v3,
    live_decision_id as v3_decision_id,
)
from mv_strategy.strategy_v4 import (
    LIVE_STRATEGY_ID,
    LIVE_RISK_ID,
    build_plan_v4,
    evaluate_setup_v4,
    live_decision_id,
)
from test_strategy_v3 import (
    BOUNDARY,
    SOURCE_OPEN,
    long_pullback_context,
    quote,
    short_breakout_context,
)


def test_v4_preserves_v3_setup_selection_exactly():
    for context in (long_pullback_context(), short_breakout_context()):
        v3 = evaluate_setup_v3(*context)
        v4 = evaluate_setup_v4(*context)
        assert v4 == v3


def test_v4_preserves_v3_risk_geometry_but_versions_identity():
    current, previous, confirmation, structure = long_pullback_context()
    setup = evaluate_setup_v4(current, previous, confirmation, structure)
    price_filter = PriceFilter(D("0.01"), D(0), D(10000))
    market_quote = quote("long", bid="100.59", ask="100.60")

    v3 = build_plan_v3(
        "BTCUSDT", setup, current, market_quote, price_filter, BOUNDARY + 1000
    )
    v4 = build_plan_v4(
        "BTCUSDT", setup, current, market_quote, price_filter, BOUNDARY + 1000
    )

    assert v4["strategy"] == LIVE_STRATEGY_ID == "MV-TREND-DUAL-v4"
    assert v4["risk_policy"] == LIVE_RISK_ID == "RISK-ATR14-SCALED-TP-v4"
    assert v3["strategy"] == V3_STRATEGY_ID
    for key in (
        "entry",
        "stop",
        "target",
        "tp1",
        "tp2",
        "tp3",
        "risk_distance",
        "tp1_r",
        "tp2_r",
        "tp3_r",
        "exit_management",
    ):
        assert v4[key] == v3[key]


def test_v4_decision_identity_is_separate_from_v3_history():
    assert live_decision_id("BTCUSDT", SOURCE_OPEN) != v3_decision_id(
        "BTCUSDT", SOURCE_OPEN
    )
    assert live_decision_id("BTCUSDT", SOURCE_OPEN) == live_decision_id(
        "BTCUSDT", SOURCE_OPEN
    )
