"""Operator-only reset after backup verification and stopping all signal writers."""
import argparse
import json
from uuid import uuid4
from sqlalchemy import select, func, delete, update
from app.database import Session
from app.market.binance import now_ms
from app.models import (SignalPlan,SignalDecision,SignalEvent,SignalSlot,WebNotification,NotificationRead,
                        AIReview,AIRequest,TelegramDelivery,SignalOutcome,DecisionOpportunity,EngineCursor,IndicatorCheckpoint,EngineStatus,ServiceLease,AuditEvent)

GENERATED=(NotificationRead,WebNotification,TelegramDelivery,SignalOutcome,DecisionOpportunity,SignalSlot,SignalEvent,AIReview,SignalPlan,SignalDecision)
WRITERS=("signal-engine","web-delivery","ai-review","telegram-delivery","outcome-analytics")


def counts(session):
    return {m.__tablename__:session.scalar(select(func.count()).select_from(m)) for m in GENERATED}


def clear_generated(session, now, backup_receipt):
    if not backup_receipt or len(backup_receipt)>300:
        raise ValueError("A verified backup receipt is required")
    for row in session.scalars(select(ServiceLease).where(ServiceLease.name.in_(WRITERS))):
        if 0<=now-row.heartbeat<30_000:
            raise ValueError("Stop signal-engine, web-delivery, AI, Telegram and outcome-analytics workers before resetting")
    engine=session.get(EngineStatus,"engine")
    if engine and engine.state not in ("stopped","maintenance") and 0<=now-engine.updated_at<30_000:
        raise ValueError("Stop the signal engine before resetting")
    before=counts(session)
    # Preserve the durable paid-request ledger, so reset cannot replenish AI spend.
    session.execute(update(AIRequest).values(signal_id=None))
    for model in GENERATED:
        session.execute(delete(model))
    advanced=0
    for cursor in session.scalars(select(EngineCursor)):
        checkpoint=session.get(IndicatorCheckpoint,(cursor.symbol,"1h"))
        if checkpoint and checkpoint.state_json.get("last_open_time") is not None:
            cursor.last_open_time=max(cursor.last_open_time,checkpoint.state_json["last_open_time"])
            advanced+=1
    if engine:
        engine.last_decision_at=None
    session.add(AuditEvent(id=str(uuid4()),actor_id=None,action="signal-records-cleared",created_at=now,
        detail_json={"deleted":before,"backup_receipt":backup_receipt,"cursors_retained":advanced,"ai_spend_ledger":"retained"}))
    session.flush()
    if any(counts(session).values()):
        raise RuntimeError("Reset did not clear all generated records")
    return {"deleted":before,"cursors_retained":advanced,"ai_requests_retained":session.scalar(select(func.count()).select_from(AIRequest)),"reset_at":now}


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--verified-backup",default="")
    args=parser.parse_args()
    with Session.begin() as session:
        result=clear_generated(session,now_ms(),args.verified_backup) if args.apply else {"dry_run":True,"counts":counts(session)}
    print(json.dumps(result,sort_keys=True))
