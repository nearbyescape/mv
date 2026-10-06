import asyncio
import json
import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.market.collector import Collector, frames_for_symbol
from app.market import collector as collector_module
from app.market.store import apply_bars
from app.models import Candle, IndicatorCheckpoint
from test_indicators import bars, replay


def test_only_btc_collects_15m_timing_stream():
    assert frames_for_symbol("BTCUSDT") == ("15m", "1h", "4h")
    assert frames_for_symbol("ETHUSDT") == ("1h", "4h")


def test_paginated_reconciliation_repairs_more_than_1000_missed_bars(monkeypatch):
    source = bars(1600)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(collector_module, "Session", sessions)
    with sessions.begin() as session:
        apply_bars(session, "BTCUSDT", "1h", source[:500], source[-1].close_time + 1)
    calls = []
    class FakePublic:
        async def klines(self, symbol, timeframe, *, start_time, end_time, limit):
            calls.append((start_time, limit))
            return [bar for bar in source if bar.open_time >= start_time and bar.close_time <= end_time][:limit]
    asyncio.run(Collector(FakePublic()).sync_stream("BTCUSDT", "1h", source[-1].close_time + 1))
    assert [limit for _, limit in calls] == [1000, 103]
    with sessions() as session:
        assert session.get(IndicatorCheckpoint, ("BTCUSDT", "1h")).state_json == replay(source)[0].dump()
    engine.dispose()


@pytest.mark.parametrize("delay", [0, 6001])
def test_stream_finalization_uses_exchange_event_boundary_and_rejects_stale_events(monkeypatch, delay):
    source = bars(501)
    bar = source[-1]
    event_time = bar.close_time + 1
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(collector_module, "Session", sessions)
    monkeypatch.setattr(collector_module, "selected_symbols", lambda: ["BTCUSDT"])
    monkeypatch.setattr(collector_module, "now_ms", lambda: event_time - 2 + delay)
    with sessions.begin() as session:
        apply_bars(session, "BTCUSDT", "1h", source[:500], event_time)
    message = {"e": "kline", "E": event_time, "s": "BTCUSDT", "k": {"s": "BTCUSDT", "i": "1h", "t": bar.open_time, "T": bar.close_time, "o": str(bar.open), "h": str(bar.high), "l": str(bar.low), "c": str(bar.close), "v": str(bar.volume), "x": True}}
    class FakeSocket:
        called = False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def recv(self):
            if self.called:
                raise RuntimeError("Test stream ended")
            self.called = True
            return json.dumps({"stream": "btcusdt@kline_1h", "data": message})
    def fake_connect(address, **kwargs):
        assert address.startswith("wss://fstream.binance.com/market/stream?streams=")
        return FakeSocket()
    monkeypatch.setattr(collector_module, "connect", fake_connect)
    with pytest.raises((ValueError, RuntimeError), match="freshness tolerance" if delay else "Test stream ended"):
        asyncio.run(Collector(None).stream(["BTCUSDT"]))
    with sessions() as session:
        state = session.get(IndicatorCheckpoint, ("BTCUSDT", "1h")).state_json
        assert state["count"] == (500 if delay else 501)
        assert state == replay(source[:state["count"]])[0].dump()
    engine.dispose()


def test_reconciliation_repairs_an_old_missing_source_bar(monkeypatch):
    source = bars(500)
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(collector_module, "Session", sessions)
    with sessions.begin() as session:
        expected = apply_bars(session, "BTCUSDT", "1h", source, source[-1].close_time + 1).dump()
        session.execute(delete(Candle).where(Candle.open_time == source[100].open_time))
    class FakePublic:
        async def klines(self, symbol, timeframe, *, start_time, end_time, limit):
            assert start_time == source[99].open_time
            return [bar for bar in source if bar.open_time >= start_time and bar.close_time <= end_time][:limit]
    asyncio.run(Collector(FakePublic()).sync_stream("BTCUSDT", "1h", source[-1].close_time + 1))
    with sessions() as session:
        assert session.get(IndicatorCheckpoint, ("BTCUSDT", "1h")).state_json == expected
        assert len(list(session.scalars(select(Candle)))) == 500
    engine.dispose()


@pytest.mark.parametrize("rate_limited",[False,True])
def test_slow_rest_reconciliation_keeps_receiving_final_candles_and_cleans_up(monkeypatch,rate_limited):
    from app.market.binance import RateLimited
    source=bars(501)
    bar=source[-1]
    event_time=bar.close_time+1
    engine=create_engine("sqlite://",poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine)
    monkeypatch.setattr(collector_module,"Session",sessions)
    monkeypatch.setattr(collector_module,"selected_symbols",lambda:["BTCUSDT"])
    monkeypatch.setattr(collector_module,"now_ms",lambda:event_time)
    with sessions.begin() as session:
        apply_bars(session,"BTCUSDT","1h",source[:500],event_time)
    message={"e":"kline","E":event_time,"s":"BTCUSDT","k":{"s":"BTCUSDT","i":"1h","t":bar.open_time,"T":bar.close_time,"o":str(bar.open),"h":str(bar.high),"l":str(bar.low),"c":str(bar.close),"v":str(bar.volume),"x":False}}
    observations=[]
    async def exercise():
        started=asyncio.Event()
        never_finishes=asyncio.Event()
        collector=Collector(None)
        collector.reconcile_interval=0
        async def reconcile():
            started.set()
            if rate_limited:
                raise RateLimited(90)
            try:
                await never_finishes.wait()
            finally:
                observations.append("cancelled")
        collector.reconcile=reconcile
        class Socket:
            count=0
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def recv(self):
                self.count+=1
                if self.count==1:return json.dumps(message)
                await started.wait()
                await asyncio.sleep(0)
                if self.count==2:
                    message["k"]["x"]=True
                    return json.dumps(message)
                with sessions() as session:
                    assert session.get(IndicatorCheckpoint,("BTCUSDT","1h")).state_json==replay(source)[0].dump()
                raise RuntimeError("Test stream ended during pending REST")
        monkeypatch.setattr(collector_module,"connect",lambda *a,**k:Socket())
        with pytest.raises(RateLimited if rate_limited else RuntimeError) as error:
            await collector.stream(["BTCUSDT"])
        if rate_limited:assert error.value.retry_after==90
        else:assert observations==["cancelled"]
    asyncio.run(exercise())
    engine.dispose()
