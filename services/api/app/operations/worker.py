import asyncio
import argparse
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from filelock import FileLock, Timeout
from app.database import Session
from app.models import SignalEvent, WebNotification, ServiceLease
from app.market.binance import now_ms
from .lease import singleton, worker_transaction, OWNERS


def sync_notifications(session,limit=500):
    rows=session.scalars(select(SignalEvent).outerjoin(WebNotification,WebNotification.id==SignalEvent.id).where(WebNotification.id.is_(None)).order_by(SignalEvent.created_at,SignalEvent.id).limit(limit))
    if session.get_bind().dialect.name=="postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    count=0
    for event in rows:
        inserted=session.scalar(insert(WebNotification).values(id=event.id,signal_id=event.signal_id,type=event.type,created_at=event.created_at,payload_json=event.payload_json).on_conflict_do_nothing(index_elements=[WebNotification.id]).returning(WebNotification.id))
        count+=int(inserted is not None)
    return count


async def run(once=False):
    owner=str(uuid4())
    while True:
        with worker_transaction("web-delivery", Session) as session:
            sync_notifications(session)
            lease=session.get(ServiceLease,"web-delivery") or ServiceLease(name="web-delivery")
            lease.owner,lease.heartbeat=OWNERS.get("web-delivery",owner),now_ms()
            session.add(lease)
        if once:
            return
        await asyncio.sleep(2)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    try:
        with FileLock(str(Path(__file__).resolve().parents[2]/".delivery.lock"),timeout=0),singleton("web-delivery"):
            asyncio.run(run(args.once))
    except (Timeout,KeyboardInterrupt):
        pass
