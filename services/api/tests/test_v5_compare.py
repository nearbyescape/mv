from dataclasses import replace
from decimal import Decimal as D

from mv_strategy.signals import PriceFilter
from mv_strategy.strategy_v5 import evaluate_context_v5, evaluate_trigger_v5
from app.research.v5_compare import (
    _observation_end_open,
    _v5_reference_plan,
)
from test_strategy_v3 import BOUNDARY, short_breakout_context
from test_strategy_v5 import short_trigger_context


def test_v5_reference_plan_keeps_v4_two_atr_scaled_risk_geometry():
    source, previous, confirmation, structure = short_breakout_context()
    source = replace(source, atr=D("3"))
    armed = evaluate_context_v5(source, previous, confirmation, structure)
    assert armed.outcome == "ARMED"

    trigger_source, trigger_previous, trigger_structure = short_trigger_context(
        "pullback"
    )
    trigger = evaluate_trigger_v5(
        "short",
        trigger_source,
        trigger_previous,
        trigger_structure,
    )
    assert trigger.outcome == "TRIGGER"

    entry = D("99.20")
    plan = _v5_reference_plan(
        "BTCUSDT",
        armed,
        trigger,
        source,
        trigger_source,
        entry,
        PriceFilter(D("0.01"), D("0"), D("10000")),
        BOUNDARY + 15 * 60_000,
    )

    risk = D(plan["risk_distance"])
    assert risk == D("6.00")
    assert D(plan["stop"]) - entry == risk
    assert entry - D(plan["tp1"]) == D(plan["tp1_r"]) * risk
    assert entry - D(plan["tp2"]) == D(plan["tp2_r"]) * risk
    assert entry - D(plan["tp3"]) == D(plan["tp3_r"]) * risk
    assert plan["trigger_timeframe"] == "15m"
    assert plan["context_timeframe"] == "1h"
    assert plan["confirmation_timeframe"] == "4h"
    assert plan["exit_management"]["tp1_allocation"] == "0.30"
    assert plan["exit_management"]["tp2_allocation"] == "0.30"
    assert plan["exit_management"]["tp3_allocation"] == "0.40"


def test_v5_replay_observation_window_is_capped_at_four_hours():
    published = 10_000_000
    four_hours = 4 * 3_600_000
    minute = 60_000

    assert _observation_end_open(
        published,
        published + four_hours + 10 * minute,
    ) == published + four_hours - minute

    assert _observation_end_open(
        published,
        published + 30 * minute,
    ) == published + 29 * minute

    assert _observation_end_open(published, published) is None
