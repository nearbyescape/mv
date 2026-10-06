from datetime import datetime, timezone
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class WatchlistItem(Base):
    __tablename__ = "watchlist"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class MarketContract(Base):
    __tablename__ = "market_contracts"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    valid: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[int] = mapped_column(BigInteger)
    metadata_json: Mapped[dict] = mapped_column(JSON)


class Candle(Base):
    __tablename__ = "candles"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    open_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    close_time: Mapped[int] = mapped_column(BigInteger)
    open: Mapped[str] = mapped_column(String(80))
    high: Mapped[str] = mapped_column(String(80))
    low: Mapped[str] = mapped_column(String(80))
    close: Mapped[str] = mapped_column(String(80))
    volume: Mapped[str] = mapped_column(String(80))
    source_hash: Mapped[str] = mapped_column(String(64))


class IndicatorSnapshot(Base):
    __tablename__ = "indicator_snapshots"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    open_time: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ema20: Mapped[str | None] = mapped_column(String(80))
    ema50: Mapped[str | None] = mapped_column(String(80))
    sma200: Mapped[str | None] = mapped_column(String(80))
    atr: Mapped[str | None] = mapped_column(String(80))
    lineage: Mapped[str] = mapped_column(String(64))


class IndicatorCheckpoint(Base):
    __tablename__ = "indicator_checkpoints"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(4), primary_key=True)
    state_json: Mapped[dict] = mapped_column(JSON)


class CollectorStatus(Base):
    __tablename__ = "collector_status"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    state: Mapped[str] = mapped_column(String(30))
    updated_at: Mapped[int] = mapped_column(BigInteger)
    last_event_at: Mapped[int | None] = mapped_column(BigInteger)
    clock_offset_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    reconnects: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class EngineStatus(Base):
    __tablename__ = "engine_status"
    id: Mapped[str] = mapped_column(String(30), primary_key=True)
    state: Mapped[str] = mapped_column(String(30))
    updated_at: Mapped[int] = mapped_column(BigInteger)
    last_decision_at: Mapped[int | None] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text)


class EngineCursor(Base):
    __tablename__ = "engine_cursors"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_open_time: Mapped[int] = mapped_column(BigInteger)
    initialized_at: Mapped[int] = mapped_column(BigInteger)


class SignalDecision(Base):
    __tablename__ = "signal_decisions"
    __table_args__ = (UniqueConstraint("symbol", "strategy", "source_open_time", name="uq_decision_source"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    strategy: Mapped[str] = mapped_column(String(80))
    source_open_time: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str | None] = mapped_column(String(8))
    outcome: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    evidence_json: Mapped[dict] = mapped_column(JSON)


class SignalPlan(Base):
    __tablename__ = "signal_plans"
    id: Mapped[str] = mapped_column(ForeignKey("signal_decisions.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    strategy: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    plan_json: Mapped[dict] = mapped_column(JSON)
    evidence_json: Mapped[dict] = mapped_column(JSON)
    evidence_hash: Mapped[str] = mapped_column(String(64))


class SignalSlot(Base):
    __tablename__ = "signal_slots"
    symbol: Mapped[str] = mapped_column(String(30), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(80), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), unique=True)
    state: Mapped[str] = mapped_column(String(12))  # reserved setup or operator-reported held position


class SignalEvent(Base):
    __tablename__ = "signal_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[int] = mapped_column(BigInteger)
    payload_json: Mapped[dict] = mapped_column(JSON)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(12))
    password_hash: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[int] = mapped_column(BigInteger)


class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    revoked_at: Mapped[int | None] = mapped_column(BigInteger)


class Invite(Base):
    __tablename__ = "invites"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[str] = mapped_column(String(12))
    created_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger)
    used_at: Mapped[int | None] = mapped_column(BigInteger)
    created_by: Mapped[str | None] = mapped_column(String(36))


class AuthThrottle(Base):
    __tablename__ = "auth_throttles"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    window_at: Mapped[int] = mapped_column(BigInteger)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(String(36))
    action: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)
    detail_json: Mapped[dict] = mapped_column(JSON)


