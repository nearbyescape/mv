import json
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_session
from .models import WatchlistItem
from .market.views import collector_health, chosen_market_views, market_view
from .market.binance import now_ms
from .signals.service import engine_health, signal_view, slot_action
from .models import SignalDecision, SignalPlan, SignalSlot
from .research.reports import read_report, download_path, read_study, study_download, read_filters, filter_download
from fastapi.responses import FileResponse
from typing import Literal

app = FastAPI(title="MV Signal API", version="0.11.0", description="Private deterministic V2 futures signals with preserved historical research, optional AI evidence commentary and Telegram delivery. No exchange orders.", docs_url=None if get_settings().environment=="production" else "/docs", redoc_url=None if get_settings().environment=="production" else "/redoc", openapi_url=None if get_settings().environment=="production" else "/openapi.json")
security = HTTPBearer(auto_error=False)
STRATEGY_FILE = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "strategy-v2.json"


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)], request: Request, session: Annotated[Session, Depends(get_session)]):
    from .auth.service import principal, check_service
    from types import SimpleNamespace
    check_service(request)
    settings = get_settings()
    token = credentials.credentials if credentials else ""
    if request.url.path.startswith("/v1/admin") and request.method not in ("GET","HEAD") and session.get_bind().dialect.name=="postgresql":
        # Serialize permission checks with bootstrap/admin changes, so a queued
        # administrator write cannot use permissions revoked while it waited.
        session.execute(text("SELECT pg_advisory_xact_lock(679012347)"))
    if settings.environment == "local" and not settings.auth_required and secrets.compare_digest(token,settings.dev_api_token):
        user = SimpleNamespace(id=None,email="",name="Local preview",role="admin",enabled=True,created_at=0)
    else:
        user = principal(session,token)
    if request.url.path.startswith("/v1/admin") and user.role != "admin":
        raise HTTPException(status_code=403,detail="Administrator access required")
    if request.method not in ("GET","HEAD") and (request.url.path == "/v1/watchlist" or request.url.path.startswith("/v1/signals/")) and user.role not in ("admin","operator"):
        raise HTTPException(status_code=403,detail="Operator access required")
    request.state.actor = user
    return user


@app.get("/v1/research/filters", dependencies=[Depends(authorize)])
def filter_study_report():
    try:
        report = read_filters()
        return {"available": report is not None, "report": report}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Filter study unavailable or integrity check failed") from exc


@app.get("/v1/research/filters/export", dependencies=[Depends(authorize)])
def filter_study_export(file: str = "report.json"):
    try:
        path, media_type = filter_download(file)
        return FileResponse(path, media_type=media_type, filename=f"mv-filter-study-{file}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No filter study generated") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Invalid or unverifiable filter study export") from exc


@app.get("/v1/paper", dependencies=[Depends(authorize)])
def forward_paper_report():
    from .paper import store
    import sqlite3
    try:
        if not get_settings().paper_enabled:
            return {"available":False,"run":None,"disabled":True,"reason":"Paper observation disabled by owner; archived journals retained"}
        return store.view(store.DB)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(status_code=503, detail="Forward journal unavailable or integrity check failed") from exc


@app.get("/v1/research/study", dependencies=[Depends(authorize)])
def exit_study_report():
    try:
        report = read_study()
        return {"available": report is not None, "report": report}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Exit study unavailable or integrity check failed") from exc


@app.get("/v1/research/study/export", dependencies=[Depends(authorize)])
def exit_study_export(file: str = "report.json"):
    try:
        path, media_type = study_download(file)
        return FileResponse(path, media_type=media_type, filename=f"mv-exit-study-{file}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No exit study generated") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Invalid or unverifiable exit study export") from exc


@app.get("/v1/research", dependencies=[Depends(authorize)])
def research_report():
    try:
        report = read_report()
        return {"available": report is not None, "report": report}
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=503, detail="Research report unavailable or integrity check failed") from exc


@app.get("/v1/research/export", dependencies=[Depends(authorize)])
def research_export(file: str = "report.json"):
    try:
        path, media_type = download_path(file)
        return FileResponse(path, media_type=media_type, filename=f"mv-research-{file}")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No research report generated") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail="Invalid or unverifiable research export") from exc


class WatchlistUpdate(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=30)

    @field_validator("symbols")
    @classmethod
    def validate_symbols(cls, symbols: list[str]) -> list[str]:
        import re
        if any(re.fullmatch(r"[A-Z0-9]{2,20}USDT", s) is None for s in symbols):
            raise ValueError("Use uppercase USDT symbols, for example BTCUSDT")
        if len(symbols) != len(set(symbols)):
            raise ValueError("Duplicate symbols are not allowed")
        return symbols


@app.get("/health")
def health(session: Annotated[Session, Depends(get_session)]):
    try:
        session.execute(text("SELECT 1"))
        session.execute(select(WatchlistItem).limit(1))
        if get_settings().environment=="production":
            from .models import User
            session.execute(select(User.id).limit(1))
            if session.scalar(text("SELECT version_num FROM alembic_version"))!="0006":
                raise RuntimeError("Database migration version mismatch")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable or migrations pending") from exc
    if get_settings().environment=="production":
        return {"status":"ok"}
    engine = engine_health(session)
    return {"status": "ok", "mode": "local-signals", "database": "connected", "collector": collector_health(session), "engine": engine, "signals": engine["state"], "telegram": "not-configured", "ai": "not-configured"}


