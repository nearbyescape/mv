"""Session-close V4 Telegram summaries; no signal execution or strategy mutation."""
import argparse
import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from html import escape, unescape
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from filelock import FileLock, Timeout
from sqlalchemy import select

from app.config import get_settings
from app.database import Session
from app.market.binance import now_ms
from app.models import SignalOutcome, TelegramDailyReport
from app.operations.lease import singleton, worker_transaction
from app.telegram.provider import DeliveryError, send

log = logging.getLogger("mv.telegram.daily_report")
IST = ZoneInfo("Asia/Kolkata")
STRATEGY = "MV-TREND-DUAL-v4"
REPORT_AT = time(23, 10)
MAX_ATTEMPTS = 5
MAX_MESSAGE = 4000
TERMINAL = frozenset(("tp3", "target", "stop", "protected_be", "protected_tp1", "ambiguous"))


def milliseconds(value):
    return int(value.timestamp() * 1000)


def boundaries(day):
    midnight = datetime.combine(day, time.min, tzinfo=IST)
    session_start = datetime.combine(day, time(9, 0), tzinfo=IST)
    session_end = datetime.combine(day, time(23, 0), tzinfo=IST)
    due = datetime.combine(day, REPORT_AT, tzinfo=IST)
    return tuple(map(milliseconds, (midnight, session_start, session_end, due)))


def due_session(now):
    local = datetime.fromtimestamp(now / 1000, IST)
    day = local.date()
    due = boundaries(day)[3]
    if now < due:
        day -= timedelta(days=1)
        due = boundaries(day)[3]
    return day, due


def reference_rows(session, day):
    midnight, start, end, due = boundaries(day)
    todays = list(session.scalars(
        select(SignalOutcome).where(
            SignalOutcome.strategy == STRATEGY,
            SignalOutcome.published_at >= start,
            SignalOutcome.published_at < end,
        ).order_by(SignalOutcome.published_at, SignalOutcome.signal_id)
    ))
    carryover = list(session.scalars(
        select(SignalOutcome).where(
            SignalOutcome.strategy == STRATEGY,
            SignalOutcome.published_at < start,
            SignalOutcome.terminal_at >= midnight,
            SignalOutcome.terminal_at < due,
        ).order_by(SignalOutcome.terminal_at, SignalOutcome.signal_id)
    ))
    return todays, carryover


def display_r(value):
    return f"{Decimal(value):+.3f}R" if value is not None else "pending"


def outcome_line(row):
    symbol = escape(row.symbol.removesuffix("USDT"))
    direction = escape(row.direction.upper())
    status = row.status
    labels = {
        "tp3": "✅ TP3 HIT",
        "target": "✅ Target hit",
        "protected_be": "🛡️ TP1 ✅ · TP2 ❌ · TP3 ❌ · Protected BE",
        "protected_tp1": "🛡️ TP1 ✅ · TP2 ✅ · TP3 ❌ · Protected at TP1",
        "stop": "❌ Stop-loss",
        "ambiguous": "⚠️ Ambiguous bar (conservative result)",
        "open": "⏳ Still open",
        "source_revised": "🚫 Source revised",
    }
    label = labels.get(status, "⚠️ " + escape(status))
    return f"{label}\n<b>{symbol}/USDT</b> · {direction} | {display_r(row.conservative_r)}"


def render_report(session, day):
    todays, carryover = reference_rows(session, day)
    settled = [row for row in todays if row.status in TERMINAL]
    positive = sum(Decimal(row.conservative_r) > 0 for row in settled if row.conservative_r is not None)
    total = sum((Decimal(row.conservative_r) for row in settled if row.conservative_r is not None), Decimal(0))
    tp3 = sum(row.status == "tp3" for row in todays)
    protected = sum(row.status in ("protected_be", "protected_tp1") for row in todays)
    stopped = sum(row.status == "stop" for row in todays)
    open_count = sum(row.status == "open" for row in todays)
    ambiguous = sum(row.status == "ambiguous" for row in todays)
    revised = sum(row.status == "source_revised" for row in todays)

    heading = [
        "<b>📊 MV SIGNAL — DAILY PERFORMANCE</b>",
        f"📅 {day.strftime('%d %B %Y')}",
        "🧠 Strategy: MV V4",
        "🕚 Session: 09:00 AM – 11:00 PM IST",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "<b>📈 TODAY'S PERFORMANCE</b>",
        "━━━━━━━━━━━━━━━━━━",
        f"📡 Total signals: <b>{len(todays)}</b>",
        f"✅ TP3 completed: <b>{tp3}</b>",
        f"🛡️ Protected exits: <b>{protected}</b>",
        f"❌ Stop-loss exits: <b>{stopped}</b>",
        f"⏳ Still open: <b>{open_count}</b>",
    ]
    if ambiguous:
        heading.append(f"⚠️ Ambiguous outcomes: <b>{ambiguous}</b>")
    if revised:
        heading.append(f"🚫 Revised outcomes: <b>{revised}</b>")
    heading += [
        f"🎯 Positive resolved outcomes: <b>{positive}/{len(settled)}</b>",
        f"💰 Resolved reference total: <b>{display_r(total)}</b>",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "<b>🎯 TODAY'S SIGNAL RESULTS</b>",
        "━━━━━━━━━━━━━━━━━━",
    ]

    lines = ["\n".join(heading)]
    entries = [outcome_line(row) for row in todays]
    if not entries:
        entries = ["No V4 signals were published this session."]
    if carryover:
        entries += [
            "━━━━━━━━━━━━━━━━━━\n<b>🔄 CARRYOVER RESOLVED TODAY</b>\n"
            "━━━━━━━━━━━━━━━━━━",
            *(outcome_line(row) for row in carryover),
            "<i>Carryover outcomes are excluded from today's reference total.</i>",
        ]
    footer = (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "<b>📋 REPORT INFORMATION</b>\n"
        "⚠️ Reference-plan analytics, not exchange fills or account P&amp;L. "
        "Fees, funding and slippage excluded. "
        "Post-exit targets are not credited. "
        "Historical results do not establish future profitability."
    )
    kept = 0
    for item in entries:
        candidate = "\n\n".join(lines + [item])
        if len(candidate) + len(footer) + 100 > MAX_MESSAGE:
            break
        lines.append(item)
        kept += 1
    omitted = len(entries) - kept
    if omitted:
        lines.append(f"… {omitted} additional result lines omitted due to Telegram length limit.")
    message = "\n\n".join(lines) + footer
    if len(message) > MAX_MESSAGE:
        raise ValueError("Daily Telegram report exceeds allowed size")
    return message


