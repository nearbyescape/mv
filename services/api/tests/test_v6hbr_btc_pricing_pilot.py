"""BTC cost-proxy orchestrator: fail-closed inputs and as-of strategy parity."""
from decimal import Decimal as D
from types import SimpleNamespace
import sys

import pytest

from app.research import v6hbr_btc_pricing_pilot as pilot
from app.research.v6hbr_execution_model import ExecutionScenario
from test_v5_decision_replay import _maps, _v4_base

Q = 900_000
M = 60_000
SCENARIO = ExecutionScenario(D(2), D(2), D(5), D(1), 1)


def bar(t, o="100"):
    return SimpleNamespace(open_time=t, open=D(o), high=D(o), low=D(o), close=D(o))


def test_exact_completed_v4_event_prices_without_any_15m_rescue(monkeypatch):
    maps, source, boundary = _maps()
    fake = SimpleNamespace(
        outcome="LONG_SETUP", direction="long",
        setup_type="momentum_breakout", regime="established",
        checks=[{"id": "long.recent_run_atr", "value": "1.2"},
                {"id": "long.source_extension_atr", "value": "0.3"}],
    )
    monkeypatch.setattr(pilot, "evaluate_setup_v4", lambda *args: fake)
    monkeypatch.setattr(pilot, "btc_timing_reason", lambda *args: None)
    monkeypatch.setattr(pilot, "balanced_15m_filter_reason", lambda *args: None)
    def build(symbol, setup, source, quote, pf, now):
        assert quote.time == boundary + M
        assert source.bar.close_time + 1 == boundary
        return {"entry": str(quote.ask), "strategy": "MV-TREND-DUAL-v4"}
    monkeypatch.setattr(pilot, "build_plan_v4", build)
    monkeypatch.setattr(pilot, "simulate_reference_trade", lambda *args: {
        "status": "TP3", "terminal_at_ms": boundary + 2*M,
        "net_realized_r": "1.2", "adverse_050_at_ms": None,
        "favorable_050_at_ms": None, "exits": [],
    })
    candidate = {
        "lane": "v4_base", "symbol": "BTCUSDT",
        "at_ms": boundary, "context_open_ms": source,
        "direction": "long", "setup_type": "momentum_breakout",
        "regime": "established",
    }
    priced = pilot.price_candidates([candidate], maps, [bar(boundary + M)], SCENARIO, D("0.1"))
    assert len(priced) == 1
    assert priced[0]["preliminary_reason"] is None
    assert priced[0]["outcome"]["net_realized_r"] == "1.2"
    assert priced[0]["plan_strategy"] == "MV-TREND-DUAL-v4"
    assert priced[0]["recent_run_atr"] == "1.2"


def test_unknown_or_missing_tick_reference_fails_closed(monkeypatch):
    maps, source, boundary = _maps()
    monkeypatch.setattr(pilot, "btc_timing_reason", lambda *args: None)
    monkeypatch.setattr(pilot, "evaluate_setup_v4", lambda *args: SimpleNamespace(
        outcome="LONG_SETUP", direction="long", setup_type="momentum_breakout",
        regime="established", checks=[
            {"id": "long.recent_run_atr", "value": "1.2"},
            {"id": "long.source_extension_atr", "value": "0.3"},
        ],
    ))
    monkeypatch.setattr(pilot, "balanced_15m_filter_reason", lambda *args: None)
    candidate = {
        "lane": "v4_base", "symbol": "BTCUSDT",
        "at_ms": boundary, "context_open_ms": source,
        "direction": "long", "setup_type": "momentum_breakout",
        "regime": "established",
    }
    # If full 1m is missing, don't assume a zero-cost fill.
    priced = pilot.price_candidates([candidate], maps, [], SCENARIO, D("0.1"))
    assert priced[0]["preliminary_reason"] == "REFERENCE_ENTRY_UNAVAILABLE"
    assert priced[0]["outcome"] is None


def test_cost_scenario_cannot_silently_bypass_v4_spread_veto():
    scenario = ExecutionScenario(D(11), D(0), D(5), D(0), 1)
    with pytest.raises(ValueError, match="10bps"):
        pilot.run_development_proxy(
            None, scenario=scenario, assumed_tick=D("0.1"),
            risk_unit=D("0.5"), max_aggregate_risk=D(2),
        )


