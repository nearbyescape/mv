"""Daily Telegram report: time-window, exact accounting and safe delivery tests."""
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SignalOutcome, TelegramDailyReport
from app.telegram.daily_report import (
    IST, STRATEGY, boundaries, build_payload, due_session, finish, prepare,
    recover_interrupted, render_report,
)
from app.telegram.provider import DeliveryError


def ms(day, hour, minute=0):
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST).timestamp() * 1000)


def synthetic_db():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def outcome(key, day, hour, status, result, terminal_day=None, terminal_hour=21):
    published_at = ms(day, hour)
    terminal_at = ms(terminal_day or day, terminal_hour) if status != "open" else None
    return SignalOutcome(
        signal_id=str(key) * 64, strategy=STRATEGY,
        symbol=f"{key}USDT", direction="short",
        setup_type="pullback_continuation", trend_regime="emerging",
        published_at=published_at, first_observed_minute=published_at + 60000,
        last_minute_open_time=None, entry="10", stop="11", target="8",
        tp1="9", tp2="8.5", tp3="8",
        risk_distance="1", target_r="2", tp1_r="1",
        tp2_r="1.5", tp3_r="2", frozen_atr="0.5",
        status=status, terminal_at=terminal_at, conservative_r=result,
        mfe_r="0", mae_r="0", favorable_050_at=None,
        favorable_100_at=None, favorable_150_at=None,
        favorable_200_at=None, adverse_050_at=None, adverse_100_at=None,
        intrabar_ambiguous=False, source_revised=False,
        observed_bars=12, updated_at=published_at, error_code=None,
    )


SETTINGS = SimpleNamespace(
    telegram_chat_id="-100123456789",
    daily_report_start_at=ms(date(2026, 10, 8), 0),
)


def test_due_session_exact_ist_boundary_and_no_midnight_reset():
    day = date(2026, 10, 8)
    assert due_session(ms(day, 23, 9))[0] == day - timedelta(days=1)
    assert due_session(ms(day, 23, 10))[0] == day
    assert due_session(ms(day + timedelta(days=1), 0, 1))[0] == day
    assert boundaries(day)[1] == ms(day, 9)
    assert boundaries(day)[2] == ms(day, 23)


def test_report_counts_publications_and_keeps_carryover_out_of_total():
    engine, sessions = synthetic_db()
    today = date(2026, 10, 8)
    yesterday = today - timedelta(days=1)
    try:
        with sessions.begin() as session:
            session.add_all([
                outcome("A", today, 9, "tp3", "1.55"),
                outcome("B", today, 10, "protected_be", ".30"),
                outcome("C", today, 11, "stop", "-1"),
                outcome("D", today, 12, "open", None),
                outcome("E", yesterday, 22, "protected_tp1", "1.15", today),
            ])
        with sessions() as session:
            text = render_report(session, today)
            payload = build_payload(session, today, SETTINGS.telegram_chat_id)
            assert "<b>📊 MV SIGNAL" in text
            assert "✅ TP3 HIT" in text and "❌ Stop-loss" in text
            assert "🛡️ TP1 ✅ · TP2 ❌ · TP3 ❌" in text
            assert "Total signals: <b>4</b>" in text
            assert "Positive resolved outcomes: <b>2/3</b>" in text
            assert "Resolved reference total: <b>+0.850R</b>" in text
            assert "Still open: <b>1</b>" in text
            assert "CARRYOVER RESOLVED TODAY" in text
            assert "E/USDT" in text
            assert payload["parse_mode"] == "HTML"
            assert "http" not in text and "mv.jaleshwarima.com" not in text
            assert "inline_keyboard" not in payload
    finally:
        engine.dispose()


def test_report_is_not_automatically_sent_before_activation_or_before_2310():
    engine, sessions = synthetic_db()
    day = date(2026, 10, 8)
    try:
        settings = SimpleNamespace(
            telegram_chat_id=SETTINGS.telegram_chat_id,
            daily_report_start_at=ms(day, 23, 10),
        )
        with sessions.begin() as session:
            assert prepare(session, ms(day, 23, 9), settings) is None
        with sessions() as session:
            assert list(session.scalars(select(TelegramDailyReport))) == []
        with sessions.begin() as session:
            assert prepare(session, ms(day, 23, 10), settings) is not None
    finally:
        engine.dispose()


def test_one_report_per_day_fenced_claim_and_received_message_id():
    engine, sessions = synthetic_db()
    day = date(2026, 10, 8)
    now = ms(day, 23, 10)
    try:
        with sessions.begin() as session:
            job = prepare(session, now, SETTINGS)
            assert job is not None
            assert prepare(session, now, SETTINGS) is None
            assert len(job[1]["text"]) <= 4000
            row = session.get(TelegramDailyReport, job[0])
            assert row.status == "inflight" and row.attempts == 1
        with sessions.begin() as session:
            finish(session, job[0], now + 1000, message_id=2345)
            assert prepare(session, now + 2000, SETTINGS) is None
        with sessions() as session:
            row = session.get(TelegramDailyReport, job[0])
            assert row.status == "delivered" and row.message_id == 2345
            assert len(list(session.scalars(select(TelegramDailyReport)))) == 1
    finally:
        engine.dispose()


def test_interrupted_or_ambiguous_send_is_never_retried_automatically():
    engine, sessions = synthetic_db()
    now = ms(date(2026, 10, 8), 23, 10)
    try:
        with sessions.begin() as session:
            job = prepare(session, now, SETTINGS)
        with sessions.begin() as session:
            assert recover_interrupted(session) == 1
            assert prepare(session, now + 100_000, SETTINGS) is None
            assert session.get(TelegramDailyReport, job[0]).status == "unknown"
    finally:
        engine.dispose()


def test_bounded_rate_limit_retry_and_unknown_provider_result():
    engine, sessions = synthetic_db()
    now = ms(date(2026, 10, 8), 23, 10)
    try:
        with sessions.begin() as session:
            job = prepare(session, now, SETTINGS)
            finish(session, job[0], now, error=DeliveryError("RATE_LIMITED", "retry", 30))
            assert session.get(TelegramDailyReport, job[0]).status == "retry"
        with sessions.begin() as session:
            assert prepare(session, now + 10_000, SETTINGS) is None
            second = prepare(session, now + 30_000, SETTINGS)
            assert second is not None
            finish(session, second[0], now + 30_000, error=DeliveryError("DELIVERY_UNCERTAIN", "unknown"))
        with sessions.begin() as session:
            assert prepare(session, now + 200_000, SETTINGS) is None
            assert session.get(TelegramDailyReport, job[0]).status == "unknown"
    finally:
        engine.dispose()


def test_report_length_limit_does_not_send_invalid_truncated_html():
    engine, sessions = synthetic_db()
    day = date(2026, 10, 8)
    try:
        with sessions.begin() as session:
            for i in range(100):
                row = outcome(f"{i:02d}", day, 9, "tp3", "1.55")
                row.signal_id = f"{i:064d}"
                session.add(row)
        with sessions() as session:
            report = render_report(session, day)
            assert len(report) <= 4000
            assert "additional result lines omitted" in report
            assert report.endswith("Historical results do not establish future profitability.")
    finally:
        engine.dispose()
