"""One budgeted real-provider diagnostic using actual retained market evidence, no signal insertion."""
import asyncio
import json
from uuid import uuid4
import httpx
from sqlalchemy import select, func
from app.config import get_settings
from app.database import Session
from app.market.binance import now_ms
from app.models import AIRequest, WatchlistItem, IndicatorCheckpoint, IndicatorSnapshot
from app.operations.lease import singleton, worker_transaction
from .provider import request_review, ReviewError

async def main():
    settings = get_settings()
    if not settings.ai_enabled or not settings.openrouter_key:
        raise RuntimeError("AI diagnostic needs enabled server configuration")
    request_id = str(uuid4())
    with worker_transaction("ai-review",Session) as session:
        now = now_ms()
        used = session.scalar(select(func.count()).select_from(AIRequest).where(AIRequest.started_at>=now//86_400_000*86_400_000))
        if used>=settings.ai_daily_requests:
            raise RuntimeError("Daily request limit reached")
        symbol = session.scalar(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order).limit(1))
        snapshots = {}
        for timeframe in ("1h","4h"):
            checkpoint = session.get(IndicatorCheckpoint,(symbol,timeframe))
            if not checkpoint or checkpoint.state_json["count"]<500:
                raise RuntimeError("Live market not warmed")
            row = session.get(IndicatorSnapshot,(symbol,timeframe,checkpoint.state_json["last_open_time"]))
            snapshots[timeframe] = {key:getattr(row,key) for key in ("open_time","ema20","ema50","sma200","atr","lineage")}
        payload = {"kind":"provider-connectivity-diagnostic","signal_id":None,"symbol":symbol,
                   "instruction":"These are real completed market snapshots, not a published signal. No entry/risk plan exists.",
                   "snapshots":snapshots,"checks":[{"id":"both_timeframes_warmed","passed":True}],"guards":{}}
        session.add(AIRequest(id=request_id,signal_id=None,started_at=now,status="inflight"))
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            response,usage = await request_review(client,settings,payload)
        error = None
    except ReviewError as exc:
        response,usage,error = None,None,exc
    with worker_transaction("ai-review",Session) as session:
        row = session.get(AIRequest,request_id)
        row.status,row.completed_at,row.usage_json,row.error_code = "failed" if error else "complete",now_ms(),usage,error.code if error else None
    if error:
        print(json.dumps({"diagnostic":"failed","error_code":error.code,"signal_created":False}))
        raise SystemExit(1)
    print(json.dumps({"diagnostic":"passed","model":settings.ai_model,"usage":usage,
                      "commentary":response,"signal_created":False},indent=2))

if __name__ == "__main__":
    with singleton("ai-review"):
        asyncio.run(main())
