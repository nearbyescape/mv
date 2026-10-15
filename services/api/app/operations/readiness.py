"""Authenticated, read-only MV operational diagnostics.

This module observes persisted data. It cannot enable an engine, certify a
trading strategy, create a candidate, stage a Telegram message, or call a broker.
The V7Sonic tables remain private paper evidence, NOT active client signals.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.market.binance import now_ms
from app.market.views import collector_health
from app.models import (
    SignalDecision, TelegramDelivery, V7ClientDelivery,
    V7DecisionCycle, V7DecisionRecord,
)
from app.signals.service import STRATEGY_ID as LEGACY_STRATEGY, engine_health

SCHEMA_LEGACY = "0008"
SCHEMA_V7_COMPLETE = "0010"
ALLOWED_PRODUCTION_REVISIONS = frozenset((SCHEMA_LEGACY, SCHEMA_V7_COMPLETE))


def validate_production_schema(revision: str | None) -> str:
    """Never declare an intermediate 0009 migration deployable."""
    if revision not in ALLOWED_PRODUCTION_REVISIONS:
        raise RuntimeError("Unsupported or incomplete production database revision")
    return revision


def database_revision(session: Session, *, production: bool) -> str:
    if production:
        revision = session.scalar(text("SELECT version_num FROM alembic_version"))
        return validate_production_schema(revision)
    # SQLite fixture schemas are sometimes created with metadata.create_all
    # rather than migrations. Never assert a migration number for those.
    return "local-unverified"


def _status_counts(session: Session, model, key, *, condition=None) -> dict[str, int]:
    query = select(key, func.count()).select_from(model)
    if condition is not None:
        query = query.where(condition)
    query = query.group_by(key)
    return {
        str(name): int(count) for name, count in session.execute(query)
    }


def build_diagnostics(session: Session, *, production: bool) -> dict:
    """A bounded, authorization-required view of *observed* engine behavior.

    Does not assert that a currently stopped worker is running simply
    because historical decisions or rows exist.
    """
    revision = database_revision(session, production=production)
    now = now_ms()
    since = now - 24 * 3_600_000
    collector = collector_health(session)
    engine = engine_health(session)

    decisions_query = (
        select(SignalDecision.reason, SignalDecision.outcome, func.count())
        .where(
            SignalDecision.strategy == LEGACY_STRATEGY,
            SignalDecision.updated_at >= since,
            SignalDecision.updated_at <= now,
        )
        .group_by(SignalDecision.reason, SignalDecision.outcome)
    )
    reason_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    for reason, outcome, count in session.execute(decisions_query):
        reason_counts[str(reason)] += int(count)
        outcome_counts[str(outcome)] += int(count)

    legacy_delivery = _status_counts(session, TelegramDelivery, TelegramDelivery.status)
    v7_available = (
        revision == SCHEMA_V7_COMPLETE if production else
        session.get_bind().dialect.name == "sqlite"
    )
    if v7_available:
        v7_cycles = _status_counts(session, V7DecisionCycle, V7DecisionCycle.state)
        v7_decisions = _status_counts(
            session, V7DecisionRecord, V7DecisionRecord.outcome
        )
        v7_delivery = _status_counts(
            session, V7ClientDelivery, V7ClientDelivery.status
        )
    else:
        v7_cycles = v7_decisions = v7_delivery = None

    # This is release qualification, not collector or website uptime.
    # Even a green API and collector cannot imply economic validation.
    blockers = [
        "NO_INDEPENDENT_POSITIVE_AFTER_COST_STRATEGY_EVIDENCE",
        "V7_AUTOMATED_RELEASE_CERTIFICATION_PRODUCER_NOT_IMPLEMENTED",
        "V7_CLIENT_PUBLISHER_NOT_DEPLOYED",
        "NO_PROSPECTIVE_LIVE_FILL_AND_LATENCY_CERTIFICATION",
    ]
    if revision != SCHEMA_V7_COMPLETE:
        blockers.append("V7_SCHEMA_NOT_VERIFIED_IN_PRODUCTION")

    return {
        "status": "OBSERVATION_ONLY_NOT_TRADING_AUTHORIZATION",
        "as_of_ms": now,
        "window_hours": 24,
        "database_revision": revision,
        "migration_status": (
            "v7-tables-complete" if revision == SCHEMA_V7_COMPLETE else
            "v4-only" if revision == SCHEMA_LEGACY else
            "local-unverified"
        ),
        "market_collector": {
            "state": collector["state"],
            "live": collector["live"],
            "last_event_at": collector["last_event_at"],
            "clock_offset_ms": collector["clock_offset_ms"],
        },
        "legacy_engine": {
            "strategy": LEGACY_STRATEGY,
            "state": engine["state"],
            "running": engine["running"],
            "ready": engine["ready"],
            "last_decision_at": engine["last_decision_at"],
        },
        "legacy_last_24h_decisions": sum(outcome_counts.values()),
        "legacy_outcome_counts": dict(sorted(outcome_counts.items())),
        "legacy_top_rejection_reasons": [
            {"reason": reason, "count": count}
            for reason, count in sorted(
                reason_counts.items(), key=lambda x: (-x[1], x[0])
            )[:12]
        ],
        "legacy_telegram_delivery_status": dict(sorted(legacy_delivery.items())),
        "v7_paper": {
            "database_tables_available": v7_available,
            "cycle_states": v7_cycles,
            "outcomes": v7_decisions,
            "historical_client_delivery_rows": v7_delivery,
            "rows_authorize_republishing": False,
        },
        "v7_publication_authorized": False,
        "v7_release_blockers": blockers,
        "automatic_exchange_orders_supported": False,
        "performed_database_mutation": False,
        "sent_telegram": False,
        "submitted_exchange_orders": False,
    }
