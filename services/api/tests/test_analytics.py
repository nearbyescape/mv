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


def test_published_v4_plan_seeds_observational_row_without_mutating_signal_tables(state):
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
        assert row.strategy == "MV-TREND-DUAL-v4"
        assert row.tp1 is not None and row.tp2 is not None and row.tp3 is not None
        assert row.setup_type in ("pullback_continuation", "momentum_breakout")
        assert row.direction == "long"
        assert row.status == "open"
        assert row.first_observed_minute >= row.published_at
        after = (
            session.scalar(select(func.count()).select_from(SignalPlan)),
            session.scalar(select(func.count()).select_from(SignalDecision)),
        )
        assert after == before


def test_v4_tp3_records_all_milestones_and_weighted_reference_result(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry = D(row.entry)
        risk = D(row.risk_distance)
        tp3 = D(row.tp3)
        bar = minute(
            row.first_observed_minute,
            str(entry),
            str(tp3),
            str(entry - risk * D("0.2")),
            str(tp3),
        )
        assert apply_minute(row, bar)
        assert row.status == "tp3"
        expected = (
            D("0.30") * D(row.tp1_r)
            + D("0.30") * D(row.tp2_r)
            + D("0.40") * D(row.tp3_r)
        )
        assert D(row.conservative_r) == expected
        assert row.favorable_050_at == bar.close_time
        assert row.favorable_100_at == bar.close_time
        assert row.favorable_150_at == bar.close_time
        assert row.favorable_200_at == bar.close_time
        assert row.adverse_100_at is None
        assert D(row.mfe_r) >= D(row.tp3_r)
        assert D(row.mae_r) == D("0.2")


def test_v4_tp1_then_next_minute_breakeven_stop_banks_first_allocation(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry, risk, tp1 = D(row.entry), D(row.risk_distance), D(row.tp1)
        first = minute(
            row.first_observed_minute,
            str(entry),
            str(tp1),
            str(entry - risk * D("0.1")),
            str(tp1),
        )
        apply_minute(row, first)
        assert row.status == "open" and row.favorable_100_at == first.close_time
        second = minute(
            first.open_time + MINUTE_MS,
            str(tp1),
            str(tp1),
            str(entry),
            str(entry),
        )
        apply_minute(row, second)
        assert row.status == "protected_be"
        assert D(row.conservative_r) == D("0.30") * D(row.tp1_r)


def test_v4_tp2_then_next_minute_tp1_stop_protects_runner(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry, risk = D(row.entry), D(row.risk_distance)
        tp1, tp2 = D(row.tp1), D(row.tp2)
        first = minute(
            row.first_observed_minute,
            str(entry),
            str(tp2),
            str(entry - risk * D("0.1")),
            str(tp2),
        )
        apply_minute(row, first)
        assert row.status == "open"
        assert row.favorable_100_at == row.favorable_150_at == first.close_time
        second = minute(
            first.open_time + MINUTE_MS,
            str(tp2),
            str(tp2),
            str(tp1),
            str(tp1),
        )
        apply_minute(row, second)
        assert row.status == "protected_tp1"
        expected = (
            D("0.30") * D(row.tp1_r)
            + D("0.30") * D(row.tp2_r)
            + D("0.40") * D(row.tp1_r)
        )
        assert D(row.conservative_r) == expected


def test_same_minute_original_stop_and_tp1_is_ambiguous_and_conservative_loss(state):
    seed(state, "long")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        row = session.get(SignalOutcome, identity)
        entry = D(row.entry)
        stop = D(row.stop)
        tp1 = D(row.tp1)
        bar = minute(
            row.first_observed_minute,
            str(entry),
            str(tp1),
            str(stop),
            str(entry),
        )
        apply_minute(row, bar)
        assert row.status == "ambiguous"
        assert row.intrabar_ambiguous is True
        assert row.conservative_r == "-1"
        assert row.adverse_100_at == bar.close_time
        assert row.favorable_100_at is None


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
        assert abs(D(row.max_up_atr) - D("3")) < D("1e-25")
        assert abs(D(row.max_down_atr) - D("1.5")) < D("1e-25")


def test_performance_summary_separates_four_setup_direction_cohorts(state):
    seed(state, "short")
    identity = pending(state)
    publish(state, identity)
    with state.sessions.begin() as session:
        seed_signal_outcomes(session, state.clock[0])
        summary = performance_summary(session)
        assert summary["strategy"] == "MV-TREND-DUAL-v4"
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
