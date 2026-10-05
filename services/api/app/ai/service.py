from sqlalchemy import select, func
from app.config import get_settings
from app.models import AIReview, AIRequest, ServiceLease

def ai_health(session):
    from app.market.binance import now_ms
    settings = get_settings()
    if not settings.ai_enabled:
        return {"state":"not-configured","pending":0,"daily_requests":0,"daily_limit":settings.ai_daily_requests}
    now = now_ms()
    lease = session.get(ServiceLease,"ai-review")
    daily = session.scalar(select(func.count()).select_from(AIRequest).where(AIRequest.started_at >= now//86_400_000*86_400_000))
    pending = session.scalar(select(func.count()).select_from(AIReview).where(AIReview.status.in_(["pending","inflight"])))
    state = "running" if lease and 0 <= now-lease.heartbeat <= 15_000 else "stale" if lease else "not-running"
    return {"state":state,"model":settings.ai_model,"pending":pending,"daily_requests":daily,"daily_limit":settings.ai_daily_requests}

def review_view(session, plan, integrity=True, revised=False):
    row = session.get(AIReview,plan.id)
    if not row:
        return {"status":"pending" if get_settings().ai_enabled else "not-configured","summary":None}
    valid = integrity and not revised and row.evidence_hash == plan.evidence_hash and row.plan_hash == plan.plan_json.get("plan_hash")
    return {"status":row.status if valid else "invalidated","model":row.model,"completed_at":row.completed_at,
            "error_code":row.error_code,"evidence_hash":row.evidence_hash,
            **(row.response_json if valid and row.status == "complete" and row.response_json else {"summary":None})}
