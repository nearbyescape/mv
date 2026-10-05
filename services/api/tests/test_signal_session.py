"""Independent clock boundaries and backend state transitions for operating hours."""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, func
import pytest
from app.config import get_settings
from app.models import SignalDecision,SignalPlan,SignalSlot,EngineCursor,EngineStatus
from app.signals import session as operating
from app.signals.service import evaluate_decision,discover,engine_health,expire_slots
from app.signals.worker import SignalWorker
from test_signal_service import state,seed,pending,fresh_quote,publish,BOUNDARY,STEP


def utc(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()*1000)


@pytest.mark.parametrize("time,expected",[
    ("2026-10-05T03:29:59.999",False),("2026-10-05T03:30:00",True),
    ("2026-10-05T04:00:00",True),("2026-10-05T17:00:00",True),
    ("2026-10-05T17:29:59.999",True),("2026-10-05T17:30:00",False),
    ("2026-10-05T18:30:00",False),("2026-10-06T03:30:00",True)])
def test_ist_open_closed_half_open_boundaries(time,expected):
    assert operating.inside(utc(time)) is expected


def test_registered_policy_and_next_open_crosses_ist_midnight(monkeypatch):
    monkeypatch.setattr(get_settings(),"signal_session_enabled",True)
    operating.check_policy()
    for time in ("2026-10-05T17:30:00","2026-10-05T18:30:00","2026-10-06T02:00:00"):
        assert operating.session_view(utc(time))["next_open_at"]==utc("2026-10-06T03:30:00")
    assert operating.session_view(utc("2026-10-06T03:30:00"))["next_open_at"] is None
    assert not operating.allowed(utc("2026-10-06T03:00:00"),utc("2026-10-06T04:00:00"))
    assert not operating.allowed(utc("2026-10-05T17:00:00"),utc("2026-10-05T17:30:00"))
    assert operating.allowed(utc("2026-10-05T17:00:00"),utc("2026-10-05T17:00:01"))


def test_closed_session_skips_before_quote_and_does_not_replay_at_next_open(state,monkeypatch):
    seed(state);identity=pending(state)
    monkeypatch.setattr(get_settings(),"signal_session_enabled",True)
    state.clock[0]=utc("2026-10-05T17:30:00")
    class NoNetwork:
        async def quote(self,*args):
            pytest.fail("Closed-session evaluation must not request quotes")
    asyncio.run(SignalWorker(NoNetwork()).process(identity))
    with state.sessions() as session:
        row=session.get(SignalDecision,identity)
        assert (row.outcome,row.reason)==("SKIPPED","OUTSIDE_SIGNAL_SESSION")
    state.clock[0]=utc("2026-10-06T04:00:01")
    asyncio.run(SignalWorker(NoNetwork()).process(identity))
    with state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SignalPlan))==0


def test_quote_returning_after_close_cannot_publish(state,monkeypatch):
    seed(state);identity=pending(state)
    monkeypatch.setattr(get_settings(),"signal_session_enabled",True)
    monkeypatch.setattr(operating,"inside",lambda now: now<state.clock[0]+100)
    with state.sessions.begin() as session:
        assert evaluate_decision(session,session.get(SignalDecision,identity),state.clock[0])
    with state.sessions.begin() as session:
        evaluate_decision(session,session.get(SignalDecision,identity),state.clock[0]+101,fresh_quote(state))
        assert session.get(SignalDecision,identity).reason=="OUTSIDE_SIGNAL_SESSION"
        assert session.scalar(select(func.count()).select_from(SignalPlan))==0


def test_operating_policy_is_frozen_with_real_engine_plan_without_financial_rule_edits(state,monkeypatch):
    seed(state);identity=pending(state)
    monkeypatch.setattr(get_settings(),"signal_session_enabled",True)
    # This fixture boundary is inside the actual IST session.
    assert operating.inside(BOUNDARY)
    publish(state,identity)
    with state.sessions() as session:
        plan=session.get(SignalPlan,identity)
        assert plan.plan_json["operating_session"]==operating.policy_evidence()==plan.evidence_json["operating_session"]
        from decimal import Decimal as D
        assert D(plan.plan_json["entry"])-D(plan.plan_json["stop"])==D(plan.plan_json["risk_distance"])
        assert D(plan.plan_json["target"])-D(plan.plan_json["entry"])==2*D(plan.plan_json["risk_distance"])


def test_closed_session_cursor_advances_and_expiry_still_runs_while_health_remains_ready(state,monkeypatch):
    seed(state);identity=pending(state);publish(state,identity)
    with state.sessions.begin() as session:
        session.add(EngineCursor(symbol="BTCUSDT",strategy="EMA-PULLBACK-ATR-v1",last_open_time=BOUNDARY-2*STEP,initialized_at=BOUNDARY))
    monkeypatch.setattr(get_settings(),"signal_session_enabled",True)
    monkeypatch.setattr(operating,"inside",lambda now: False)
    state.clock[0]+=300_000
    with state.sessions.begin() as session:
        discover(session,state.clock[0]);expire_slots(session,state.clock[0])
        assert session.get(EngineCursor,("BTCUSDT","EMA-PULLBACK-ATR-v1")).last_open_time==BOUNDARY-STEP
        assert session.scalar(select(SignalSlot)) is None
        engine=session.get(EngineStatus,"engine");engine.state,engine.updated_at="session-paused",state.clock[0]
        # Collector heartbeat must also be current for readiness.
        from app.models import CollectorStatus
        collector=session.get(CollectorStatus,"collector");collector.updated_at=collector.last_event_at=state.clock[0]
        health=engine_health(session)
        assert health["running"] and health["ready"] and not health["session"]["open"]
