import asyncio
from dataclasses import replace
from decimal import Decimal as D
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mv_strategy import Bar, INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import STRATEGY_ID as V1_STRATEGY_ID, Quote, canonical_hash
from mv_strategy.strategy_v3 import LIVE_STRATEGY_ID as STRATEGY_ID, live_decision_id as decision_id
from app.database import Base, get_session
from app.main import app
from app.market import views
from app.market.binance import RateLimited
from app.market.store import apply_bars
from app.models import Candle, CollectorStatus, EngineCursor, EngineStatus, SignalDecision, SignalPlan, SignalSlot, SignalEvent, MarketContract, WatchlistItem
from app.signals import service, worker
from app.signals.service import discover, evaluate_decision, expire_slots, signal_view, slot_action, check_source_revisions
from app.signals.worker import SignalWorker
from test_binance import contract

BOUNDARY = 1791046800000
STEP = INTERVAL_MS["1h"]
AUTH = {"Authorization": "Bearer mv-local-preview-only"}


@pytest.fixture
def state(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    clock = [BOUNDARY + 1000]
    for module in (service, views, worker):
        monkeypatch.setattr(module, "now_ms", lambda: clock[0])
    monkeypatch.setattr(worker, "Session", sessions)
    yield SimpleNamespace(sessions=sessions, clock=clock)
    engine.dispose()


def source_bars(count, timeframe, last_open, direction, pullback=False):
    step = INTERVAL_MS[timeframe]
    result = []
    for i in range(count):
        close = D(100) + D(i) / 5 if direction == "long" else D(300) - D(i) / 5
        if pullback and i == 499:
            close += -D("2.2") if direction == "long" else D("2.2")
        opening = result[-1].close if result else close
        time = last_open - (count - 1 - i) * step
        result.append(Bar(time, time + step - 1, opening, max(opening, close) + 1, min(opening, close) - 1, close, D(10)))
    return result


def seed(state, direction="long", confirmation_count=500, initial_count=501):
    source = source_bars(501, "1h", BOUNDARY - STEP, direction, True)
    confirmation = source_bars(500, "4h", confirmation_open_time(BOUNDARY), direction)
    metadata = contract()
    metadata["filters"][0].update({"minPrice": "0.0", "maxPrice": "10000"})
    with state.sessions.begin() as session:
        session.add(WatchlistItem(symbol="BTCUSDT", sort_order=0))
        session.add(MarketContract(symbol="BTCUSDT", valid=True, reason="verified fixture", checked_at=state.clock[0], metadata_json=metadata))
        session.add(CollectorStatus(id="collector", state="streaming", updated_at=state.clock[0], last_event_at=state.clock[0], clock_offset_ms=0, reconnects=0))
        session.add(EngineStatus(id="engine", state="running", updated_at=state.clock[0]))
        apply_bars(session, "BTCUSDT", "1h", source[:initial_count], state.clock[0])
        apply_bars(session, "BTCUSDT", "4h", confirmation[:confirmation_count], state.clock[0])
    return source, confirmation


def pending(state):
    identity = decision_id("BTCUSDT", BOUNDARY - STEP)
    with state.sessions.begin() as session:
        session.add(SignalDecision(id=identity, symbol="BTCUSDT", strategy=STRATEGY_ID, source_open_time=BOUNDARY - STEP, outcome="PENDING", reason="test", updated_at=state.clock[0] - 2000, expires_at=BOUNDARY + 300_000, evidence_json={}))
    return identity


def fresh_quote(state):
    return Quote("BTCUSDT", D("200.0"), D("200.1"), D(1), D(2), state.clock[0] - 100, state.clock[0])


def publish(state, identity):
    with state.sessions.begin() as session:
        row = session.get(SignalDecision, identity)
        assert evaluate_decision(session, row, state.clock[0]) is not None
    with state.sessions.begin() as session:
        evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0], fresh_quote(state))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).outcome == "PUBLISHED"


