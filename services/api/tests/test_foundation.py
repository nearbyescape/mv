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
    assert contract["id"] == "MV-TREND-DUAL-v2"
    assert contract["version"] == 2
    assert contract["indicators"] == {"ema_fast": 20, "ema_slow": 50, "sma_trend": 200, "atr_wilder": 14}
    assert set(contract["setups"]) == {"pullback_continuation", "momentum_breakout"}
    assert contract["execution_quality"]["max_spread_bps"] == "10"
    assert "cannot originate or change" in contract["ai_role"]


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
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0007"
    engine.dispose()
    subprocess.run([sys.executable, "-m", "alembic", "downgrade", "base"], cwd=API_ROOT, env=env, check=True, capture_output=True)
    engine = create_engine(env["MV_DATABASE_URL"])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sqlite_master WHERE name='watchlist'")) == 0
    engine.dispose()
