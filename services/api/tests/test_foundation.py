import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base, get_session
from app.main import app
from app.models import WatchlistItem

API_ROOT = Path(__file__).resolve().parents[1]
AUTH = {"Authorization": "Bearer mv-local-preview-only"}


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with session_factory() as session:
        session.add_all([WatchlistItem(symbol="BTCUSDT", sort_order=0), WatchlistItem(symbol="ETHUSDT", sort_order=1)])
        session.commit()

    def sessions():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def test_private_configuration_requires_credentials(client):
    assert client.get("/v1/watchlist").status_code == 401
    assert client.put("/v1/watchlist", json={"symbols": ["SOLUSDT"]}).status_code == 401
    assert client.get("/v1/strategy", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert client.get("/v1/analytics/performance").status_code == 401


def test_empty_analytics_are_private_read_only_and_do_not_create_signals(client):
    before = client.get("/v1/signals", headers=AUTH).json()["signals"]
    result = client.get("/v1/analytics/performance", headers=AUTH)
    assert result.status_code == 200
    payload = result.json()
    assert payload["strategy"] == "MV-TREND-DUAL-v4"
    assert payload["overall"]["signals"] == 0
    assert len(payload["cohorts"]) == 4
    assert client.get("/v1/analytics/outcomes", headers=AUTH).json()["outcomes"] == []
    assert client.get("/v1/signals", headers=AUTH).json()["signals"] == before


def test_watchlist_saved_across_requests_and_order_preserved(client):
    assert client.put("/v1/watchlist", headers=AUTH, json={"symbols": ["ETHUSDT", "BTCUSDT", "SOLUSDT"]}).status_code == 200
    result = client.get("/v1/watchlist", headers=AUTH).json()
    assert result["symbols"] == ["ETHUSDT", "BTCUSDT", "SOLUSDT"]
    assert result["monitoring"] is False
    assert result["exchange_validation"] == "per-market-status"


def test_thirty_symbol_limit_accepts_ordered_markets_without_creating_signals(client):
    symbols=[f"COIN{i}USDT" for i in range(30)]
    assert client.put("/v1/watchlist",headers=AUTH,json={"symbols":symbols}).status_code==200
    assert client.get("/v1/watchlist",headers=AUTH).json()["symbols"]==symbols
    assert client.get("/v1/signals",headers=AUTH).json()["signals"]==[]


@pytest.mark.parametrize("symbols", [[], ["BTCUSDT", "BTCUSDT"], ["btcUSDT"], ["ETH/USDT"], ["BTCUSDT; DROP TABLE watchlist"], [f"COIN{i}USDT" for i in range(31)]])
def test_invalid_configuration_does_not_replace_existing_list(client, symbols):
    assert client.put("/v1/watchlist", headers=AUTH, json={"symbols": symbols}).status_code == 422
    assert client.get("/v1/watchlist", headers=AUTH).json()["symbols"] == ["BTCUSDT", "ETHUSDT"]


def test_health_reports_implemented_services_only(client):
    result = client.get("/health").json()
    assert result["database"] == "connected"
    assert result["collector"]["state"] == "not-running"
    assert result["signals"] == "not-running"


def test_strategy_is_versioned_and_ai_cannot_originate_signal(client):
    contract = client.get("/v1/strategy", headers=AUTH).json()
    assert contract["id"] == "MV-TREND-DUAL-v4"
    assert contract["version"] == 4
    assert contract["indicators"] == {"ema_fast": 20, "ema_slow": 50, "sma_trend": 200, "atr_wilder": 14}
    assert set(contract["setups"]) == {"pullback_continuation", "momentum_breakout"}
    assert contract["execution_quality"]["max_spread_bps"] == "10"
    assert contract["anti_chase"]["max_recent_run_atr"] == "2.50"
    assert contract["market_regime"]["btc_15m_timing_veto"] is True
    assert contract["market_regime"]["btc_15m_hard_contradiction_only"] is True
    assert contract["portfolio_safety"]["max_same_direction_signals_per_source_close"] == 2
    assert contract["portfolio_safety"]["directional_circuit_breaker"]["deterioration_threshold_r"] == "0.50"
    assert [row["id"] for row in contract["risk"]["targets"]] == ["TP1", "TP2", "TP3"]
    assert "cannot originate or change" in contract["ai_role"]


def test_0008_migration_backfills_existing_v2_outcome_and_downgrades_cleanly(tmp_path):
    database = tmp_path / "migration-0008.db"
    env = {
        **os.environ,
        "MV_DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "MV_ENVIRONMENT": "local",
    }
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "0007"],
        cwd=API_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = create_engine(env["MV_DATABASE_URL"])
    identity = "a" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO signal_decisions
                (id,symbol,strategy,source_open_time,direction,outcome,reason,
                 updated_at,expires_at,attempts,evidence_json)
                VALUES
                (:id,'BTCUSDT','MV-TREND-DUAL-v2',1,'long','PUBLISHED','fixture',
                 2,3,1,'{}')
                """
            ),
            {"id": identity},
        )
        connection.execute(
            text(
                """
                INSERT INTO signal_plans
                (id,symbol,strategy,created_at,expires_at,plan_json,evidence_json,evidence_hash)
                VALUES
                (:id,'BTCUSDT','MV-TREND-DUAL-v2',2,3,'{}','{}',:hash)
                """
            ),
            {"id": identity, "hash": "b" * 64},
        )
        connection.execute(
            text(
                """
                INSERT INTO signal_outcomes
                (signal_id,symbol,direction,setup_type,trend_regime,published_at,
                 first_observed_minute,last_minute_open_time,entry,stop,target,
                 risk_distance,target_r,frozen_atr,status,terminal_at,conservative_r,
                 mfe_r,mae_r,favorable_050_at,favorable_100_at,favorable_150_at,
                 favorable_200_at,adverse_050_at,adverse_100_at,intrabar_ambiguous,
                 source_revised,observed_bars,updated_at,error_code)
                VALUES
                (:id,'BTCUSDT','long','pullback_continuation','established',2,
                 60000,NULL,'100','98','104','2','2','1','open',NULL,NULL,
                 '0','0',NULL,NULL,NULL,NULL,NULL,NULL,0,0,0,2,NULL)
                """
            ),
            {"id": identity},
        )
    engine.dispose()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = create_engine(env["MV_DATABASE_URL"])
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT strategy,tp1,tp2,tp3,tp1_r,tp2_r,tp3_r "
                "FROM signal_outcomes WHERE signal_id=:id"
            ),
            {"id": identity},
        ).one()
        assert tuple(row) == (
            "MV-TREND-DUAL-v2",
            None,
            None,
            "104",
            None,
            None,
            "2",
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
    engine.dispose()

    subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "0007"],
        cwd=API_ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = create_engine(env["MV_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
        assert connection.scalar(
            text("SELECT target FROM signal_outcomes WHERE signal_id=:id"),
            {"id": identity},
        ) == "104"
    engine.dispose()


def test_foundation_rejects_production_mode():
    with pytest.raises(RuntimeError, match="invite-only"):
        Settings(environment="production").check_local_only()


def test_real_migration_can_upgrade_seed_and_downgrade(tmp_path):
    database = tmp_path / "migration.db"
    env = {**os.environ, "MV_DATABASE_URL": f"sqlite:///{database.as_posix()}", "MV_ENVIRONMENT": "local"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env, check=True, capture_output=True)
    engine = create_engine(env["MV_DATABASE_URL"])
    with engine.connect() as connection:
        assert list(connection.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order))) == ["BTCUSDT", "ETHUSDT"]
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008"
    engine.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=API_ROOT, env=env, check=True, capture_output=True)
    engine = create_engine(env["MV_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sqlite_master WHERE name='watchlist'")) == 0
    engine.dispose()