@pytest.mark.parametrize("direction", ["long", "short"])
def test_atomic_publication_dedup_and_frozen_evidence_on_real_indicator_history(state, direction):
    seed(state, direction)
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        plan = session.get(SignalPlan, identity)
        frozen = json.dumps(plan.plan_json, sort_keys=True)
        assert plan.plan_json["direction"] == direction
        assert canonical_hash(plan.evidence_json) == plan.evidence_hash
        assert session.get(SignalDecision, identity).evidence_json == plan.evidence_json
        assert plan.plan_json["evidence_hash"] == plan.evidence_hash
        assert isinstance(plan.plan_json["stop"], str)
        assert signal_view(session, plan, state.clock[0])["entry_actionable"] is True
        assert session.get(SignalSlot, ("BTCUSDT", STRATEGY_ID)).signal_id == identity
        assert evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0], fresh_quote(state)) is None
        slot_action(session, plan, "hold", state.clock[0], "Operator reported held")
        slot_action(session, plan, "hold", state.clock[0], "Retry")
    state.clock[0] += 300_000
    with state.sessions.begin() as session:
        expire_slots(session, state.clock[0])
        assert session.get(SignalSlot, ("BTCUSDT", STRATEGY_ID)).state == "held"
        assert signal_view(session, session.get(SignalPlan, identity), state.clock[0])["status"] == "held"
        slot_action(session, session.get(SignalPlan, identity), "release", state.clock[0], "Operator released")
        slot_action(session, session.get(SignalPlan, identity), "release", state.clock[0], "Retry")
        assert json.dumps(session.get(SignalPlan, identity).plan_json, sort_keys=True) == frozen
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 1
        assert list(session.scalars(select(SignalEvent.type).order_by(SignalEvent.created_at))) == ["published", "held", "released"]


def test_failed_commit_rolls_back_plan_slot_event_and_decision(state):
    seed(state)
    identity = pending(state)
    with pytest.raises(RuntimeError, match="crash"):
        with state.sessions.begin() as session:
            evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0], fresh_quote(state))
            session.flush()
            raise RuntimeError("crash before commit")
    with state.sessions() as session:
        for model in (SignalPlan, SignalSlot, SignalEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.get(SignalDecision, identity).outcome == "PENDING"
    publish(state, identity)


def test_exact_4h_arrival_is_waited_for_not_substituted_with_an_older_bar(state):
    _, confirmation = seed(state, confirmation_count=499)
    identity = pending(state)
    with state.sessions.begin() as session:
        assert evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0]) is None
        assert session.get(SignalDecision, identity).reason == "WAITING_EXPECTED_4H"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0
        apply_bars(session, "BTCUSDT", "4h", [confirmation[-1]], state.clock[0])
    publish(state, identity)


def test_expired_recovery_never_requests_a_quote_or_publishes(state):
    seed(state)
    identity = pending(state)
    state.clock[0] = BOUNDARY + 300_000
    class NoQuote:
        async def quote(self, *args):
            pytest.fail("Expired setup must not fetch a quote")
    asyncio.run(SignalWorker(NoQuote()).process(identity))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).outcome == "EXPIRED"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0


def test_stale_quote_retries_then_publishes_once(state):
    seed(state)
    identity = pending(state)
    class Quotes:
        stale = True
        async def quote(self, *args):
            quote = fresh_quote(state)
            return replace(quote, time=state.clock[0] - 5001) if self.stale else quote
    quotes = Quotes()
    engine = SignalWorker(quotes)
    asyncio.run(engine.process(identity))
    with state.sessions() as session:
        row = session.get(SignalDecision, identity)
        assert row.outcome == "PENDING" and row.reason == "STALE_OR_FUTURE_QUOTE"
        assert row.evidence_json["quote"]["time"] == state.clock[0] - 5001
    quotes.stale = False
    asyncio.run(engine.process(identity))
    asyncio.run(engine.process(identity))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).outcome == "PUBLISHED"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 1


def test_source_correction_during_quote_fetch_is_retried_before_publication(state):
    source, _ = seed(state)
    identity = pending(state)
    class CorrectDuringQuote:
        async def quote(self, *args):
            corrected = replace(source[-1], close=source[-1].close + D("0.1"))
            with state.sessions.begin() as session:
                apply_bars(session, "BTCUSDT", "1h", [corrected], state.clock[0])
            return fresh_quote(state)
    asyncio.run(SignalWorker(CorrectDuringQuote()).process(identity))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).reason == "SOURCE_CHANGED_DURING_QUOTE"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0
    publish(state, identity)


