from typing import Annotated
import json
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy import select, func, or_, and_, text
from sqlalchemy.orm import Session
from app.database import get_session
from app.models import SignalPlan, SignalDecision, SignalEvent, WebNotification, NotificationRead, ServiceLease, User
from app.market.binance import now_ms
from app.market.views import collector_health
from app.signals.service import engine_health, signal_view
from app.config import get_settings
from app.main import authorize
from datetime import date as calendar_date, datetime, timedelta, timezone
from pathlib import Path
import os

router=APIRouter()
DB=Annotated[Session,Depends(get_session)]
Actor=Annotated[User,Depends(authorize)]


def operations_health(session):
    from app.ai.service import ai_health
    from app.telegram.service import telegram_health
    now=now_ms()
    collector,engine=collector_health(session),engine_health(session)
    delivery=session.get(ServiceLease,"web-delivery")
    current=bool(delivery and 0<=now-delivery.heartbeat<=15000)
    backlog=session.scalar(select(func.count()).select_from(SignalEvent).outerjoin(WebNotification,WebNotification.id==SignalEvent.id).where(WebNotification.id.is_(None)))
    access=bool(session.scalar(select(User.id).where(User.enabled.is_(True),User.role=="admin").limit(1)))
    backup={"state":"not-configured","completed_at":None}
    if os.getenv("MV_BACKUP_STATUS_FILE"):
        try:
            status=json.loads(Path(os.environ["MV_BACKUP_STATUS_FILE"]).read_text())
            completed=int(datetime.fromisoformat(status["completed_at"]).timestamp()*1000)
            backup={"state":"current" if 0<=now-completed<=36*3_600_000 else "stale","completed_at":completed}
        except (OSError,ValueError,KeyError,TypeError):
            backup={"state":"pending-or-failed","completed_at":None}
    ai = ai_health(session)
    telegram = telegram_health(session)
    return {"status":"ok","database":"connected","mode":"live-signals","collector":collector,"engine":engine,"signals":engine["state"],
            "web_delivery":{"state":"running" if current else "stale" if delivery else "not-running","heartbeat":delivery.heartbeat if delivery else None,"backlog":backlog},
            "telegram":telegram["state"],"telegram_delivery":telegram,"ai":ai["state"],"ai_review":ai,"paper":"disabled" if not get_settings().paper_enabled else "enabled",
            "ready":bool(collector["live"] and engine["ready"] and current and not get_settings().maintenance and (get_settings().environment!="production" or (access and backup["state"]=="current"))),
            "access":{"state":"invite-only" if get_settings().auth_required else "development","owner_configured":access},"backup":backup,
            "maintenance":get_settings().maintenance,"orders":"disabled","server_time":now}


@router.get("/v1/operations/health")
def health(actor:Actor,session:DB):
    return operations_health(session)


@router.get("/v1/operations/ready")
def ready(actor:Actor,session:DB):
    from fastapi.responses import JSONResponse
    result=operations_health(session)
    return JSONResponse(result,status_code=200 if result["ready"] else 503)


