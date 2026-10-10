"""Conservative reference fills: no claim of historical book depth/funding."""
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.research.v6hbr_execution_model import ExecutionScenario, simulate_reference_trade

T = 60000
PLAN = {"direction": "long", "stop": "98", "tp1": "102", "tp2": "103", "tp3": "104"}
ZERO = ExecutionScenario(D(0), D(0), D(0), D(0))


def bar(t, o=100, h=100, l=100, c=100):
    return SimpleNamespace(open_time=t, open=D(o), high=D(h), low=D(l), close=D(c))


def test_simultaneous_initial_stop_and_target_is_stop_first():
    result = simulate_reference_trade(PLAN, [bar(T), bar(2*T), bar(3*T, 100, 103, 98, 100)], 0, ZERO)
    assert result["status"] == "STOP"
    assert D(result["net_realized_r"]) == -1
    assert result["intraminute_stop_first_ties"] == 1
    assert result["tp_count"] == 0


def test_tp1_then_next_minute_breakeven_protection():
    bars = [bar(T), bar(2*T, 100, 102.1, 99.5, 102), bar(3*T, 101, 101, 99.5, 100)]
    result = simulate_reference_trade(PLAN, bars, 0, ZERO)
    assert result["status"] == "PROTECTED_STOP"
    assert D(result["net_realized_r"]) == D("0.30")
    assert result["tp_count"] == 1
    assert D(result["remaining_fraction"]) == 0


def test_stop_updates_only_after_minute_with_target():
    result = simulate_reference_trade(PLAN, [bar(T, 100, 102.1, 99, 101)], 0, ZERO)
    assert result["status"] == "OPEN_UNRESOLVED"
    assert result["tp_count"] == 1
    assert result["net_realized_r"] is None
    assert result["open_mark_r_not_booked"] is not None


def test_three_targets_and_costs():
    result = simulate_reference_trade(PLAN, [bar(T,100,104.5,99,104)], 0, ZERO)
    assert result["status"] == "TP3"
    assert D(result["net_realized_r"]) == D("1.55")
    costly = simulate_reference_trade(
        PLAN, [bar(T,100,104.5,99,104)], 0,
        ExecutionScenario(D(2), D(1), D(4), D(0))
    )
    assert D(costly["net_realized_r"]) < D(result["net_realized_r"])


def test_latency_and_data_gaps_fail_closed():
    with pytest.raises(ValueError, match="First executable"):
        simulate_reference_trade(PLAN, [bar(2*T)], 0, ZERO)
    with pytest.raises(ValueError, match="gap"):
        simulate_reference_trade(PLAN, [bar(T), bar(3*T)], 0, ZERO)
    assert simulate_reference_trade(PLAN, [], 0, ZERO)["status"] == "NO_FILL_REFERENCE"


def test_cost_scenario_is_explicit_and_validated():
    with pytest.raises(ValueError, match="cost scenario"):
        simulate_reference_trade(PLAN, [bar(T)], 0, ExecutionScenario(D(-1), D(0), D(0), D(0)))
    with pytest.raises(ValueError, match="Latency"):
        simulate_reference_trade(PLAN, [bar(T)], 0, ExecutionScenario(D(0), D(0), D(0), D(0), 0))


def test_short_stop_first_and_short_tp3():
    plan = {"direction":"short", "stop":"102", "tp1":"98", "tp2":"97", "tp3":"96"}
    result = simulate_reference_trade(plan, [bar(T,100,102,96,99)], 0, ZERO)
    assert result["status"] == "STOP"
    assert D(result["net_realized_r"]) == -1
    assert result["intraminute_stop_first_ties"] == 1
    profit = simulate_reference_trade(plan, [bar(T,100,100,95.5,96)], 0, ZERO)
    assert profit["status"] == "TP3"
    assert D(profit["net_realized_r"]) == D("1.55")