@pytest.mark.parametrize("held", [False, True])
def test_post_publication_correction_withdraws_setup_without_mutating_levels(state, held):
    source, _ = seed(state)
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        plan = session.get(SignalPlan, identity)
        original = json.dumps(plan.plan_json, sort_keys=True)
        if held:
            slot_action(session, plan, "hold", state.clock[0], "held")
        corrected = replace(source[-1], close=source[-1].close + D("0.1"))
        apply_bars(session, "BTCUSDT", "1h", [corrected], state.clock[0])
        check_source_revisions(session, state.clock[0])
    with state.sessions.begin() as session:
        check_source_revisions(session, state.clock[0])
        plan = session.get(SignalPlan, identity)
        view = signal_view(session, plan, state.clock[0])
        assert view["status"] == "withdrawn" and view["entry_actionable"] is False
        assert json.dumps(plan.plan_json, sort_keys=True) == original
        assert sum(event["type"] == "source-revised" for event in view["events"]) == 1
        assert (session.get(SignalSlot, ("BTCUSDT", STRATEGY_ID)) is not None) is held


def test_unaccepted_setup_expires_once_and_cannot_be_marked_held(state):
    seed(state)
    identity = pending(state)
    publish(state, identity)
    state.clock[0] = BOUNDARY + 300_000
    with state.sessions.begin() as session:
        expire_slots(session, state.clock[0])
        expire_slots(session, state.clock[0])
        assert session.get(SignalSlot, ("BTCUSDT", STRATEGY_ID)) is None
        view = signal_view(session, session.get(SignalPlan, identity), state.clock[0])
        assert view["status"] == "expired" and view["entry_actionable"] is False
        assert sum(e["type"] == "expired" for e in view["events"]) == 1
        with pytest.raises(ValueError, match="expired"):
            slot_action(session, session.get(SignalPlan, identity), "hold", state.clock[0], "late")


def test_held_slot_blocks_new_candidate_and_database_enforces_unique_source_and_slot(state):
    seed(state)
    identity = pending(state)
    old = "a" * 64
    with state.sessions.begin() as session:
        session.add(SignalDecision(id=old, symbol="BTCUSDT", strategy=STRATEGY_ID, source_open_time=BOUNDARY - 2 * STEP, outcome="PUBLISHED", reason="fixture", updated_at=state.clock[0], expires_at=BOUNDARY - STEP + 300_000, evidence_json={}))
        session.flush()
        session.add(SignalPlan(id=old, symbol="BTCUSDT", strategy=STRATEGY_ID, created_at=BOUNDARY - STEP, expires_at=BOUNDARY - STEP + 300_000, plan_json={}, evidence_json={}, evidence_hash="b" * 64))
        session.flush()
        session.add(SignalSlot(symbol="BTCUSDT", strategy=STRATEGY_ID, signal_id=old, state="held"))
    with state.sessions.begin() as session:
        evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0], fresh_quote(state))
        assert session.get(SignalDecision, identity).reason == "ACTIVE_SIGNAL_OR_HELD_POSITION"
        assert session.get(SignalDecision, identity).outcome == "REJECTED"
    with pytest.raises(IntegrityError):
        with state.sessions.begin() as session:
            session.add(SignalSlot(symbol="BTCUSDT", strategy=STRATEGY_ID, signal_id=old, state="reserved"))
    with pytest.raises(IntegrityError):
        with state.sessions.begin() as session:
            session.add(SignalDecision(id="c" * 64, symbol="BTCUSDT", strategy=STRATEGY_ID, source_open_time=BOUNDARY - STEP, outcome="PENDING", reason="duplicate", updated_at=state.clock[0], expires_at=BOUNDARY + 300_000, evidence_json={}))


