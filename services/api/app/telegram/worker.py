"""A fenced durable outbox. Ambiguous sends remain visible and are never blindly retried."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
from filelock import FileLock, Timeout
from sqlalchemy import select, func
from app.config import get_settings
from app.database import Session
from app.market.binance import now_ms
from app.market.views import collector_health
from app.models import SignalEvent, SignalPlan, TelegramDelivery, ServiceLease
from app.operations.lease import singleton, worker_transaction, OWNERS
from app.signals.service import signal_view, canonical_hash
from app.signals.session import allowed
from .provider import send, DeliveryError

GAP_MS=4000


def ist(timestamp):
    return datetime.fromtimestamp(timestamp/1000,timezone(timedelta(minutes=330))).strftime("%d %b %Y, %I:%M %p IST")


def payload_for(event, plan, settings):
    p=plan.plan_json
    if event.type=="source-revised":
        text=f"MV Signal · WITHDRAWN\n{plan.symbol} · {p['direction'].upper()}\nSource data changed after publication. Review any held position.\nOriginal signal: {plan.id[:12]}\nOriginal levels remain unchanged in the journal."
    else:
        setup={"momentum_breakout":"Momentum breakout","pullback_continuation":"Pullback continuation"}.get(p.get("setup_type"),"Trend setup")
        regime=str(p.get("trend_regime") or "confirmed").title()
        text=(f"MV Signal · {p['direction'].upper()}\n{plan.symbol} · Binance USDT futures · 1H\n"
              f"Setup: {setup} · {regime} trend\n"
              f"Source close: {ist(p['source_close_boundary'])}\nEntry: {p['entry']}\nStop loss: {p['stop']}\nTarget: {p['target']}\n"
              f"Entry window ends: {ist(plan.expires_at)}\nEMA20 / EMA50 / SMA200 + ATR14 · completed 4H confirmed\n"
              f"Signal: {plan.id[:12]}\nReference quote; execution and fills are not recorded.")
    return {"chat_id":settings.telegram_chat_id,"text":text,"link_preview_options":{"is_disabled":True},
            "reply_markup":{"inline_keyboard":[[{"text":"Open MV Signal","url":settings.public_origin}]]}}


def enqueue(session, now, settings):
    rows=session.scalars(select(SignalEvent).outerjoin(TelegramDelivery,TelegramDelivery.event_id==SignalEvent.id)
         .where(TelegramDelivery.event_id.is_(None),SignalEvent.type.in_(["published","source-revised"]),
                SignalEvent.created_at>=settings.telegram_start_at)
         .order_by(SignalEvent.created_at,SignalEvent.id).limit(200))
    for event in rows:
        plan=session.get(SignalPlan,event.signal_id)
        payload=payload_for(event,plan,settings)
        session.add(TelegramDelivery(event_id=event.id,signal_id=plan.id,chat_id=settings.telegram_chat_id,
            status="pending",attempts=0,next_attempt_at=now,payload_json=payload,payload_hash=canonical_hash(payload),
            evidence_hash=plan.evidence_hash,plan_hash=plan.plan_json["plan_hash"]))
    session.flush()


def recover_interrupted(session):
    for row in session.scalars(select(TelegramDelivery).where(TelegramDelivery.status=="inflight")):
        row.status,row.error_code="unknown","INTERRUPTED_SEND"


def prepare(session, now, settings):
    enqueue(session,now,settings)
    blocked_until=session.scalar(select(func.max(TelegramDelivery.next_attempt_at)).where(TelegramDelivery.status=="retry",TelegramDelivery.error_code=="RATE_LIMITED"))
    if blocked_until is not None and now<blocked_until:
        return None
    last=session.scalar(select(func.max(TelegramDelivery.claimed_at)))
    if last is not None and now<last+GAP_MS:
        return None
    if session.scalar(select(TelegramDelivery.event_id).where(TelegramDelivery.status=="inflight").limit(1)):
        return None
    row=session.scalar(select(TelegramDelivery).where(TelegramDelivery.status.in_(["pending","retry"]),TelegramDelivery.next_attempt_at<=now)
                       .order_by(TelegramDelivery.next_attempt_at,TelegramDelivery.event_id).limit(1))
    if not row:
        return None
    event,plan=session.get(SignalEvent,row.event_id),session.get(SignalPlan,row.signal_id)
    view=signal_view(session,plan,now+collector_health(session)["clock_offset_ms"])
    reason=None
    if row.chat_id!=settings.telegram_chat_id:
        reason="DESTINATION_CHANGED"
    elif row.payload_hash!=canonical_hash(row.payload_json) or row.evidence_hash!=plan.evidence_hash or row.plan_hash!=plan.plan_json.get("plan_hash") or not view["integrity_valid"]:
        reason="EVIDENCE_OR_PAYLOAD_CHANGED"
    elif event.type=="published":
        exchange_now=now+collector_health(session)["clock_offset_ms"]
        if view["source_revised"]:
            reason="SOURCE_REVISED"
        elif view["status"]!="active" or exchange_now>=plan.expires_at:
            reason="ENTRY_NO_LONGER_ACTIVE"
        elif not allowed(plan.plan_json["source_close_boundary"],exchange_now):
            reason="OUTSIDE_SIGNAL_SESSION"
    else:
        publication=session.scalar(select(TelegramDelivery).join(SignalEvent,SignalEvent.id==TelegramDelivery.event_id)
            .where(TelegramDelivery.signal_id==plan.id,SignalEvent.type=="published"))
        if not publication or publication.status not in ("delivered","unknown"):
            reason="NO_PRIOR_DELIVERY"
    if reason:
        row.status,row.error_code="skipped",reason
        return None
    row.status,row.attempts,row.claimed_at="inflight",row.attempts+1,now
    return row.event_id,dict(row.payload_json)


def finish(session, identity, now, message_id=None, error=None):
    row=session.get(TelegramDelivery,identity)
    if not row or row.status!="inflight":
        return
    if error:
        row.status="failed" if error.state=="retry" and row.attempts>=5 else error.state
        row.error_code=error.code
        row.next_attempt_at=now+max(4,error.retry_after)*1000
    else:
        row.status,row.message_id,row.sent_at,row.error_code="delivered",message_id,now,None


async def perform(job,client,settings):
    try:
        message_id,error=await send(client,settings,job[1]),None
    except DeliveryError as exc:
        message_id,error=None,exc
    with worker_transaction("telegram-delivery",Session) as session:
        finish(session,job[0],now_ms(),message_id,error)


async def run():
    settings=get_settings()
    if not settings.telegram_enabled or not settings.telegram_token:
        raise RuntimeError("Telegram worker requires enabled configuration and a server secret")
    with worker_transaction("telegram-delivery",Session) as session:
        recover_interrupted(session)
    task=None
    async with httpx.AsyncClient(follow_redirects=False) as client:
        try:
            while True:
                if task is not None and task.done():
                    task.result()
                    task=None
                with worker_transaction("telegram-delivery",Session) as session:
                    now=now_ms()
                    lease=session.get(ServiceLease,"telegram-delivery") or ServiceLease(name="telegram-delivery")
                    lease.owner,lease.heartbeat=OWNERS.get("telegram-delivery","local-worker"),now
                    session.add(lease)
                    job=prepare(session,now,settings) if task is None and not settings.maintenance else None
                if job:
                    task=asyncio.create_task(perform(job,client,settings))
                await asyncio.sleep(2)
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        with FileLock(str(Path(__file__).resolve().parents[2]/".telegram.lock"),timeout=0),singleton("telegram-delivery"):
            asyncio.run(run())
    except (Timeout,KeyboardInterrupt):
        pass
