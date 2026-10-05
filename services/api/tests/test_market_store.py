from dataclasses import replace
from decimal import Decimal
import time

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from mv_strategy import INTERVAL_MS
from app.database import Base
from app.market.store import apply_bars, confirmation_at
from app.market.views import market_view
from app.models import Candle, CollectorStatus, IndicatorCheckpoint, IndicatorSnapshot, MarketContract
from test_indicators import bars, replay


@pytest.fixture
def sessions():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()


def test_rest_duplicates_and_restart_do_not_reseed(sessions):
    source = bars()
    with sessions.begin() as session:
        first = apply_bars(session, "BTCUSDT", "1h", source[:500], source[-1].close_time + 1).dump()
    with sessions.begin() as session:
        assert apply_bars(session, "BTCUSDT", "1h", source[497:500], source[-1].close_time + 1).dump() == first
        actual = apply_bars(session, "BTCUSDT", "1h", source[498:], source[-1].close_time + 1)
        assert actual.dump() == replay(source)[0].dump()
        assert session.scalar(select(func.count()).select_from(Candle)) == 510


def test_final_bar_correction_rebuilds_recursive_values_from_original_origin(sessions):
    source = bars(500)
    with sessions.begin() as session:
        original = apply_bars(session, "BTCUSDT", "1h", source, source[-1].close_time + 1).dump()
    corrected = replace(source[200], close=source[200].close + Decimal("0.5"))
    source[200] = corrected
    with sessions.begin() as session:
        actual = apply_bars(session, "BTCUSDT", "1h", [corrected], source[-1].close_time + 1).dump()
        assert actual == replay(source)[0].dump()
        assert actual["history_origin"] == original["history_origin"]
        assert actual["lineage"] != original["lineage"]
        assert session.scalar(select(func.count()).select_from(IndicatorSnapshot)) == 500


def test_gap_failure_rolls_back_candles_and_checkpoint_then_repair_succeeds(sessions):
    source = bars(502)
    with sessions.begin() as session:
        before = apply_bars(session, "BTCUSDT", "1h", source[:500], source[-1].close_time + 1).dump()
    with pytest.raises(ValueError, match="Non-contiguous"):
        with sessions.begin() as session:
            apply_bars(session, "BTCUSDT", "1h", [source[501]], source[-1].close_time + 1)
    with sessions() as session:
        assert session.get(IndicatorCheckpoint, ("BTCUSDT", "1h")).state_json == before
        assert session.get(Candle, ("BTCUSDT", "1h", source[501].open_time)) is None
    with sessions.begin() as session:
        assert apply_bars(session, "BTCUSDT", "1h", source[499:], source[-1].close_time + 1).dump() == replay(source)[0].dump()


def test_partial_candle_is_not_committed(sessions):
    with pytest.raises(ValueError, match="completed"):
        with sessions.begin() as session:
            apply_bars(session, "BTCUSDT", "1h", bars(1), 100)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Candle)) == 0


def test_missing_expected_4h_confirmation_blocks_instead_of_using_an_older_bar(sessions):
    source = bars(501, "4h")
    with sessions.begin() as session:
        apply_bars(session, "BTCUSDT", "4h", source[:500], source[-1].close_time + 1)
        assert confirmation_at(session, "BTCUSDT", 500 * INTERVAL_MS["4h"]) is not None
        assert confirmation_at(session, "BTCUSDT", 501 * INTERVAL_MS["4h"]) is None


def test_readiness_requires_live_heartbeat_completed_latest_bar_and_500_warmup(sessions):
    now = int(time.time() * 1000)
    step = INTERVAL_MS["1h"]
    end = now // step * step
    source = [replace(bar, open_time=end - (500 - i) * step, close_time=end - (499 - i) * step - 1) for i, bar in enumerate(bars(500))]
    with sessions.begin() as session:
        session.add(MarketContract(symbol="BTCUSDT", valid=True, reason="test", checked_at=now, metadata_json={}))
        session.add(CollectorStatus(id="collector", state="streaming", updated_at=now, last_event_at=now, clock_offset_ms=0, reconnects=0))
        apply_bars(session, "BTCUSDT", "1h", source, now)
        paired_step = INTERVAL_MS["4h"]
        paired_end = now // paired_step * paired_step
        paired = [replace(bar, open_time=paired_end - (500 - i) * paired_step, close_time=paired_end - (499 - i) * paired_step - 1) for i, bar in enumerate(bars(500, "4h"))]
        apply_bars(session, "BTCUSDT", "4h", paired, now)
    with sessions.begin() as session:
        result = market_view(session, "BTCUSDT", "1h")
        assert result["ready"] is True
        assert isinstance(result["series"]["candles"][-1]["close"], str)
        assert result["signal_generation"] is False
        paired_checkpoint = session.get(IndicatorCheckpoint, ("BTCUSDT", "4h"))
        paired_checkpoint.state_json = {**paired_checkpoint.state_json, "count": 499}
        session.flush()
        assert market_view(session, "BTCUSDT", "1h")["status"] == "warming-up"
        heartbeat = session.get(CollectorStatus, "collector")
        heartbeat.last_event_at = now - 60_000
        paired_checkpoint.state_json = {**paired_checkpoint.state_json, "count": 500}
    with sessions() as session:
        assert market_view(session, "BTCUSDT", "1h")["status"] == "stale"