def test_alt_signal_btc_regime_veto_is_directional_and_uses_completed_context(state):
    seed(state, "long")
    with state.sessions() as session:
        source_open = BOUNDARY - STEP
        reason, evidence = service.btc_regime_guard(session, "ETHUSDT", "short", source_open)
        assert reason == "BTC_REGIME_CONTRADICTION"
        assert evidence["state"] == "bullish"
        assert evidence["passed"] is False
        assert evidence["source_1h"]["open_time"] == source_open
        assert evidence["confirmation_4h"]["open_time"] == confirmation_open_time(BOUNDARY)

        reason, evidence = service.btc_regime_guard(session, "ETHUSDT", "long", source_open)
        assert reason is None
        assert evidence["state"] == "bullish"
        assert evidence["passed"] is True


def test_existing_v1_held_slot_blocks_v3_candidate_for_same_symbol(state):
    seed(state)
    identity = pending(state)
    old = "d" * 64
    with state.sessions.begin() as session:
        session.add(SignalDecision(
            id=old,
            symbol="BTCUSDT",
            strategy=V1_STRATEGY_ID,
            source_open_time=BOUNDARY - 2 * STEP,
            outcome="PUBLISHED",
            reason="retained-v1-held",
            updated_at=state.clock[0],
            expires_at=BOUNDARY + 3_600_000,
            evidence_json={},
        ))
        session.flush()
        session.add(SignalPlan(
            id=old,
            symbol="BTCUSDT",
            strategy=V1_STRATEGY_ID,
            created_at=BOUNDARY - STEP,
            expires_at=BOUNDARY + 3_600_000,
            plan_json={},
            evidence_json={},
            evidence_hash="e" * 64,
        ))
        session.flush()
        session.add(SignalSlot(
            symbol="BTCUSDT",
            strategy=V1_STRATEGY_ID,
            signal_id=old,
            state="held",
        ))
    with state.sessions.begin() as session:
        evaluate_decision(session, session.get(SignalDecision, identity), state.clock[0], fresh_quote(state))
        row = session.get(SignalDecision, identity)
        assert (row.outcome, row.reason) == ("REJECTED", "ACTIVE_SIGNAL_OR_HELD_POSITION")
        assert session.scalar(select(func.count()).select_from(SignalPlan).where(SignalPlan.strategy == STRATEGY_ID)) == 0


def test_existing_v1_cursor_cannot_replay_history_when_v3_first_starts(state):
    seed(state)
    with state.sessions.begin() as session:
        checkpoint = session.get(service.IndicatorCheckpoint, ("BTCUSDT", "1h"))
        head = checkpoint.state_json["last_open_time"]
        session.add(EngineCursor(
            symbol="BTCUSDT",
            strategy=V1_STRATEGY_ID,
            last_open_time=head - 20 * STEP,
            initialized_at=BOUNDARY - 20 * STEP,
        ))
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
        v3 = session.get(EngineCursor, ("BTCUSDT", STRATEGY_ID))
        assert v3 is not None
        assert v3.last_open_time == BOUNDARY - STEP
        rows = list(session.scalars(select(SignalDecision).where(SignalDecision.strategy == STRATEGY_ID)))
        assert len(rows) == 1
        assert rows[0].outcome == "BASELINE"
        assert rows[0].reason == "STARTUP_BASELINE_NO_RETROACTIVE_ENTRY"


def test_startup_baseline_and_restart_cursor_never_reseed_or_republish(state):
    state.clock[0] = BOUNDARY - STEP + 1000
    source, _ = seed(state, initial_count=500)
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 1
        assert session.scalar(select(SignalDecision.outcome)) == "BASELINE"
        state.clock[0] = BOUNDARY + 1000
        health = session.get(CollectorStatus, "collector")
        health.updated_at = health.last_event_at = state.clock[0]
        session.get(MarketContract, "BTCUSDT").checked_at = state.clock[0]
        session.get(EngineStatus, "engine").updated_at = state.clock[0]
        apply_bars(session, "BTCUSDT", "1h", [source[-1]], state.clock[0])
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
    identity = decision_id("BTCUSDT", source[-1].open_time)
    publish(state, identity)
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
        assert session.scalar(select(func.count()).select_from(SignalDecision)) == 2
        assert session.get(EngineCursor, ("BTCUSDT", STRATEGY_ID)).last_open_time == source[-1].open_time