def test_command_line_requires_explicit_proxy_acknowledgement(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "v6hbr_btc_pricing_pilot", "--root", "/nonexistent",
        "--assumed-tick", "0.1", "--spread-bps", "2",
        "--slippage-bps", "2", "--taker-fee-bps", "5",
        "--funding-debit-bps-per-8h", "1",
        "--risk-unit", "0.5", "--max-aggregate-risk", "2",
    ])
    with pytest.raises(SystemExit) as e:
        pilot.main()
    assert e.value.code == 2


def test_pinned_agent_coverage_entry_adversity_reversal_and_censoring():
    """Pinned VPS script already runs this test module at every revision."""
    from app.research.v6hbr_entry_adversity import entry_adversity_report

    published = 1775016000000  # UTC minute boundary; exact date immaterial
    first = published + M
    bars = [
        SimpleNamespace(open_time=first, open=D(100), close=D(100),
                        high=D("100.2"), low=D("98.8")),
        SimpleNamespace(open_time=first + M, open=D(100), close=D(100),
                        high=D("101.5"), low=D("99.6")),
    ]
    row = {
        "id": "BTCUSDT:v4:diagnostic", "at_ms": published,
        "lane": "v4_base", "direction": "long",
        "outcome": {
            "status": "TP3",
            "entry_at_ms": first,
            "terminal_at_ms": first + 2 * M,
            "entry_price_scenario": "100",
            "risk_distance_at_fill": "2",
        },
    }
    states = {
        name: {"accepted_ids": [row["id"]]}
        for name in ("V4", "H", "B", "R")
    }
    report = entry_adversity_report(
        [row], bars, states, end_exclusive_ms=first + 2*M
    )
    sample = report["cohorts"]["V4"]["entry_details"][0]["windows"]["15"]
    assert sample["first_0p5r_event"] == "ADVERSE_FIRST"
    assert sample["observed_minutes"] == 2
    assert sample["complete_window"] is False
    assert report["cohorts"]["V4"]["windows"]["15"]["overall"][
        "closed_before_window_end"
    ] == 1


def test_pinned_agent_coverage_entry_adversity_requires_all_minutes():
    """No hidden favorable-only interpolation across missing 1m candles."""
    from app.research.v6hbr_entry_adversity import entry_adversity_report

    published = 1775016000000
    first = published + M
    row = {
        "id": "BTCUSDT:v4:minute-gap", "at_ms": published,
        "lane": "v4_base", "direction": "long",
        "outcome": {
            "status": "TP3",
            "entry_at_ms": first,
            "terminal_at_ms": first + 3*M,
            "entry_price_scenario": "100",
            "risk_distance_at_fill": "2",
        },
    }
    states = {
        name: {"accepted_ids": [row["id"]]}
        for name in ("V4", "H", "B", "R")
    }
    with pytest.raises(ValueError, match="Minute-gap"):
        entry_adversity_report(
            [row], [bar(first), bar(first + 2*M)], states,
            end_exclusive_ms=first + 3*M
        )


def test_pinned_vps_agent_rejects_premature_live_v6hbr_promotion():
    """Fixed installed V6HBR runner already executes this test module."""
    from app.research.v6hbr_release_readiness import assess_release_readiness
    no_evidence = assess_release_readiness(None)
    assert no_evidence["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert not no_evidence["can_auto_deploy"]
    btc_proxy_only = assess_release_readiness({
        "schema": 1, "candidate": "V6HBR",
        "reviewed_commit_sha": "f"*40,
        "data_scope": "BTC_APR_MAY_DEVELOPMENT_ONLY",
        "validation_resolved": 24,
        "validation_symbols": 1,
    })
    assert btc_proxy_only["decision"] == "NO_GO_FOR_LIVE_V6HBR"
    assert "INSUFFICIENT_DATA_SCOPE" in btc_proxy_only["reasons"]
    assert not btc_proxy_only["can_claim_high_accuracy"]
