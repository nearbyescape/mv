"""MV operational hardening: tested schema compatibility, auth and no-send behavior."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_session
from app.main import app
from app.market.binance import now_ms
from app.models import SignalDecision
from app.operations.readiness import (
    SCHEMA_LEGACY, SCHEMA_V7_COMPLETE,
    validate_production_schema, build_diagnostics,
)

TOKEN = {"Authorization": "Bearer mv-local-preview-only"}


@pytest.fixture
def local_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def client(local_session):
    def sessions():
        with local_session() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    try:
        with TestClient(app) as item:
            yield item
    finally:
        app.dependency_overrides.clear()


def test_production_supports_only_0008_or_complete_0010():
    assert validate_production_schema("0008") == SCHEMA_LEGACY
    assert validate_production_schema("0010") == SCHEMA_V7_COMPLETE
    for invalid in (None, "", "0007", "0009", "0011", "head"):
        with pytest.raises(RuntimeError, match="Unsupported or incomplete"):
            validate_production_schema(invalid)


@pytest.mark.parametrize("schema,status",[
    ("0008", 200), ("0010", 200), ("0009", 503),
])
def test_production_health_supports_fully_migrated_adapter_but_rejects_half_upgrade(
    client, local_session, schema, status,
):
    with local_session.begin() as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        session.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": schema})
    # /health does NOT depend on bearer access, only on DB/schema status.
    with patch("app.main.get_settings", return_value=SimpleNamespace(
        environment="production",
    )):
        result = client.get("/health")
    assert result.status_code == status
    assert result.json()["status"] == "ok" if status == 200 else (
        result.json()["detail"] == "Database unavailable or migrations pending"
    )


def test_read_only_diagnostics_requires_auth_and_preserves_rows(client, local_session):
    assert client.get("/v1/operations/diagnostics").status_code == 401
    now = now_ms()
    with local_session.begin() as s:
        s.add_all([
            SignalDecision(
                id="a"*64, symbol="BTCUSDT", strategy="MV-TREND-DUAL-v4",
                source_open_time=now-3_600_000, direction="short",
                outcome="NO_SETUP", reason="NO_PULLBACK_OR_BREAKOUT_TRIGGER",
                updated_at=now-1000, expires_at=now+1000,
                attempts=1, evidence_json={},
            ),
            SignalDecision(
                id="b"*64, symbol="ETHUSDT", strategy="MV-TREND-DUAL-v4",
                source_open_time=now-3_600_000, direction="long",
                outcome="NO_SETUP", reason="NO_PULLBACK_OR_BREAKOUT_TRIGGER",
                updated_at=now-2000, expires_at=now+1000,
                attempts=1, evidence_json={},
            ),
            SignalDecision(
                id="c"*64, symbol="SOLUSDT", strategy="MV-TREND-DUAL-v3",
                source_open_time=now-3_600_000, direction="long",
                outcome="PUBLISHED", reason="QUALIFIED",
                updated_at=now-2000, expires_at=now+1000,
                attempts=1, evidence_json={},
            ),
        ])
    response=client.get("/v1/operations/diagnostics", headers=TOKEN)
    assert response.status_code == 200, response.text
    observed=response.json()
    assert observed["status"]=="OBSERVATION_ONLY_NOT_TRADING_AUTHORIZATION"
    assert observed["database_revision"]=="local-unverified"
    assert observed["legacy_last_24h_decisions"]==2
    assert observed["legacy_outcome_counts"]=={"NO_SETUP":2}
    assert observed["legacy_top_rejection_reasons"]==[
        {"reason":"NO_PULLBACK_OR_BREAKOUT_TRIGGER","count":2},
    ]
    assert observed["v7_publication_authorized"] is False
    assert observed["v7_paper"]["database_tables_available"] is True
    assert observed["sent_telegram"] is False
    assert observed["submitted_exchange_orders"] is False
    assert observed["performed_database_mutation"] is False
    with local_session() as session:
        assert list(session.scalars(select(SignalDecision.id).order_by(
            SignalDecision.id
        ))) == ["a"*64, "b"*64, "c"*64]


def test_diagnostics_after_legacy_database_revision_never_claims_v7_tables(local_session):
    now=now_ms()
    with local_session.begin() as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        session.execute(text("INSERT INTO alembic_version VALUES ('0008')"))
    # Simulate a production-like revision without a need to actually use
    # PostgreSQL. No V7 ORM SELECT may be executed in this path.
    with local_session() as session:
        view=build_diagnostics(session, production=True)
    assert view["migration_status"]=="v4-only"
    assert view["v7_paper"]["database_tables_available"] is False
    assert view["v7_paper"]["cycle_states"] is None
    assert view["v7_publication_authorized"] is False
