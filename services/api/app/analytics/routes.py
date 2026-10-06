from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.main import authorize
from app.models import SignalOutcome, User
from .service import outcome_view, performance_summary

router = APIRouter()
DB = Annotated[Session, Depends(get_session)]
Actor = Annotated[User, Depends(authorize)]


@router.get("/v1/analytics/performance")
def performance(actor: Actor, session: DB):
    return performance_summary(session)


@router.get("/v1/analytics/outcomes")
def outcomes(
    actor: Actor,
    session: DB,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    symbol: Annotated[str | None, Query(pattern=r"^[A-Z0-9]{2,20}USDT$")] = None,
    direction: Annotated[str | None, Query(pattern=r"^(long|short)$")] = None,
    setup_type: Annotated[str | None, Query(pattern=r"^(pullback_continuation|momentum_breakout)$")] = None,
):
    query = select(SignalOutcome)
    if symbol:
        query = query.where(SignalOutcome.symbol == symbol)
    if direction:
        query = query.where(SignalOutcome.direction == direction)
    if setup_type:
        query = query.where(SignalOutcome.setup_type == setup_type)
    rows = list(
        session.scalars(
            query.order_by(SignalOutcome.published_at.desc(), SignalOutcome.signal_id.desc()).limit(limit)
        )
    )
    return {"outcomes": [outcome_view(row) for row in rows], "limit": limit}
