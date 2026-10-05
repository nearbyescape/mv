from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import json

import pytest
from fastapi.testclient import TestClient
from mv_strategy.backtest import Replay, touch
from app.main import app
from app.research import reports
from app.research.exit_study import replay_policies, publish
from test_backtest import START, FILTER, ZERO, sources, minutes, replay
from test_research_data import AUTH


def variants(bars, history=None, direction="long", funding=()):
    return replay_policies("BTCUSDT", bars, history or sources(direction, hours=len(bars)//60), funding, FILTER,
                           {"baseline": ZERO}, START, START + len(bars)*60_000, D(1000))


@pytest.mark.parametrize("direction", ["long", "short"])
def test_disabled_target_ignores_touch_and_favorable_gap_but_keeps_stop(direction):
    plan = {"direction": direction, "stop": "96" if direction == "long" else "104", "target": "108" if direction == "long" else "92"}
    bar = replace(minutes()[0], open=D(110 if direction == "long" else 90), high=D(111 if direction == "long" else 101), low=D(99 if direction == "long" else 89))
    assert touch(bar, plan)[1] == "target_gap"
    assert touch(bar, plan, target_enabled=False) is None
    both = replace(bar, open=D(100), high=D(110), low=D(90))
    assert touch(both, plan, target_enabled=False) == (D(plan["stop"]), "stop", False)
    assert touch(both, plan)[2] is True


def test_default_control_is_identical_and_variant_contract_is_explicit():
    bars = minutes()
    rows = variants(bars)
    assert rows[("baseline", "baseline")] == replay(bars)
    st = rows[("stop_target", "baseline")]["trades"][0]
    se = rows[("stop_ema50", "baseline")]["trades"][0]
    assert st["plan"]["strategy"] == "EMA-PULLBACK-ATR-EXITS-ST-v1"
    assert se["plan"]["strategy"] == "EMA-PULLBACK-ATR-EXITS-SE-v1"
    assert se["plan"]["target_active"] is False
    assert st["plan"]["ema50_exit_active"] is False
    assert len({rows[(p, "baseline")]["trades"][0]["signal_id"] for p in ("baseline", "stop_target", "stop_ema50")}) == 3
    assert se["stop"] == st["stop"] == rows[("baseline", "baseline")]["trades"][0]["stop"]


@pytest.mark.parametrize("direction,stop,target", [("long", "96", "108"), ("short", "104", "92")])
def test_target_ablation_continues_to_later_stop_with_independent_cash_oracle(direction, stop, target):
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109) if direction == "long" else D(101), low=D(99) if direction == "long" else D(91))
    bars[3] = replace(bars[3], high=D(101) if direction == "long" else D(105), low=D(95) if direction == "long" else D(99))
    result = variants(bars, direction=direction)
    assert F(result[("baseline", "baseline")]["ending_equity"]) == 1080
    row = result[("stop_ema50", "baseline")]
    assert row["trades"][0]["exit_reason"] == "stop"
    assert F(row["ending_equity"]) == 960
    assert row["trades"][0]["target"] == target and row["trades"][0]["stop"] == stop


def test_disabling_trend_exit_holds_until_partition_and_still_handles_pending_stop():
    history, bars = sources(atr="5"), minutes(2)
    source = history["1h"][START]
    history["1h"][START] = replace(source, bar=replace(source.bar, low=D(94), close=D(94)))
    bars[59] = replace(bars[59], open=D(94), high=D(94), low=D(94), close=D(94))
    bars[61] = replace(bars[61], open=D(98), high=D(100), low=D(97), close=D(99))
    result = variants(bars, history)
    assert result[("baseline", "baseline")]["trades"][0]["exit_reason"] == "ema50_exit"
    st = result[("stop_target", "baseline")]
    assert st["trades"][0]["exit_reason"] == "partition_end" and F(st["ending_equity"]) == 1000
    bars[60] = replace(bars[60], open=D(89), high=D(100), low=D(89), close=D(100))
    result = variants(bars, history)
    assert all(row["trades"][0]["exit_reason"] == "stop_gap" for row in result.values())


def test_unknown_policy_and_incomplete_minute_history_fail_closed():
    with pytest.raises(ValueError, match="policy"):
        Replay("BTCUSDT", sources(), [], FILTER, ZERO, START, START+3_600_000, D(1000), "automatic_best")
    with pytest.raises(ValueError, match="minute"):
        bars = minutes()
        bars[0] = bars[1]
        variants(bars)


def test_policies_retain_precision_independent_of_caller_context():
    with localcontext() as context:
        context.prec = 7
        low = variants(minutes())
    with localcontext() as context:
        context.prec = 50
        high = variants(minutes())
    assert low == high


def test_study_publication_reproducible_readonly_protected_and_tamper_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "STUDY_ROOT", tmp_path)
    client = TestClient(app)
    assert client.get("/v1/research/study").status_code == 401
    assert client.get("/v1/research/study", headers=AUTH).json() == {"available": False, "report": None}
    report = {"id": "a"*64, "groups": [], "diagnostics": []}
    files = {"diagnostics.json": b"[]", "trades.csv": b"net_pnl\n-1.00\n"}
    publish(dict(report), dict(files), tmp_path)
    before = (tmp_path/report["id"]/"report.json").read_bytes()
    publish(dict(report), dict(files), tmp_path)
    assert (tmp_path/report["id"]/"report.json").read_bytes() == before
    assert client.get("/v1/research/study", headers=AUTH).json()["report"]["diagnostics"] == []
    assert client.get("/v1/research/study/export?file=diagnostics.json", headers=AUTH).json() == []
    assert client.get("/v1/research/study/export?file=../secret", headers=AUTH).status_code == 422
    assert client.post("/v1/research/study", headers=AUTH).status_code == 405
    (tmp_path/report["id"]/"diagnostics.json").write_text("changed")
    assert client.get("/v1/research/study/export?file=diagnostics.json", headers=AUTH).status_code == 422
    with pytest.raises(ValueError, match="different"):
        publish(dict(report), {**files, "diagnostics.json": b"[1]"}, tmp_path)
    (tmp_path/report["id"]/"report.json").write_text(json.dumps({**json.loads(before), "groups": ["changed"]}))
    assert client.get("/v1/research/study", headers=AUTH).status_code == 503
