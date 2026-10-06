from uuid import uuid4
from sqlalchemy import select,func
import pytest
from app.operations.reset import clear_generated,counts
from app.operations.worker import sync_notifications
from app.models import AIRequest,AIReview,User,EngineCursor,WatchlistItem,Candle,IndicatorCheckpoint,EngineStatus,AuditEvent
from app.signals.service import STRATEGY_ID,discover,canonical_hash
from test_signal_service import state,seed,pending,publish,BOUNDARY,STEP
from app.ai.worker import prepare as prepare_ai
from app.analytics.service import seed_signal_outcomes
from types import SimpleNamespace


def setup(state):
    seed(state);identity=pending(state);publish(state,identity)
    with state.sessions.begin() as session:
        sync_notifications(session)
        seed_signal_outcomes(session,state.clock[0])
        session.add(User(id=str(uuid4()),email="owner@example.test",name="Owner",role="admin",password_hash="retained-test-hash",enabled=True,created_at=BOUNDARY))
        session.add(EngineCursor(symbol="BTCUSDT",strategy=STRATEGY_ID,last_open_time=BOUNDARY-2*STEP,initialized_at=BOUNDARY))
        session.add(AIRequest(id=str(uuid4()),signal_id=identity,started_at=state.clock[0],status="complete",usage_json={"cost":"retained"}))
    return identity


def test_atomic_clear_preserves_users_markets_checkpoints_and_ai_budget_and_prevents_old_replay(state):
    setup(state)
    with state.sessions.begin() as session:
        before={m.__tablename__:session.scalar(select(func.count()).select_from(m)) for m in (User,WatchlistItem,Candle,IndicatorCheckpoint,AIRequest)}
        result=clear_generated(session,state.clock[0]+31_000,"verified-test-backup:sha256")
        assert result["deleted"]["signal_plans"]==1 and result["deleted"]["web_notifications"]==1
        assert result["deleted"]["signal_outcomes"]==1
        assert not any(counts(session).values())
        assert session.scalar(select(AIRequest)).signal_id is None
        for m in (User,WatchlistItem,Candle,IndicatorCheckpoint,AIRequest):assert session.scalar(select(func.count()).select_from(m))==before[m.__tablename__]
        assert session.scalar(select(User)).password_hash=="retained-test-hash"
        assert session.scalar(select(AuditEvent)).action=="signal-records-cleared"
        discover(session,state.clock[0])
        assert not any(counts(session).values())
        # Retained spend still exhausts the day's configured single-request allowance.
        assert prepare_ai(session,state.clock[0],SimpleNamespace(ai_daily_requests=1,ai_model="deepseek/deepseek-v4-pro-0813")) is None


def test_clear_rolls_back_every_deleted_row_on_interruption(state):
    setup(state)
    with state.sessions() as session:before=counts(session)
    with pytest.raises(RuntimeError):
        with state.sessions.begin() as session:
            clear_generated(session,state.clock[0]+31_000,"verified-test-backup")
            raise RuntimeError("interruption")
    with state.sessions() as session:
        assert counts(session)==before and session.scalar(select(AIRequest)).signal_id is not None


def test_reset_requires_backup_and_quiet_workers(state):
    setup(state)
    with state.sessions.begin() as session:
        with pytest.raises(ValueError,match="backup"):clear_generated(session,state.clock[0],"")
        with pytest.raises(ValueError,match="engine"):clear_generated(session,state.clock[0],"verified-backup")
