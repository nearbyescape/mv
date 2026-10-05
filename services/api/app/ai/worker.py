"""Separate, transaction-fenced commentary worker; publication never depends on it."""
import asyncio
from pathlib import Path
from uuid import uuid4
import httpx
from filelock import FileLock, Timeout
from sqlalchemy import select, func
from app.config import get_settings
from app.database import Session
from app.market.binance import now_ms
from app.models import AIReview, AIRequest, SignalPlan, ServiceLease
from app.operations.lease import singleton, worker_transaction, OWNERS
from app.signals.service import signal_view
from .provider import evidence_payload, request_review, ReviewError

def recover_interrupted(session, now):
    for row in session.scalars(select(AIReview).where(AIReview.status == "inflight")):
        row.status,row.error_code,row.completed_at = "failed","INTERRUPTED_REQUEST",now
    for row in session.scalars(select(AIRequest).where(AIRequest.status == "inflight")):
        row.status,row.error_code,row.completed_at = "failed","INTERRUPTED_REQUEST",now

def prepare(session, now, settings):
    for plan in session.scalars(select(SignalPlan).outerjoin(AIReview,AIReview.signal_id==SignalPlan.id)
            .where(AIReview.signal_id.is_(None),SignalPlan.created_at>=now-86_400_000)
            .order_by(SignalPlan.created_at,SignalPlan.id).limit(100)):
        view = signal_view(session,plan,now)
        session.add(AIReview(signal_id=plan.id,evidence_hash=plan.evidence_hash,plan_hash=plan.plan_json["plan_hash"],
            model=settings.ai_model,status="pending" if view["integrity_valid"] and not view["source_revised"] else "invalidated",
            attempts=0,next_attempt_at=now))
    session.flush()
    daily = session.scalar(select(func.count()).select_from(AIRequest).where(AIRequest.started_at>=now//86_400_000*86_400_000))
    if daily >= settings.ai_daily_requests:
        return None
    review = session.scalar(select(AIReview).where(AIReview.status=="pending",AIReview.next_attempt_at<=now)
                            .order_by(AIReview.next_attempt_at,AIReview.signal_id).limit(1))
    if not review:
        return None
    plan = session.get(SignalPlan,review.signal_id)
    view = signal_view(session,plan,now)
    if not view["integrity_valid"] or view["source_revised"] or review.evidence_hash!=plan.evidence_hash or review.plan_hash!=plan.plan_json["plan_hash"]:
        review.status,review.error_code = "invalidated","EVIDENCE_CHANGED"
        return None
    request = AIRequest(id=str(uuid4()),signal_id=plan.id,started_at=now,status="inflight")
    session.add(request)
    review.status,review.attempts = "inflight",review.attempts+1
    return request.id,plan.id,evidence_payload(plan)

def finish(session, request_id, signal_id, now, response=None, usage=None, error=None):
    request,review = session.get(AIRequest,request_id),session.get(AIReview,signal_id)
    if request.status != "inflight" or review.status != "inflight":
        return
    request.completed_at,request.usage_json = now,usage
    plan = session.get(SignalPlan,signal_id)
    view = signal_view(session,plan,now)
    if not view["integrity_valid"] or view["source_revised"] or review.evidence_hash!=plan.evidence_hash or review.plan_hash!=plan.plan_json["plan_hash"]:
        request.status,request.error_code = "invalidated","EVIDENCE_CHANGED"
        review.status,review.error_code,review.completed_at = "invalidated","EVIDENCE_CHANGED",now
    elif error:
        request.status,request.error_code = "failed",error.code
        review.error_code = error.code
        review.status = "pending" if error.retryable and review.attempts<2 else "failed"
        review.next_attempt_at = now+120_000
        review.completed_at = now if review.status=="failed" else None
    else:
        request.status = "complete"
        review.status,review.completed_at,review.response_json,review.error_code = "complete",now,response,None

async def perform(job, client, settings):
    request_id,signal_id,payload = job
    try:
        response,usage = await request_review(client,settings,payload)
        error = None
    except ReviewError as exc:
        response,usage,error = None,None,exc
    with worker_transaction("ai-review",Session) as session:
        finish(session,request_id,signal_id,now_ms(),response,usage,error)

async def run():
    settings = get_settings()
    if not settings.ai_enabled or not settings.openrouter_key:
        raise RuntimeError("AI worker needs enabled configuration and a server secret")
    with worker_transaction("ai-review",Session) as session:
        recover_interrupted(session,now_ms())
    task = None
    async with httpx.AsyncClient(follow_redirects=False) as client:
        try:
            while True:
                if task is not None and task.done():
                    task.result()  # Unexpected failure/ownership loss stops the worker.
                    task = None
                with worker_transaction("ai-review",Session) as session:
                    now = now_ms()
                    lease = session.get(ServiceLease,"ai-review") or ServiceLease(name="ai-review")
                    lease.owner,lease.heartbeat = OWNERS.get("ai-review","local-worker"),now
                    session.add(lease)
                    if task is None:
                        job = prepare(session,now,settings)
                    else:
                        job = None
                if job:
                    task = asyncio.create_task(perform(job,client,settings))
                await asyncio.sleep(2)
        finally:
            if task is not None:
                task.cancel()
                await asyncio.gather(task,return_exceptions=True)

if __name__ == "__main__":
    try:
        with FileLock(str(Path(__file__).resolve().parents[2]/".ai.lock"),timeout=0),singleton("ai-review"):
            asyncio.run(run())
    except (Timeout,KeyboardInterrupt):
        pass
