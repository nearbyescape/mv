from dataclasses import replace
from decimal import Decimal as D

from mv_strategy.signals import PriceFilter
from mv_strategy.strategy_v5 import evaluate_context_v5, evaluate_trigger_v5
from app.research.v5_compare import (
    _is_mature_4h,
    _observation_end_open,
    _v5_reference_plan,
    simulate_v5_with_safety,
)
from app.research.v4_retrospective import Candidate
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


def test_v5_four_hour_maturity_requires_complete_observation_window():
    published = 20_000_000
    minute = 60_000
    four_hours = 4 * 3_600_000

    row = Candidate(
        signal_id="v5-test",
        symbol="BTCUSDT",
        direction="short",
        source_open_time=published - 15 * minute,
        source_close=published,
        published_at=published,
        setup_type="momentum_breakout",
        regime="established",
        recent_run_atr=D("1"),
        source_extension_atr=D("0.5"),
        favorable_050_at=None,
        adverse_050_at=None,
        historical_last_minute_open_time=None,
    )
    assert _is_mature_4h(row, published + four_hours) is True
    assert _is_mature_4h(row, published + four_hours - minute) is False


def _safety_candidate(signal_id, symbol, published_at, direction="short"):
    row = Candidate(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        source_open_time=published_at - 15 * 60_000,
        source_close=published_at,
        published_at=published_at,
        setup_type="momentum_breakout",
        regime="established",
        recent_run_atr=D("1"),
        source_extension_atr=D("0.5"),
        favorable_050_at=None,
        adverse_050_at=None,
    )
    row.v4_scaled_outcome = {
        "status": "open",
        "terminal_at": None,
        "favorable_050_at": None,
        "adverse_050_at": None,
    }
    return row


def test_v5_safety_caps_same_direction_to_two_in_rolling_hour():
    base = 30_000_000
    rows = [
        _safety_candidate("a", "AUSDT", base),
        _safety_candidate("b", "BUSDT", base + 15 * 60_000),
        _safety_candidate("c", "CUSDT", base + 30 * 60_000),
        _safety_candidate("d", "DUSDT", base + 60 * 60_000),
    ]

    simulate_v5_with_safety(rows)

    assert rows[0].capped_reason == "WOULD_PUBLISH_V4"
    assert rows[1].capped_reason == "WOULD_PUBLISH_V4"
    assert (
        rows[2].capped_reason
        == "ROLLING_MARKET_DIRECTION_CONCENTRATION_LIMIT"
    )
    # Exactly one hour after the first publication, that first row has aged
    # out of the rolling window and one slot is available again.
    assert rows[3].capped_reason == "WOULD_PUBLISH_V4"
