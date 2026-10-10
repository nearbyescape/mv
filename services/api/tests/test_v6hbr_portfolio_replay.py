"""Pure chronological V6HBR cohort-policy regression fixtures."""
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.research.v6hbr_portfolio_replay import HOUR, simulate_cohort

T = int(datetime(2026, 4, 1, 4, 0, tzinfo=timezone.utc).timestamp() * 1000)
Q = 15 * 60_000


def outcome(at, *, terminal_minutes=90, net="0.5", adverse=None, favorable=None, status="TP3"):
    return {
        "status": status,
        "terminal_at_ms": at + terminal_minutes * 60_000 if status in ("TP3", "STOP", "PROTECTED_STOP") else None,
        "net_realized_r": net if status in ("TP3", "STOP", "PROTECTED_STOP") else None,
        "adverse_050_at_ms": at + adverse * 60_000 if adverse is not None else None,
        "favorable_050_at_ms": at + favorable * 60_000 if favorable is not None else None,
        "exits": [],
    }


def event(i, at, lane="15m_rescue", direction="long", regime="established", **extra):
    return {
        "id": str(i), "symbol": f"TEST{i}USDT", "lane": lane,
        "direction": direction, "regime": regime,
        "at_ms": at, "context_open_ms": (at // HOUR - 1) * HOUR,
        "recent_run_atr": "0.7", "source_extension_atr": "0.2",
        "outcome": outcome(at), **extra,
    }


def run(rows, name):
    return simulate_cohort(rows, name, risk_unit=D(1), max_aggregate_risk=D(10))


def test_reserved_prospectively_avoids_early_rescue_crowd_out():
    # No policy gets to inspect that the later V4 signal is profitable.
    rows = [
        event(1, T + Q),
        event(2, T + 2 * Q),
        event(3, T + HOUR, "v4_base"),
    ]
    v4, hybrid, balanced, reserved = (run(rows, name) for name in ("V4", "H", "B", "R"))
    assert v4["accepted_ids"] == ["3"]
    assert hybrid["accepted_ids"] == ["1", "2"]
    assert balanced["accepted_ids"] == ["1", "2"]
    assert reserved["accepted_ids"] == ["1", "3"]
    assert reserved["rejections"]["RESCUE_LANE_ROLLING_LIMIT"] == 1


def test_balanced_fails_closed_on_missing_emerging_confirmation():
    rows = [event(1, T, "v4_base", regime="emerging")]
    assert run(rows, "H")["accepted_ids"] == ["1"]
    assert run(rows, "B")["accepted_ids"] == []
    rows[0]["balanced_confirmed"] = True
    assert run(rows, "B")["accepted_ids"] == ["1"]


def test_independent_portfolio_state_and_future_outcomes_cannot_select_winner():
    rows = [event(1, T + Q), event(2, T + 2 * Q), event(3, T + HOUR, "v4_base")]
    one = run(rows, "R")
    rows[2]["outcome"]["net_realized_r"] = "-2"
    two = run(rows, "R")
    assert one["accepted_ids"] == two["accepted_ids"] == ["1", "3"]
    assert one["resolved_net_r_sum"] != two["resolved_net_r_sum"]
    assert run(rows, "H")["accepted_ids"] == ["1", "2"]


def test_circuit_breaker_only_reads_past_complete_milestones():
    rows = [
        event(1, T, "v4_base", outcome=outcome(T, adverse=2, favorable=50)),
        event(2, T + Q, "15m_rescue", outcome=outcome(T+Q, adverse=2, favorable=50)),
        event(3, T + 2*Q, "15m_rescue", direction="long"),
    ]
    assert run(rows, "H")["accepted_ids"] == ["1", "2"]
    assert run(rows, "H")["rejections"]["DIRECTIONAL_CIRCUIT_BREAKER"] == 1
    rows[1]["outcome"] = outcome(T+Q, adverse=45)
    assert run(rows, "H")["accepted_ids"] == ["1", "2", "3"]


def test_open_unresolved_never_books_net_r_and_blocks_overlapping_symbol():
    first = event(1, T, "v4_base", outcome=outcome(T, status="OPEN_UNRESOLVED", net=None))
    second = event(2, T + Q, "15m_rescue", direction="short", symbol=first["symbol"])
    report = run([first, second], "H")
    assert report["accepted_ids"] == ["1"]
    assert report["rejections"]["SYMBOL_ALREADY_ACTIVE"] == 1
    assert report["resolved_net_r_sum"] == "0"
    assert report["unresolved_references"] == 1


def test_missing_milestones_and_uncertified_risk_budget_fail_closed():
    rows = [event(1, T)]
    del rows[0]["outcome"]["adverse_050_at_ms"]
    with pytest.raises(ValueError, match="milestone"):
        run(rows, "H")
    rows[0]["outcome"]["adverse_050_at_ms"] = None
    with pytest.raises(ValueError, match="risk budget"):
        simulate_cohort(rows, "H", risk_unit=D("0.5"), max_aggregate_risk=D("0.1"))


def test_missing_execution_outcome_does_not_become_zero_cost_win():
    rows = [event(1, T)]
    rows[0]["outcome"] = None
    with pytest.raises(ValueError, match="execution outcome"):
        run(rows, "H")


def test_conservative_partial_release_of_proxy_risk_slots():
    rows = [
        event(1, T, "v4_base", outcome=outcome(T, status="OPEN_UNRESOLVED", net=None)),
        event(2, T + Q, "15m_rescue"),
    ]
    with pytest.raises(ValueError, match="risk budget"):
        simulate_cohort(rows, "H", risk_unit=D(1), max_aggregate_risk=D("0.5"))
    restricted = simulate_cohort(rows, "H", risk_unit=D(1), max_aggregate_risk=D(1))
    assert restricted["accepted_ids"] == ["1"]
    assert restricted["rejections"]["PROXY_AGGREGATE_RISK_CAP"] == 1
    rows[0]["outcome"]["exits"] = [
        {"at_ms": T + Q - 60_000, "fraction": "0.3"},
        {"at_ms": T + Q - 60_000, "fraction": "0.3"},
    ]
    partial = simulate_cohort(rows, "H", risk_unit=D("0.5"), max_aggregate_risk=D(1))
    assert partial["accepted_ids"] == ["1", "2"]


def test_execution_milestones_come_from_finished_reference_minute():
    from types import SimpleNamespace
    from app.research.v6hbr_execution_model import ExecutionScenario, simulate_reference_trade
    plan = {"direction": "long", "stop": "98", "tp1": "102", "tp2": "103", "tp3": "104"}
    scenario = ExecutionScenario(D(0), D(0), D(0), D(0))
    row = SimpleNamespace(open_time=60_000, open=D(100), high=D(102), low=D(99), close=D(100))
    out = simulate_reference_trade(plan, [row], 0, scenario)
    assert out["favorable_050_at_ms"] == 120_000
    assert out["adverse_050_at_ms"] == 120_000
    assert out["status"] == "OPEN_UNRESOLVED"
    assert out["net_realized_r"] is None