@router.get("/v1/notifications")
def notifications(actor:Actor,session:DB,limit:Annotated[int,Query(ge=1,le=100)]=50,
                  before_time:Annotated[int|None,Query(ge=0)]=None,before_id:Annotated[str|None,Query(pattern=r"^[a-f0-9-]{36}$")]=None):
    if (before_time is None)!=(before_id is None):
        raise HTTPException(status_code=422,detail="Provide both cursor fields")
    query=select(WebNotification)
    if before_time is not None:
        query=query.where(or_(WebNotification.created_at<before_time,and_(WebNotification.created_at==before_time,WebNotification.id<before_id)))
    rows=list(session.scalars(query.order_by(WebNotification.created_at.desc(),WebNotification.id.desc()).limit(limit+1)))
    more=len(rows)>limit
    rows=rows[:limit]
    read=set(session.scalars(select(NotificationRead.notification_id).where(NotificationRead.user_id==actor.id,NotificationRead.notification_id.in_([r.id for r in rows])))) if actor.id else set()
    already_read=select(NotificationRead.notification_id).where(NotificationRead.user_id==actor.id,NotificationRead.notification_id==WebNotification.id).exists()
    count=session.scalar(select(func.count()).select_from(WebNotification).where(~already_read))
    now=now_ms()+collector_health(session)["clock_offset_ms"]
    items=[]
    for n in rows:
        plan=session.get(SignalPlan,n.signal_id)
        view=signal_view(session,plan,now)
        items.append({"id":n.id,"signal_id":n.signal_id,"type":n.type,"created_at":n.created_at,"read":n.id in read,
                      "symbol":plan.symbol,"direction":plan.plan_json["direction"],"status":view["status"],"entry_actionable":view["entry_actionable"],"detail":n.payload_json})
    return {"notifications":items,"unread":count,"server_time":now,"next":{"before_time":rows[-1].created_at,"before_id":rows[-1].id} if more else None}


@router.post("/v1/notifications/{identity}/read")
def notification_read(identity:str,actor:Actor,session:DB):
    if not actor.id:
        raise HTTPException(status_code=403,detail="Sign in to persist notification reads")
    if not session.get(WebNotification,identity):
        raise HTTPException(status_code=404,detail="Notification not found")
    if session.get_bind().dialect.name=="postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(NotificationRead).values(user_id=actor.id,notification_id=identity,read_at=now_ms()).on_conflict_do_nothing(index_elements=[NotificationRead.user_id,NotificationRead.notification_id]))
    session.commit()
    return {"read":True}


@router.get("/v1/history/signals")
def history(actor:Actor,session:DB,symbol:Annotated[str|None,Query(pattern=r"^[A-Z0-9]{2,20}USDT$")]=None,
            direction:Annotated[str|None,Query(pattern=r"^(long|short)$")]=None,before_time:Annotated[int|None,Query(ge=0)]=None,
            before_id:Annotated[str|None,Query(pattern=r"^[a-f0-9]{64}$")]=None,limit:Annotated[int,Query(ge=1,le=100)]=25,
            date:Annotated[str|None,Query(pattern=r"^\d{4}-\d{2}-\d{2}$")]=None):
    if (before_time is None)!=(before_id is None):
        raise HTTPException(status_code=422,detail="Provide both cursor fields")
    query=select(SignalPlan)
    if date is not None:
        try:
            day=calendar_date.fromisoformat(date)
            start=int(datetime.combine(day,datetime.min.time(),tzinfo=timezone(timedelta(minutes=330))).timestamp())*1000
        except (ValueError,OverflowError) as exc:
            raise HTTPException(status_code=422,detail="Invalid IST calendar date") from exc
        # Publication time is indexed; half-open IST days preserve boundary rows
        # and apply before pagination, without modifying stored UTC timestamps.
        query=query.where(SignalPlan.created_at>=start,SignalPlan.created_at<start+86_400_000)
    if symbol: query=query.where(SignalPlan.symbol==symbol)
    if direction: query=query.where(SignalPlan.id.in_(select(SignalDecision.id).where(SignalDecision.direction==direction)))
    if before_time is not None: query=query.where(or_(SignalPlan.created_at<before_time,and_(SignalPlan.created_at==before_time,SignalPlan.id<before_id)))
    rows=list(session.scalars(query.order_by(SignalPlan.created_at.desc(),SignalPlan.id.desc()).limit(limit+1)))
    more=len(rows)>limit
    rows=rows[:limit]
    now=now_ms()+collector_health(session)["clock_offset_ms"]
    return {"signals":[signal_view(session,p,now) for p in rows],"next":{"before_time":rows[-1].created_at,"before_id":rows[-1].id} if more else None,"server_time":now}