class WebNotification(Base):
    __tablename__ = "web_notifications"
    id: Mapped[str] = mapped_column(ForeignKey("signal_events.id"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), index=True)
    type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)


class NotificationRead(Base):
    __tablename__ = "notification_reads"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    notification_id: Mapped[str] = mapped_column(ForeignKey("web_notifications.id"), primary_key=True)
    read_at: Mapped[int] = mapped_column(BigInteger)


class ServiceLease(Base):
    __tablename__ = "service_leases"
    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36))
    heartbeat: Mapped[int] = mapped_column(BigInteger)


class AIReview(Base):
    __tablename__ = "ai_reviews"
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), primary_key=True)
    evidence_hash: Mapped[str] = mapped_column(String(64))
    plan_hash: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[int] = mapped_column(BigInteger)
    completed_at: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(60))
    response_json: Mapped[dict | None] = mapped_column(JSON)


class AIRequest(Base):
    __tablename__ = "ai_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str | None] = mapped_column(ForeignKey("signal_plans.id"), index=True)
    started_at: Mapped[int] = mapped_column(BigInteger, index=True)
    completed_at: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20))
    usage_json: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(60))


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    setup_type: Mapped[str] = mapped_column(String(40))
    trend_regime: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[int] = mapped_column(BigInteger, index=True)
    first_observed_minute: Mapped[int] = mapped_column(BigInteger)
    last_minute_open_time: Mapped[int | None] = mapped_column(BigInteger)
    entry: Mapped[str] = mapped_column(String(80))
    stop: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(80))
    risk_distance: Mapped[str] = mapped_column(String(80))
    frozen_atr: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(24), index=True)
    terminal_at: Mapped[int | None] = mapped_column(BigInteger)
    conservative_r: Mapped[str | None] = mapped_column(String(80))
    mfe_r: Mapped[str] = mapped_column(String(80), default="0")
    mae_r: Mapped[str] = mapped_column(String(80), default="0")
    favorable_050_at: Mapped[int | None] = mapped_column(BigInteger)
    favorable_100_at: Mapped[int | None] = mapped_column(BigInteger)
    favorable_150_at: Mapped[int | None] = mapped_column(BigInteger)
    favorable_200_at: Mapped[int | None] = mapped_column(BigInteger)
    adverse_050_at: Mapped[int | None] = mapped_column(BigInteger)
    adverse_100_at: Mapped[int | None] = mapped_column(BigInteger)
    intrabar_ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    source_revised: Mapped[bool] = mapped_column(Boolean, default=False)
    observed_bars: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[int] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(80))


class DecisionOpportunity(Base):
    __tablename__ = "decision_opportunities"
    decision_id: Mapped[str] = mapped_column(ForeignKey("signal_decisions.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(String(100), index=True)
    direction: Mapped[str | None] = mapped_column(String(8))
    source_open_time: Mapped[int] = mapped_column(BigInteger)
    observed_from: Mapped[int] = mapped_column(BigInteger)
    observed_until: Mapped[int] = mapped_column(BigInteger)
    anchor_close: Mapped[str] = mapped_column(String(80))
    frozen_atr: Mapped[str] = mapped_column(String(80))
    max_up_atr: Mapped[str] = mapped_column(String(80), default="0")
    max_down_atr: Mapped[str] = mapped_column(String(80), default="0")
    observed_bars: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), index=True)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class TelegramDelivery(Base):
    __tablename__ = "telegram_deliveries"
    event_id: Mapped[str] = mapped_column(ForeignKey("signal_events.id"), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("signal_plans.id"), index=True)
    chat_id: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[int] = mapped_column(BigInteger)
    claimed_at: Mapped[int | None] = mapped_column(BigInteger)
    sent_at: Mapped[int | None] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(60))
    payload_json: Mapped[dict] = mapped_column(JSON)
    payload_hash: Mapped[str] = mapped_column(String(64))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    plan_hash: Mapped[str] = mapped_column(String(64))
