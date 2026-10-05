from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import pytest
from mv_strategy.entry_filters import entry_filter
from mv_strategy.backtest import Replay
from app.research.exit_study import replay_policies
from test_backtest import START, FILTER, ZERO, sources, minutes, replay


@pytest.mark.parametrize("direction,sign", [("long", 1), ("short", -1)])
@pytest.mark.parametrize("change,passed", [("0.099999", False), ("0.1", True), ("0.100001", True), ("-0.1", False)])
def test_slope_direction_and_inclusive_threshold_with_rational_oracle(direction, sign, change, passed):
    history = sources(direction)
    current, previous = history["1h"][START-3_600_000], history["1h"][START-7_200_000]
    current = replace(current, ema50=previous.ema50 + sign*D(change))
    check = entry_filter("slope", current, previous, direction)
    assert check["passed"] is passed
    assert check["passed"] == (sign*(F(current.ema50)-F(previous.ema50)) >= F("0.05")*F(current.atr))


@pytest.mark.parametrize("gap,passed", [("0.999999", False), ("1", True), ("1.000001", True)])
def test_separation_threshold_without_direction_bias(gap, passed):
    history = sources()
    current, previous = history["1h"][START-3_600_000], history["1h"][START-7_200_000]
    current = replace(current, ema20=current.ema50+D(gap))
    assert entry_filter("separation", current, previous, "long")["passed"] is passed
    assert entry_filter("separation", current, previous, "short")["passed"] is passed


def test_filters_are_independent_and_original_control_is_exact():
    history, bars = sources(), minutes()
    rows = replay_policies("BTCUSDT", bars, history, [], FILTER, {"baseline": ZERO}, START, START+3_600_000, D(1000), True)
    assert rows[("baseline", "baseline")] == replay(bars)
    assert len(rows[("separation", "baseline")]["trades"]) == 1
    assert rows[("slope", "baseline")]["trades"] == []
    plan = rows[("separation", "baseline")]["trades"][0]["plan"]
    control = rows[("baseline", "baseline")]["trades"][0]["plan"]
    assert all(plan[k] == control[k] for k in ("entry", "stop", "target", "frozen_atr", "risk_policy"))
    assert plan["id"] != control["id"] and plan["strategy"] == "EMA-PULLBACK-ATR-GAP-v1"


def test_alignment_and_unregistered_combinations_fail_closed():
    history = sources()
    current, previous = history["1h"][START-3_600_000], history["1h"][START-7_200_000]
    for invalid in (None, replace(previous, history_origin=previous.history_origin-3_600_000, count=previous.count+1)):
        with pytest.raises(ValueError):
            entry_filter("slope", current, invalid, "long")
    with pytest.raises(ValueError):
        entry_filter("separation", replace(current, atr=D(0)), previous, "long")
    with pytest.raises(ValueError):
        Replay("BTCUSDT", history, [], FILTER, ZERO, START, START+3_600_000, D(1000), "stop_target", "slope")


def test_filter_results_ignore_caller_precision():
    history = sources()
    current, previous = history["1h"][START-3_600_000], history["1h"][START-7_200_000]
    with localcontext() as ctx:
        ctx.prec = 5
        low = entry_filter("separation", current, previous, "long")
    with localcontext() as ctx:
        ctx.prec = 50
        assert entry_filter("separation", current, previous, "long") == low


def test_filter_report_api_is_readonly_verified_and_export_paths_are_confined(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.research import reports
    from app.research.exit_study import publish
    from test_research_data import AUTH
    monkeypatch.setattr(reports, "FILTER_ROOT", tmp_path)
    client = TestClient(app)
    assert client.get("/v1/research/filters").status_code == 401
    assert client.get("/v1/research/filters", headers=AUTH).json() == {"available":False,"report":None}
    report = {"id":"a"*64,"groups":[]}
    publish(report, {"diagnostics.json":b"[]"}, tmp_path)
    assert client.get("/v1/research/filters",headers=AUTH).json()["report"]["groups"] == []
    assert client.get("/v1/research/filters/export?file=diagnostics.json",headers=AUTH).json() == []
    assert client.get("/v1/research/filters/export?file=../secret",headers=AUTH).status_code == 422
    assert client.post("/v1/research/filters",headers=AUTH).status_code == 405
    (tmp_path/report["id"]/"diagnostics.json").write_text("tampered")
    assert client.get("/v1/research/filters/export?file=diagnostics.json",headers=AUTH).status_code == 422
