from decimal import Decimal as D

from sqlalchemy import func, select

from app.analytics.service import (
    HOUR_MS,
    MINUTE_MS,
    MinuteBar,
    apply_minute,
    mark_source_revisions,
    performance_summary,
    seed_decision_opportunities,
    seed_signal_outcomes,
    update_decision_opportunities,
)
from app.models import (
    Candle,
    DecisionOpportunity,
    SignalDecision,
    SignalEvent,
    SignalOutcome,
    SignalPlan,
)
from app.signals import service
from mv_strategy import Bar
from test_signal_service import BOUNDARY, STEP, pending, publish, seed, state


def minute(open_time, open_, high, low, close):
    return MinuteBar(
        open_time=open_time,
        close_time=open_time + MINUTE_MS - 1,
        open=D(open_),
        high=D(high),
        low=D(low),
        close=D(close),
        volume=D("10"),
    )


def test_published_v2_plan_seeds_observational_row_without_mutating_signal_tables(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        before = (
            session.scalar(select(func.count()).select_from(SignalPlan)),
            session.scalar(select(func.count()).select_from(SignalDecision)),
        )
        assert seed_signal_outcomes(session, state.clock[0]) == 1
        assert seed_signal_outcomes(session, state.clock[0]) == 0
        row = session.get(SignalOutcome, identity)
        assert row is not None
        assert row.setup_type in ("pullback_continuation", "momentum_breakout")
        assert row.direction == "long"
        assert row.status == "open"
        assert row.first_observed_minute >= row.published_at
        after = (
            session.scalar(select(func.count()).select_from(SignalPlan)),
            session.scalar(select(func.count()).select_from(SignalDecision)),
        )
        assert after == before


def test_target_milestones_and_mfe_are_reference_only_and_exact(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry = D(row.entry)
        risk = D(row.risk_distance)
        target = D(row.target)
        bar = minute(
            row.first_observed_minute,
            str(entry),
            str(target),
            str(entry - risk * D("0.2")),
            str(target),
        )
        assert apply_minute(row, bar)
        assert row.status == "target"
        assert D(row.conservative_r) == D(row.target_r)
        assert row.favorable_050_at == bar.close_time
        assert row.favorable_100_at == bar.close_time
        assert row.favorable_150_at == bar.close_time
        assert row.favorable_200_at == bar.close_time
        assert row.adverse_100_at is None
        assert D(row.mfe_r) >= D(row.target_r)
        assert D(row.mae_r) == D("0.2")


def test_same_minute_stop_and_target_is_ambiguous_and_conservative_loss(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry = D(row.entry)
        stop = D(row.stop)
        target = D(row.target)
        bar = minute(
            row.first_observed_minute,
            str(entry),
            str(target),
            str(stop),
            str(entry),
        )
        apply_minute(row, bar)
        assert row.status == "ambiguous"
        assert row.intrabar_ambiguous is True
        assert row.conservative_r == "-1"
        assert row.favorable_200_at == row.adverse_100_at == bar.close_time


def test_source_revision_terminates_only_still_open_analytics(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        session.add(
            SignalEvent(
                id="00000000-0000-0000-0000-000000000001",
                signal_id=identity,
                type="source-revised",
                created_at=state.clock[0] + 100,
                payload_json={},
            )
        )
        assert mark_source_revisions(session, state.clock[0] + 200) == 1
        row = session.get(SignalOutcome, identity)
        assert row.source_revised is True
        assert row.status == "source_revised"
        assert row.conservative_r is None


def test_no_setup_decision_gets_future_only_six_hour_atr_excursion(state):
    seed(state, "long")
    with state.sessions.begin() as session:
        current, previous, confirmation, structure, contract, evidence = service.context_at(
            session, "BTCUSDT", BOUNDARY - STEP
        )
        identity = "9" * 64
        session.add(
            SignalDecision(
                id=identity,
                symbol="BTCUSDT",
                strategy=service.STRATEGY_ID,
                source_open_time=BOUNDARY - STEP,
                direction="long",
                outcome="NO_SETUP",
                reason="NO_PULLBACK_OR_BREAKOUT_TRIGGER",
                updated_at=state.clock[0],
                expires_at=BOUNDARY + 300_000,
                evidence_json=evidence,
            )
        )
        assert seed_decision_opportunities(session, state.clock[0]) == 1

        anchor = D(evidence["source"]["ohlcv"]["close"])
        atr = D(evidence["source"]["atr"])
        bars = []
        for index in range(6):
            open_time = BOUNDARY + index * HOUR_MS
            close = anchor
            bars.append(
                Candle(
                    symbol="BTCUSDT",
                    timeframe="1h",
                    open_time=open_time,
                    close_time=open_time + HOUR_MS - 1,
                    open=str(close),
                    high=str(close + atr * D(index + 1) / 2),
                    low=str(close - atr * D(index + 1) / 4),
                    close=str(close),
                    volume="1",
                    source_hash=f"{index:064d}",
                )
            )
        session.add_all(bars)
        update_decision_opportunities(session, state.clock[0] + 6 * HOUR_MS)
        row = session.get(DecisionOpportunity, identity)
        assert row.status == "complete"
        assert row.observed_bars == 6
        assert D(row.max_up_atr) == D("3")
        assert D(row.max_down_atr) == D("1.5")


def test_performance_summary_separates_four_setup_direction_cohorts(state):
    seed(state, "short")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        summary = performance_summary(session)
        assert summary["strategy"] == "MV-TREND-DUAL-v2"
        assert summary["overall"]["signals"] == 1
        assert len(summary["cohorts"]) == 4
        matching = [
            row
            for row in summary["cohorts"]
            if row["direction"] == "short"
            and row["setup_type"] == session.get(SignalOutcome, identity).setup_type
        ]
        assert matching[0]["signals"] == 1
        assert summary["next_review_milestone"] == 25
        assert "not exchange fills" in summary["method"]
