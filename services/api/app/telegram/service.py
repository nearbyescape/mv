from sqlalchemy import select, func
from app.config import get_settings
from app.models import TelegramDelivery, SignalEvent, ServiceLease


def delivery_view(session, signal_id):
    if not get_settings().telegram_enabled:
        return "not-configured"
    row = session.scalar(select(TelegramDelivery).join(SignalEvent, SignalEvent.id==TelegramDelivery.event_id)
                         .where(TelegramDelivery.signal_id==signal_id,SignalEvent.type=="published"))
    return row.status if row else "pending"


def telegram_health(session):
    from app.market.binance import now_ms
    settings = get_settings()
    if not settings.telegram_enabled:
        return {"state":"not-configured","pending":0,"failed":0,"unknown":0,"delivered":0,"last_sent_at":None}
    now = now_ms()
    lease = session.get(ServiceLease,"telegram-delivery")
    counts = dict(session.execute(select(TelegramDelivery.status,func.count()).group_by(TelegramDelivery.status)).all())
    state = "running" if lease and 0<=now-lease.heartbeat<=15_000 else "stale" if lease else "not-running"
    return {"state":state,"pending":counts.get("pending",0)+counts.get("retry",0)+counts.get("inflight",0),
            "failed":counts.get("failed",0),"unknown":counts.get("unknown",0),"delivered":counts.get("delivered",0),
            "last_sent_at":session.scalar(select(func.max(TelegramDelivery.sent_at)))}