def build_payload(session, day, chat_id):
    return {
        "chat_id": chat_id,
        "text": render_report(session, day),
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }


def prepare(session, now, settings):
    day, due = due_session(now)
    if due < settings.daily_report_start_at:
        return None
    identity = (day.isoformat(), STRATEGY, settings.telegram_chat_id)
    row = session.get(TelegramDailyReport, identity)
    if row is None:
        row = TelegramDailyReport(
            report_date=identity[0], strategy=STRATEGY,
            chat_id=settings.telegram_chat_id, status="pending",
            attempts=0, next_attempt_at=now, claimed_at=None,
            sent_at=None, message_id=None, error_code=None,
            payload_json=build_payload(session, day, settings.telegram_chat_id),
        )
        session.add(row)
        session.flush()

    candidate = session.scalar(
        select(TelegramDailyReport).where(
            TelegramDailyReport.strategy == STRATEGY,
            TelegramDailyReport.chat_id == settings.telegram_chat_id,
            TelegramDailyReport.status.in_(("pending", "retry")),
            TelegramDailyReport.next_attempt_at <= now,
        ).order_by(TelegramDailyReport.report_date).limit(1).with_for_update()
    )
    if candidate is None:
        return None
    if candidate.attempts >= MAX_ATTEMPTS:
        candidate.status = "failed"
        candidate.error_code = "RETRY_LIMIT_EXCEEDED"
        return None
    candidate.status = "inflight"
    candidate.attempts += 1
    candidate.claimed_at = now
    return (candidate.report_date, candidate.strategy, candidate.chat_id), dict(candidate.payload_json)


def recover_interrupted(session):
    rows = list(session.scalars(
        select(TelegramDailyReport).where(TelegramDailyReport.status == "inflight")
    ))
    for row in rows:
        row.status = "unknown"
        row.error_code = "INTERRUPTED_SEND"
    return len(rows)


def finish(session, identity, now, message_id=None, error=None):
    row = session.get(TelegramDailyReport, identity, with_for_update=True)
    if row is None or row.status != "inflight":
        return
    if error is None:
        row.status = "delivered"
        row.message_id = message_id
        row.sent_at = now
        row.error_code = None
        return
    row.status = (
        "failed" if error.state == "retry" and row.attempts >= MAX_ATTEMPTS
        else error.state
    )
    row.error_code = error.code
    row.next_attempt_at = now + max(error.retry_after, 15) * 1000


async def deliver(client, settings, job):
    try:
        message_id = await send(client, settings, job[1])
        error = None
    except DeliveryError as exc:
        message_id, error = None, exc
    with worker_transaction("telegram-daily-report", Session) as session:
        finish(session, job[0], now_ms(), message_id=message_id, error=error)
    if error:
        log.warning("Daily report send status=%s reason=%s", error.state, error.code)
    else:
        log.info("Daily report delivered date=%s message_id=%s", job[0][0], message_id)


async def run(once=False):
    settings = get_settings()
    if not settings.telegram_enabled or not settings.telegram_token or settings.daily_report_start_at <= 0:
        raise RuntimeError("Daily report requires Telegram and MV_DAILY_REPORT_START_AT")
    with FileLock(str(Path(__file__).resolve().parents[2] / ".telegram-daily-report.lock"), timeout=0):
        with singleton("telegram-daily-report"):
            with worker_transaction("telegram-daily-report", Session) as session:
                count = recover_interrupted(session)
                if count:
                    log.warning("%s uncertain daily report sends require manual verification", count)
            async with httpx.AsyncClient(follow_redirects=False) as client:
                while True:
                    job = None
                    if not settings.maintenance:
                        with worker_transaction("telegram-daily-report", Session) as session:
                            job = prepare(session, now_ms(), settings)
                    if job:
                        await deliver(client, settings, job)
                    if once:
                        return
                    await asyncio.sleep(15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Perform one due send attempt")
    parser.add_argument("--preview-date", help="Read-only HTML preview, YYYY-MM-DD; never sends")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.preview_date:
        day = date.fromisoformat(args.preview_date)
        with Session() as session:
            message = render_report(session, day)
        print(unescape(re.sub(r"</?b>|</?i>", "", message)))
        return
    try:
        asyncio.run(run(once=args.once))
    except (Timeout, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
