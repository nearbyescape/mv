from dataclasses import replace
from decimal import Decimal as D, localcontext
from fractions import Fraction as F
import json
import pytest
from fastapi.testclient import TestClient
from mv_strategy.backtest import Replay, Funding
from mv_strategy.entry_filters import ENTRY_POLICIES
from app.main import app
from app.paper import store
from app.paper.state import dump, restore, decode
from app.paper.worker import parse_settlements, frozen_specs
from test_backtest import START, FILTER, ZERO, sources, minutes
from test_research_data import AUTH


@pytest.fixture(autouse=True)
def isolate_previous_sample(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PREVIOUS_DB", tmp_path/"previous.db")
    from app.config import get_settings
    monkeypatch.setattr(get_settings(),"paper_enabled",True)


def journal(tmp_path):
    path = tmp_path/'paper.db'
    db = store.connection(path)
    engines = {p: Replay("BTCUSDT", sources(), [], FILTER, ZERO, START, START+3_600_000, D(1000), entry_policy=p) for p in ENTRY_POLICIES}
    payload = {"id": "a"*64, "start": START, "end_exclusive": START+3_600_000,
               "spec": {"observation_grace_ms": 120000, "policies": list(ENTRY_POLICIES)}, "code_hash": "b"*64}
    store.register(db, payload, {("BTCUSDT", p): e for p,e in engines.items()}, START)
    return path, db, engines


def test_restart_between_entry_and_target_preserves_cash_with_rational_oracle(tmp_path):
    path, db, engines = journal(tmp_path)
    bars = minutes()
    bars[2] = replace(bars[2], high=D(109))
    for index in range(3):
        context = sources() if index == 0 else {"1h": {}, "4h": {}}
        store.commit_minute(db, "BTCUSDT", bars[index], bars[index].close_time+2000, context, [], engines, START+28_800_000)
        # Restore after every observation, including the pending entry and open position.
        db.close()
        db = store.connection(path)
        engines = {s["policy"]: restore(store.checked(s)) for s in db.execute("SELECT * FROM sleeves")}
    assert F(engines["baseline"].cash) == F(1080)
    assert F(engines["separation"].cash) == F(1080)
    assert F(engines["slope"].cash) == F(1000)
    trade = engines["baseline"].trades[0]
    assert F(trade["net_pnl"]) == F(80)
    assert trade["plan"]["execution"] == "modeled-forward-minute-reference"
    assert trade["plan"]["observed_at"] > trade["entry_time"]
    assert trade["evidence"]["quote"]["source"] == "modeled-from-newly-observed-1m-open"
    feed = store.view(path, START)
    assert feed["run"]["observed_minutes"] == 3 and not feed["run"]["assessment_ready"]
    db.close()


def test_duplicate_gap_late_and_future_observations_never_advance_cursor(tmp_path):
    path, db, engines = journal(tmp_path)
    bar = minutes()[0]
    for invalid_bar, time in ((minutes()[1], bar.close_time+2000), (bar, bar.close_time), (bar, bar.close_time+120002)):
        with pytest.raises(ValueError):
            store.commit_minute(db, "BTCUSDT", invalid_bar, time, sources(), [], engines, START+28_800_000)
        assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
        assert all(row[0] == START for row in db.execute("SELECT cursor FROM sleeves"))
    store.commit_minute(db, "BTCUSDT", bar, bar.close_time+2000, sources(), [], engines, START+28_800_000)
    with pytest.raises(ValueError):
        store.commit_minute(db, "BTCUSDT", bar, bar.close_time+2000, sources(), [], engines, START+28_800_000)
    db.close()


def test_mid_policy_failure_rolls_back_all_states_and_minute(tmp_path):
    _, db, engines = journal(tmp_path)
    original = [dict(s) for s in db.execute("SELECT * FROM sleeves")]
    def fail(_):
        raise ValueError("Injected failure after baseline")
    engines["slope"].step = fail
    with pytest.raises(ValueError, match="Injected"):
        store.commit_minute(db, "BTCUSDT", minutes()[0], START+62000, sources(), [], engines, START+28_800_000)
    assert [dict(s) for s in db.execute("SELECT * FROM sleeves")] == original
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    db.close()


def test_signed_actual_funding_survives_checkpoint_and_precision(tmp_path):
    _, db, engines = journal(tmp_path)
    bars = minutes()
    for index in range(3):
        funding = [Funding(bars[index].open_time, D("0.01"), D(100))] if index == 2 else []
        with localcontext() as ctx:
            ctx.prec = 5
            store.commit_minute(db, "BTCUSDT", bars[index], bars[index].close_time+2000, sources() if index == 0 else {"1h": {}, "4h": {}}, funding, engines, START+28_800_000)
    assert F(engines["baseline"].cash) == 990
    assert F(engines["baseline"].position["funding"]) == -10
    assert restore(dump(engines["baseline"])).position == engines["baseline"].position
    db.close()


def test_forward_api_readonly_missing_stale_frozen_and_hash_fail_closed(tmp_path, monkeypatch):
    path, db, _ = journal(tmp_path)
    monkeypatch.setattr(store, "DB", path)
    client = TestClient(app)
    assert client.get("/v1/paper").status_code == 401
    assert client.post("/v1/paper", headers=AUTH).status_code == 405
    assert client.get("/v1/paper", headers=AUTH).json()["run"]["state"] == "stale"
    with db:
        db.execute("UPDATE run SET state='frozen',error='Observation gap'")
    assert client.get("/v1/paper", headers=AUTH).json()["run"]["state"] == "frozen"
    with db:
        db.execute("UPDATE sleeves SET payload='{}' WHERE policy='baseline'")
    assert client.get("/v1/paper", headers=AUTH).status_code == 503
    db.close()
    monkeypatch.setattr(store, "DB", tmp_path/'missing.db')
    assert client.get("/v1/paper", headers=AUTH).json() == {"available": False, "run": None}


def test_codecs_and_funding_reject_nonfinite_unknown_records_and_wrong_symbols():
    with pytest.raises(ValueError):
        decode({"$record": "exec", "fields": {}})
    with pytest.raises(ValueError):
        decode({"$decimal": "NaN"})
    row = {"symbol": "BTCUSDT", "fundingTime": START, "fundingRate": "-0.001", "markPrice": "100"}
    assert parse_settlements([row], "BTCUSDT", START, START+60000)[0].rate == D("-0.001")
    for invalid in ({**row, "symbol": "ETHUSDT"}, {**row, "fundingRate": 0.01}, {**row, "markPrice": "NaN"}):
        with pytest.raises(ValueError):
            parse_settlements([invalid], "BTCUSDT", START, START+60000)
    with pytest.raises(ValueError):
        parse_settlements([row,row], "BTCUSDT", START, START+60000)
    assert frozen_specs()[0]["duration_days"] == 90


def test_due_funding_missing_blocks_entire_minute_and_late_restart_fails(tmp_path, monkeypatch):
    import asyncio
    from app.paper import worker
    from types import SimpleNamespace
    _, db, _ = journal(tmp_path)
    spec, filters = frozen_specs()
    spec = {**spec, "symbols": ["BTCUSDT"]}
    history = sources()
    price = {"filterType": "PRICE_FILTER", "tickSize": "0.1", "minPrice": "0", "maxPrice": "0"}
    row = db.execute("SELECT * FROM run").fetchone()
    payload = {**store.checked(row), "spec": spec, "filters": filters, "code_hash": "b"*64,
               "price_filters": {"BTCUSDT": price}, "next_funding_initial": {"BTCUSDT": START},
               "history_origins": {"BTCUSDT": {tf: next(iter(history[tf].values())).history_origin for tf in history}}}
    with db:
        db.execute("UPDATE run SET payload=?,hash=?", (json.dumps(payload), worker.canonical_hash(payload)))
    monkeypatch.setattr(worker, "frozen_specs", lambda: (spec,filters))
    monkeypatch.setattr(worker, "implementation_hash", lambda: "b"*64)
    monkeypatch.setattr(worker, "now_ms", lambda: START+62000)
    contract = SimpleNamespace(valid=True, checked_at=START, metadata_json={"filters": [price]})
    class FakeSession:
        def __enter__(self): return self
        def __exit__(self,*_): return False
        def get(self,*_): return contract
    monkeypatch.setattr(worker, "Session", FakeSession)
    monkeypatch.setattr(worker, "collector_health", lambda _: {"live":True})
    monkeypatch.setattr(worker, "validate_contract", lambda _: (True,"valid"))
    monkeypatch.setattr(worker, "revision_guard", lambda *_: None)
    class Public:
        server = START+82000
        async def clock(self): return self.server, 0
        async def get(self,path,**_):
            if path.endswith("klines"):
                b = minutes()[0]
                return [[b.open_time,*map(str,(b.open,b.high,b.low,b.close,b.volume)),b.close_time]]
            if path.endswith("premiumIndex"): return {"symbol":"BTCUSDT","nextFundingTime": START+28_800_000}
            return []
    public = Public()
    public.server = START+62000
    assert asyncio.run(worker.tick(db, public)) is True
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    public.server = START+82000
    with pytest.raises(RuntimeError, match="settlement"):
        asyncio.run(worker.tick(db, public))
    assert db.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    public.server = START+180001
    with pytest.raises(ValueError, match="gap"):
        asyncio.run(worker.tick(db, public))
    # Persisted policy/code mismatch freezes before any public observation.
    public.server = START+82000
    monkeypatch.setattr(worker, "implementation_hash", lambda: "c"*64)
    with pytest.raises(ValueError, match="changed"):
        asyncio.run(worker.tick(db, public))
    db.close()