def test_first_start_waits_for_fresh_history_then_baselines_even_a_qualifying_latest_bar(state):
    source, _ = seed(state, initial_count=500)
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
        assert session.get(EngineCursor, ("BTCUSDT", STRATEGY_ID)) is None
        apply_bars(session, "BTCUSDT", "1h", [source[-1]], state.clock[0])
    with state.sessions.begin() as session:
        discover(session, state.clock[0])
        assert session.scalar(select(SignalDecision.outcome)) == "BASELINE"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0


def test_quote_response_that_arrives_after_expiry_is_never_published(state):
    seed(state)
    identity = pending(state)
    state.clock[0] = BOUNDARY + 299_000
    with state.sessions.begin() as session:
        health = session.get(CollectorStatus, "collector")
        health.updated_at = health.last_event_at = state.clock[0]
    class SlowQuote:
        async def quote(self, *args):
            state.clock[0] += 2000
            return fresh_quote(state)
    asyncio.run(SignalWorker(SlowQuote()).process(identity))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).outcome == "EXPIRED"
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0


def test_v3_worker_ignores_leftover_v1_pending_decisions(state):
    seed(state)
    legacy_id = "f" * 64
    with state.sessions.begin() as session:
        session.add(SignalDecision(
            id=legacy_id,
            symbol="BTCUSDT",
            strategy=V1_STRATEGY_ID,
            source_open_time=BOUNDARY - STEP,
            outcome="PENDING",
            reason="legacy-pending",
            updated_at=state.clock[0] - 5000,
            expires_at=BOUNDARY + 300_000,
            evidence_json={},
        ))
    class NoQuote:
        async def quote(self, *args):
            pytest.fail("V3 worker must not request a quote for a V1 decision")
    asyncio.run(SignalWorker(NoQuote()).process(legacy_id))
    with state.sessions() as session:
        row = session.get(SignalDecision, legacy_id)
        assert (row.outcome, row.reason, row.attempts) == ("PENDING", "legacy-pending", 0)


def test_changed_v3_financial_contract_is_refused_before_worker_start(state, monkeypatch):
    changed = json.loads(json.dumps(service.LIVE_CONTRACT))
    changed["setups"]["momentum_breakout"]["min_body_atr"] = "0.10"
    monkeypatch.setattr(service, "LIVE_CONTRACT", changed)
    with pytest.raises(ValueError, match="Production V3 financial contract changed"):
        service.check_live_contract()


def test_same_direction_signal_is_suppressed_for_rest_of_ist_session(state):
    seed(state)
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        first = session.get(SignalDecision, identity)
        assert first.direction == "long"
        session.execute(
            __import__("sqlalchemy").delete(SignalSlot).where(SignalSlot.signal_id == identity)
        )
        later_open = first.source_open_time + 2 * STEP
        later_id = decision_id("BTCUSDT", later_open)
        session.add(
            SignalDecision(
                id=later_id,
                symbol="BTCUSDT",
                strategy=STRATEGY_ID,
                source_open_time=later_open,
                direction=None,
                outcome="PENDING",
                reason="test-repeat",
                updated_at=state.clock[0],
                expires_at=later_open + STEP + 300_000,
                evidence_json={},
            )
        )
        # Test the durable session-level guard directly; market context for a
        # future fixture candle is intentionally not fabricated here.
        assert service._same_direction_signal_this_session(
            session, "BTCUSDT", "long", later_open + STEP
        )
        assert not service._same_direction_signal_this_session(
            session, "BTCUSDT", "short", later_open + STEP
        )


def test_rate_limit_is_respected_across_candidates_and_retries(state):
    seed(state)
    identity = pending(state)
    class Limited:
        calls = 0
        async def quote(self, *args):
            self.calls += 1
            raise RateLimited(120)
    public = Limited()
    engine = SignalWorker(public)
    asyncio.run(engine.process(identity))
    asyncio.run(engine.process(identity))
    assert public.calls == 1
    with state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0