@app.get("/v1/strategy", dependencies=[Depends(authorize)])
def strategy():
    return json.loads(STRATEGY_FILE.read_text(encoding="utf-8"))


@app.get("/v1/watchlist", dependencies=[Depends(authorize)])
def watchlist(session: Annotated[Session, Depends(get_session)]):
    symbols = list(session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order)))
    return {"symbols": symbols, "exchange_validation": "per-market-status", "monitoring": collector_health(session)["live"]}


@app.put("/v1/watchlist", dependencies=[Depends(authorize)])
def update_watchlist(payload: WatchlistUpdate, request: Request, session: Annotated[Session, Depends(get_session)]):
    # A single transaction makes replacement atomic, including on PostgreSQL.
    session.execute(delete(WatchlistItem))
    session.add_all(WatchlistItem(symbol=s, sort_order=i) for i, s in enumerate(payload.symbols))
    from .auth.service import audit
    audit(session,request.state.actor.id,"watchlist-updated",{"symbols":payload.symbols})
    session.commit()
    return {"symbols": payload.symbols, "exchange_validation": "pending-collector-validation", "monitoring": False}


@app.get("/v1/markets", dependencies=[Depends(authorize)])
def markets(session: Annotated[Session, Depends(get_session)]):
    return {"markets": chosen_market_views(session), "collector": collector_health(session)}


@app.get("/v1/markets/{symbol}", dependencies=[Depends(authorize)])
def market(symbol: str, session: Annotated[Session, Depends(get_session)], timeframe: str = "1h"):
    if timeframe not in ("1h", "4h"):
        raise HTTPException(status_code=422, detail="Use timeframe 1h or 4h")
    if session.get(WatchlistItem, symbol) is None:
        raise HTTPException(status_code=404, detail="Symbol is not in your chosen coins")
    return market_view(session, symbol, timeframe)


@app.get("/v1/signals", dependencies=[Depends(authorize)])
def signals(session: Annotated[Session, Depends(get_session)], limit: Annotated[int, Query(ge=1, le=100)] = 50):
    now = now_ms() + collector_health(session)["clock_offset_ms"]
    recent = list(session.scalars(select(SignalPlan).order_by(SignalPlan.created_at.desc()).limit(limit)))
    active = list(session.scalars(select(SignalPlan).join(SignalSlot, SignalSlot.signal_id == SignalPlan.id)))
    plans = sorted({row.id: row for row in recent + active}.values(), key=lambda row: row.created_at, reverse=True)
    decisions = session.scalars(select(SignalDecision).order_by(SignalDecision.updated_at.desc()).limit(25))
    return {"engine": engine_health(session), "server_time": now, "signals": [signal_view(session, row, now) for row in plans],
            "decisions": [{"id": row.id, "symbol": row.symbol, "source_open_time": row.source_open_time, "outcome": row.outcome, "reason": row.reason, "direction": row.direction, "updated_at": row.updated_at, "attempts": row.attempts} for row in decisions],
            "slots": [{"symbol": row.symbol, "signal_id": row.signal_id, "state": row.state} for row in session.scalars(select(SignalSlot))]}


@app.get("/v1/signals/{signal_id}", dependencies=[Depends(authorize)])
def signal(signal_id: str, session: Annotated[Session, Depends(get_session)]):
    row = session.get(SignalPlan, signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal_view(session, row, now_ms() + collector_health(session)["clock_offset_ms"])


@app.get("/v1/signals/{signal_id}/chart", dependencies=[Depends(authorize)])
def signal_chart(signal_id: str, session: Annotated[Session, Depends(get_session)], window: Literal['source','latest'] = 'source'):
    row = session.get(SignalPlan, signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    view = signal_view(session, row, now_ms() + collector_health(session)['clock_offset_ms'])
    if not view['integrity_valid']:
        raise HTTPException(status_code=409, detail="Signal integrity check failed")
    from .market.signal_chart import signal_chart_view
    return signal_chart_view(session, view, window)


from .auth.routes import router as auth_router
from .operations.routes import router as operations_router
app.include_router(auth_router)
app.include_router(operations_router)


class SignalAction(BaseModel):
    action: Literal["hold", "release"]
    note: str = Field(default="Reported by workspace operator", max_length=200)


@app.post("/v1/signals/{signal_id}/slot", dependencies=[Depends(authorize)])
def update_signal_slot(signal_id: str, payload: SignalAction, request: Request, session: Annotated[Session, Depends(get_session)]):
    if payload.action=="hold" and get_settings().maintenance:
        raise HTTPException(status_code=409,detail="Entry actions paused for maintenance")
    if session.get_bind().dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    row = session.get(SignalPlan, signal_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    try:
        from .operations.market_lock import lock_market
        lock_market(session,row.symbol)
        slot_action(session, row, payload.action, now_ms(), payload.note.strip())
        from .auth.service import audit
        audit(session,request.state.actor.id,"signal-"+payload.action,{"signal_id":signal_id,"note":payload.note.strip()})
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return signal_view(session, row, now_ms() + collector_health(session)["clock_offset_ms"])