def test_large_candidate_batch_refreshes_health_between_slow_quote_operations(state):
    seed(state)
    with state.sessions.begin() as session:
        for i in range(29):
            time=BOUNDARY-STEP-i*STEP
            session.add(SignalDecision(id=decision_id("BTCUSDT",time),symbol="BTCUSDT",strategy=STRATEGY_ID,
                source_open_time=time,outcome="PENDING",reason="controlled backlog",updated_at=state.clock[0]-5000,
                expires_at=BOUNDARY+300_000,evidence_json={}))
    engine=SignalWorker(None)
    observed=[]
    async def delayed_process(identity):
        with state.sessions() as session:
            assert state.clock[0]-session.get(EngineStatus,"engine").updated_at<=15_000
        observed.append(identity)
        state.clock[0]+=8000
        with state.sessions.begin() as session:
            collector=session.get(CollectorStatus,"collector")
            collector.updated_at=collector.last_event_at=state.clock[0]
    engine.process=delayed_process
    asyncio.run(engine.tick())
    assert len(observed)==29
    with state.sessions() as session:
        assert session.get(EngineStatus,"engine").updated_at==state.clock[0]
        assert session.scalar(select(func.count()).select_from(SignalPlan))==0


def test_protected_api_returns_exact_plan_evidence_and_tracks_operator_state(state, monkeypatch):
    seed(state)
    identity = pending(state)
    publish(state, identity)
    import app.main as main
    monkeypatch.setattr(main, "now_ms", lambda: state.clock[0])
    def sessions():
        with state.sessions() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    try:
        with TestClient(app) as client:
            assert client.get("/v1/signals").status_code == 401
            assert client.post(f"/v1/signals/{identity}/slot", json={"action": "hold"}).status_code == 401
            signal = client.get(f"/v1/signals/{identity}", headers=AUTH).json()
            assert signal["status"] == "active" and signal["entry_actionable"] is True
            assert canonical_hash(signal["evidence"]) == signal["evidence_hash"]
            assert client.get("/v1/signals?limit=101", headers=AUTH).status_code == 422
            assert client.get("/v1/signals/missing", headers=AUTH).status_code == 404
            held = client.post(f"/v1/signals/{identity}/slot", headers=AUTH, json={"action": "hold"})
            assert held.status_code == 200 and held.json()["slot"] == "held"
            released = client.post(f"/v1/signals/{identity}/slot", headers=AUTH, json={"action": "release"})
            assert released.status_code == 200 and released.json()["status"] == "released"
            final = client.get("/v1/signals", headers=AUTH).json()
            assert final["slots"] == [] and final["signals"][0]["entry"] == signal["entry"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize('direction', ['long','short'])
def test_signal_chart_windows_are_bounded_and_do_not_change_frozen_plans(state, direction):
    source,_ = seed(state,direction)
    identity=pending(state)
    publish(state,identity)
    from app.market.signal_chart import signal_chart_view
    later=[replace(source[-1],open_time=source[-1].open_time+i*STEP,close_time=source[-1].close_time+i*STEP) for i in range(1,151)]
    state.clock[0]=later[-1].close_time+1
    with state.sessions.begin() as session:
        apply_bars(session,'BTCUSDT','1h',later,state.clock[0])
    with state.sessions() as session:
        plan=session.get(SignalPlan,identity)
        before=json.dumps(plan.plan_json,sort_keys=True)
        frozen=signal_view(session,plan,state.clock[0])
        original=signal_chart_view(session,frozen,'source')
        latest=signal_chart_view(session,frozen,'latest')
        assert len(original['series']['candles'])==169 and original['source_candle_in_window']
        assert len(latest['series']['candles'])==120 and not latest['source_candle_in_window']
        candle=next(c for c in original['series']['candles'] if c['time']==frozen['source_open_time']//1000)
        assert candle['close']==str(source[-1].close)
        assert original['plan_hash']==frozen['plan_hash'] and not original['source_revised']
        assert not latest['live']  # The collector heartbeat is stale; retained data is never live.
        assert json.dumps(plan.plan_json,sort_keys=True)==before
        assert session.scalar(select(func.count()).select_from(SignalPlan))==1


def test_signal_chart_api_auth_validation_and_corrupt_plan_rejection(state, monkeypatch):
    seed(state)
    identity=pending(state)
    publish(state,identity)
    import app.main as main
    monkeypatch.setattr(main,'now_ms',lambda:state.clock[0])
    def sessions():
        with state.sessions() as session:yield session
    app.dependency_overrides[get_session]=sessions
    try:
        with TestClient(app) as client:
            path=f'/v1/signals/{identity}/chart'
            assert client.get(path).status_code==401
            assert client.get('/v1/signals/missing/chart',headers=AUTH).status_code==404
            assert client.get(path+'?window=all',headers=AUTH).status_code==422
            response=client.get(path,headers=AUTH)
            assert response.status_code==200 and response.json()['source_candle_in_window']
            with state.sessions.begin() as session:
                plan=session.get(SignalPlan,identity)
                plan.plan_json={**plan.plan_json,'entry':'999'}
            assert client.get(path,headers=AUTH).status_code==409
    finally:app.dependency_overrides.clear()


def test_browser_fixture_contract_is_generated_by_backend_publication(state, monkeypatch):
    seed(state)
    identity = pending(state)
    publish(state, identity)
    import app.main as main
    monkeypatch.setattr(main, "now_ms", lambda: state.clock[0])
    def sessions():
        with state.sessions() as session:
            yield session
    app.dependency_overrides[get_session] = sessions
    try:
        with TestClient(app) as client:
            result = client.get("/v1/signals", headers=AUTH).json()
            assert result["signals"][0]["id"] == identity
            assert result["signals"][0]["entry_actionable"] is True
            assert canonical_hash(result["signals"][0]["evidence"]) == result["signals"][0]["evidence_hash"]
            if target := os.environ.get("MV_BROWSER_FIXTURE_OUTPUT"):
                path = Path(target)
                path.parent.mkdir(parents=True, exist_ok=True)
                result["fixture_provenance"] = "Controlled test publication generated by the real backend from synthetic source bars. Not a Binance opportunity."
                path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("failure,reason", [("collector", "COLLECTOR_NOT_LIVE"), ("metadata", "CONTRACT_NOT_VALIDATED"), ("checkpoint", "CHECKPOINT_NOT_ALIGNED"), ("removed", "SYMBOL_REMOVED")])
def test_failed_data_guards_do_not_fetch_entry_quotes(state, failure, reason):
    seed(state)
    identity = pending(state)
    from app.models import IndicatorCheckpoint
    with state.sessions.begin() as session:
        if failure == "collector": session.get(CollectorStatus, "collector").last_event_at -= 30_001
        elif failure == "metadata": session.get(MarketContract, "BTCUSDT").checked_at -= 600_001
        elif failure == "checkpoint":
            row = session.get(IndicatorCheckpoint, ("BTCUSDT", "1h"))
            row.state_json = {**row.state_json, "lineage": "0" * 64}
        else: session.delete(session.get(WatchlistItem, "BTCUSDT"))
    class NoQuote:
        async def quote(self, *args): pytest.fail("Blocked data must not request an entry quote")
    asyncio.run(SignalWorker(NoQuote()).process(identity))
    with state.sessions() as session:
        assert session.get(SignalDecision, identity).reason == reason
        assert session.scalar(select(func.count()).select_from(SignalPlan)) == 0


def test_changed_version_one_risk_contract_is_refused(state, monkeypatch):
    changed = json.loads(json.dumps(service.CONTRACT))
    changed["risk"]["stop_atr_multiple"] = "3"
    monkeypatch.setattr(service, "CONTRACT", changed)
    with pytest.raises(ValueError, match="new strategy version"):
        service.check_contract()


def test_plan_checksum_failure_disables_entry_without_hiding_operator_held_state(state):
    seed(state)
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        plan = session.get(SignalPlan, identity)
        assert signal_view(session, plan, state.clock[0])["integrity_valid"] is True
        plan.plan_json = {**plan.plan_json, "stop": "192.0"}
    with state.sessions() as session:
        view = signal_view(session, session.get(SignalPlan, identity), state.clock[0])
        assert view["integrity_valid"] is False and view["status"] == "integrity-failed"
        assert view["entry_actionable"] is False
