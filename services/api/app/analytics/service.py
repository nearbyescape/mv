"""Observational V2 performance analytics.

Nothing in this module is imported by the signal engine.  It consumes immutable
published plans and completed market data after publication.
"""
from dataclasses import dataclass
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN
from sqlalchemy import func, select

from mv_strategy.indicators import PRECISION
from app.models import (
    Candle,
    DecisionOpportunity,
    SignalDecision,
    SignalEvent,
    SignalOutcome,
    SignalPlan,
)

V2_STRATEGY = "MV-TREND-DUAL-v2"
MINUTE_MS = 60_000
HOUR_MS = 3_600_000
DECISION_WINDOW_HOURS = 6
MILESTONES = (
    (D("0.5"), "favorable_050_at"),
    (D("1.0"), "favorable_100_at"),
    (D("1.5"), "favorable_150_at"),
    (D("2.0"), "favorable_200_at"),
)
ADVERSE_MILESTONES = (
    (D("0.5"), "adverse_050_at"),
    (D("1.0"), "adverse_100_at"),
)


@dataclass(frozen=True)
class MinuteBar:
    open_time: int
    close_time: int
    open: D
    high: D
    low: D
    close: D
    volume: D

    def validate(self):
        if (
            type(self.open_time) is not int
            or self.open_time < 0
            or self.open_time % MINUTE_MS
            or self.close_time != self.open_time + MINUTE_MS - 1
        ):
            raise ValueError("Invalid 1m observation boundaries")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(not isinstance(v, D) or not v.is_finite() for v in values):
            raise ValueError("Observation values must be finite Decimals")
        if (
            min(values[:4]) <= 0
            or self.volume < 0
            or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high
        ):
            raise ValueError("Invalid 1m observation OHLCV")


def number(value, name="value"):
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an exact decimal string")
    result = D(value)
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def first_full_minute(published_at):
    if type(published_at) is not int or published_at < 0:
        raise ValueError("Invalid publication time")
    return ((published_at + MINUTE_MS - 1) // MINUTE_MS) * MINUTE_MS


def seed_signal_outcomes(session, now):
    rows = session.scalars(
        select(SignalPlan)
        .outerjoin(SignalOutcome, SignalOutcome.signal_id == SignalPlan.id)
        .where(
            SignalPlan.strategy == V2_STRATEGY,
            SignalOutcome.signal_id.is_(None),
        )
        .order_by(SignalPlan.created_at, SignalPlan.id)
        .limit(500)
    )
    count = 0
    for plan in rows:
        payload = plan.plan_json
        direction = payload.get("direction")
        setup_type = payload.get("setup_type")
        regime = payload.get("trend_regime")
        if direction not in ("long", "short"):
            raise ValueError("Published V2 plan has invalid direction")
        if setup_type not in ("pullback_continuation", "momentum_breakout"):
            raise ValueError("Published V2 plan has invalid setup type")
        if regime not in ("established", "emerging"):
            raise ValueError("Published V2 plan has invalid trend regime")
        entry = number(payload.get("entry"), "entry")
        stop = number(payload.get("stop"), "stop")
        target = number(payload.get("target"), "target")
        risk = number(payload.get("risk_distance"), "risk_distance")
        target_r = number(payload.get("reward_risk"), "reward_risk")
        atr = number(payload.get("frozen_atr"), "frozen_atr")
        geometry = stop < entry < target if direction == "long" else target < entry < stop
        if risk <= 0 or atr <= 0 or target_r <= 0 or not geometry:
            raise ValueError("Published V2 plan has invalid analytics geometry")
        session.add(
            SignalOutcome(
                signal_id=plan.id,
                symbol=plan.symbol,
                direction=direction,
                setup_type=setup_type,
                trend_regime=regime,
                published_at=plan.created_at,
                first_observed_minute=first_full_minute(plan.created_at),
                last_minute_open_time=None,
                entry=str(entry),
                stop=str(stop),
                target=str(target),
                risk_distance=str(risk),
                target_r=str(target_r),
                frozen_atr=str(atr),
                status="open",
                terminal_at=None,
                conservative_r=None,
                mfe_r="0",
                mae_r="0",
                favorable_050_at=None,
                favorable_100_at=None,
                favorable_150_at=None,
                favorable_200_at=None,
                adverse_050_at=None,
                adverse_100_at=None,
                intrabar_ambiguous=False,
                source_revised=False,
                observed_bars=0,
                updated_at=now,
                error_code=None,
            )
        )
        count += 1
    return count


def seed_decision_opportunities(session, now):
    rows = session.scalars(
        select(SignalDecision)
        .outerjoin(DecisionOpportunity, DecisionOpportunity.decision_id == SignalDecision.id)
        .where(
            SignalDecision.strategy == V2_STRATEGY,
            SignalDecision.outcome == "NO_SETUP",
            DecisionOpportunity.decision_id.is_(None),
        )
        .order_by(SignalDecision.source_open_time, SignalDecision.id)
        .limit(1000)
    )
    count = 0
    for decision in rows:
        evidence = decision.evidence_json or {}
        source = evidence.get("source") or {}
        ohlcv = source.get("ohlcv") or {}
        close = ohlcv.get("close")
        atr = source.get("atr")
        boundary = source.get("close_boundary")
        if not isinstance(boundary, int) or not isinstance(close, str) or not isinstance(atr, str):
            continue
        close_d, atr_d = number(close, "source close"), number(atr, "source atr")
        if close_d <= 0 or atr_d <= 0:
            continue
        session.add(
            DecisionOpportunity(
                decision_id=decision.id,
                symbol=decision.symbol,
                reason=decision.reason,
                direction=decision.direction if decision.direction in ("long", "short") else None,
                source_open_time=decision.source_open_time,
                observed_from=boundary,
                observed_until=boundary + DECISION_WINDOW_HOURS * HOUR_MS,
                anchor_close=str(close_d),
                frozen_atr=str(atr_d),
                max_up_atr="0",
                max_down_atr="0",
                observed_bars=0,
                status="open",
                updated_at=now,
            )
        )
        count += 1
    return count


def apply_minute(outcome, bar):
    bar.validate()
    if outcome.status != "open":
        return False
    if bar.open_time < outcome.first_observed_minute:
        raise ValueError("Observation predates the first uncontaminated minute")
    if outcome.last_minute_open_time is not None and bar.open_time <= outcome.last_minute_open_time:
        return False
    if outcome.last_minute_open_time is not None and bar.open_time != outcome.last_minute_open_time + MINUTE_MS:
        raise ValueError("Non-contiguous 1m outcome observations")

    entry = number(outcome.entry, "entry")
    risk = number(outcome.risk_distance, "risk_distance")
    target_r = number(outcome.target_r, "target_r")
    if risk <= 0 or target_r <= 0:
        raise ValueError("Invalid frozen outcome risk")

    with localcontext() as ctx:
        ctx.prec, ctx.rounding = PRECISION, ROUND_HALF_EVEN
        if outcome.direction == "long":
            favorable = max(bar.high - entry, D(0)) / risk
            adverse = max(entry - bar.low, D(0)) / risk
        elif outcome.direction == "short":
            favorable = max(entry - bar.low, D(0)) / risk
            adverse = max(bar.high - entry, D(0)) / risk
        else:
            raise ValueError("Invalid outcome direction")

        outcome.mfe_r = str(max(number(outcome.mfe_r, "mfe_r"), favorable))
        outcome.mae_r = str(max(number(outcome.mae_r, "mae_r"), adverse))

        for threshold, field in MILESTONES:
            if getattr(outcome, field) is None and favorable >= threshold:
                setattr(outcome, field, bar.close_time)
        for threshold, field in ADVERSE_MILESTONES:
            if getattr(outcome, field) is None and adverse >= threshold:
                setattr(outcome, field, bar.close_time)

        stop_hit = adverse >= D(1)
        target_hit = favorable >= target_r
        if stop_hit and target_hit:
            outcome.status = "ambiguous"
            outcome.terminal_at = bar.close_time
            outcome.conservative_r = "-1"
            outcome.intrabar_ambiguous = True
        elif stop_hit:
            outcome.status = "stop"
            outcome.terminal_at = bar.close_time
            outcome.conservative_r = "-1"
        elif target_hit:
            outcome.status = "target"
            outcome.terminal_at = bar.close_time
            outcome.conservative_r = str(target_r)

    outcome.last_minute_open_time = bar.open_time
    outcome.observed_bars += 1
    outcome.updated_at = bar.close_time
    outcome.error_code = None
    return True


def mark_source_revisions(session, now):
    rows = list(
        session.execute(
            select(SignalEvent.signal_id, func.min(SignalEvent.created_at))
            .join(SignalOutcome, SignalOutcome.signal_id == SignalEvent.signal_id)
            .where(SignalEvent.type == "source-revised")
            .group_by(SignalEvent.signal_id)
        )
    )
    changed = 0
    for signal_id, revised_at in rows:
        outcome = session.get(SignalOutcome, signal_id)
        if outcome is None or outcome.source_revised:
            continue
        outcome.source_revised = True
        outcome.updated_at = now
        if outcome.status == "open":
            outcome.status = "source_revised"
            outcome.terminal_at = revised_at
            outcome.conservative_r = None
        changed += 1
    return changed


def update_decision_opportunities(session, now):
    rows = session.scalars(
        select(DecisionOpportunity)
        .where(DecisionOpportunity.status == "open")
        .order_by(DecisionOpportunity.observed_from)
        .limit(1000)
    )
    changed = 0
    for row in rows:
        candles = list(
            session.scalars(
                select(Candle)
                .where(
                    Candle.symbol == row.symbol,
                    Candle.timeframe == "1h",
                    Candle.open_time >= row.observed_from,
                    Candle.open_time < row.observed_until,
                )
                .order_by(Candle.open_time)
            )
        )
        if not candles:
            continue
        anchor, atr = number(row.anchor_close, "anchor close"), number(row.frozen_atr, "frozen atr")
        up = D(0)
        down = D(0)
        for candle in candles:
            up = max(up, (number(candle.high, "candle high") - anchor) / atr)
            down = max(down, (anchor - number(candle.low, "candle low")) / atr)
        row.max_up_atr = str(max(D(0), up))
        row.max_down_atr = str(max(D(0), down))
        row.observed_bars = len(candles)
        row.updated_at = now
        if len(candles) >= DECISION_WINDOW_HOURS:
            expected = [row.observed_from + i * HOUR_MS for i in range(DECISION_WINDOW_HOURS)]
            if [c.open_time for c in candles[:DECISION_WINDOW_HOURS]] == expected:
                row.status = "complete"
        changed += 1
    return changed


def _before(favorable_at, stop_at):
    return favorable_at is not None and (stop_at is None or favorable_at < stop_at)


def _summary(rows):
    rows = list(rows)
    observed = [r for r in rows if r.observed_bars > 0]
    resolved = [r for r in rows if r.status in ("target", "stop", "ambiguous")]
    positive = sum((number(r.conservative_r) for r in resolved if r.conservative_r and number(r.conservative_r) > 0), D(0))
    negative = sum((number(r.conservative_r) for r in resolved if r.conservative_r and number(r.conservative_r) < 0), D(0))
    total_r = positive + negative
    one_r = sum(_before(r.favorable_100_at, r.adverse_100_at) for r in observed)
    two_r = sum(_before(r.favorable_200_at, r.adverse_100_at) for r in observed)
    return {
        "signals": len(rows),
        "observed": len(observed),
        "open": sum(r.status == "open" for r in rows),
        "target": sum(r.status == "target" for r in rows),
        "stop": sum(r.status == "stop" for r in rows),
        "ambiguous": sum(r.status == "ambiguous" for r in rows),
        "source_revised": sum(r.status == "source_revised" for r in rows),
        "resolved": len(resolved),
        "target_rate": str(D(sum(r.status == "target" for r in resolved)) / len(resolved)) if resolved else None,
        "expectancy_r": str(total_r / len(resolved)) if resolved else None,
        "profit_factor": str(positive / -negative) if negative else None,
        "one_r_before_stop": one_r,
        "two_r_before_stop": two_r,
        "one_r_before_stop_rate": str(D(one_r) / len(observed)) if observed else None,
        "two_r_before_stop_rate": str(D(two_r) / len(observed)) if observed else None,
        "average_mfe_r": str(sum((number(r.mfe_r) for r in observed), D(0)) / len(observed)) if observed else None,
        "average_mae_r": str(sum((number(r.mae_r) for r in observed), D(0)) / len(observed)) if observed else None,
    }


def outcome_view(row):
    return {
        "signal_id": row.signal_id,
        "symbol": row.symbol,
        "direction": row.direction,
        "setup_type": row.setup_type,
        "trend_regime": row.trend_regime,
        "published_at": row.published_at,
        "status": row.status,
        "terminal_at": row.terminal_at,
        "entry": row.entry,
        "stop": row.stop,
        "target": row.target,
        "risk_distance": row.risk_distance,
        "target_r": row.target_r,
        "frozen_atr": row.frozen_atr,
        "mfe_r": row.mfe_r,
        "mae_r": row.mae_r,
        "favorable_050_at": row.favorable_050_at,
        "favorable_100_at": row.favorable_100_at,
        "favorable_150_at": row.favorable_150_at,
        "favorable_200_at": row.favorable_200_at,
        "adverse_050_at": row.adverse_050_at,
        "adverse_100_at": row.adverse_100_at,
        "one_r_before_stop": _before(row.favorable_100_at, row.adverse_100_at),
        "two_r_before_stop": _before(row.favorable_200_at, row.adverse_100_at),
        "intrabar_ambiguous": row.intrabar_ambiguous,
        "source_revised": row.source_revised,
        "observed_bars": row.observed_bars,
        "conservative_r": row.conservative_r,
        "updated_at": row.updated_at,
        "error_code": row.error_code,
    }


def performance_summary(session):
    outcomes = list(
        session.scalars(
            select(SignalOutcome).order_by(SignalOutcome.published_at, SignalOutcome.signal_id)
        )
    )
    cohorts = []
    for setup_type in ("pullback_continuation", "momentum_breakout"):
        for direction in ("long", "short"):
            rows = [r for r in outcomes if r.setup_type == setup_type and r.direction == direction]
            cohorts.append({"setup_type": setup_type, "direction": direction, **_summary(rows)})

    symbols = sorted({r.symbol for r in outcomes})
    by_symbol = []
    for symbol in symbols:
        rows = [r for r in outcomes if r.symbol == symbol]
        by_symbol.append({"symbol": symbol, **_summary(rows)})

    decisions = list(
        session.scalars(
            select(SignalDecision)
            .where(SignalDecision.strategy == V2_STRATEGY)
            .order_by(SignalDecision.updated_at)
        )
    )
    blocker_counts = {}
    for decision in decisions:
        if decision.outcome in ("NO_SETUP", "REJECTED", "EXPIRED"):
            key = decision.reason
            blocker_counts[key] = blocker_counts.get(key, 0) + 1

    opportunities = list(
        session.scalars(
            select(DecisionOpportunity)
            .where(DecisionOpportunity.status == "complete")
            .order_by(DecisionOpportunity.reason, DecisionOpportunity.decision_id)
        )
    )
    missed = []
    for reason in sorted({r.reason for r in opportunities}):
        rows = [r for r in opportunities if r.reason == reason]
        missed.append(
            {
                "reason": reason,
                "decisions": len(rows),
                "average_max_up_atr": str(sum((number(r.max_up_atr) for r in rows), D(0)) / len(rows)),
                "average_max_down_atr": str(sum((number(r.max_down_atr) for r in rows), D(0)) / len(rows)),
                "moves_up_ge_2atr": sum(number(r.max_up_atr) >= 2 for r in rows),
                "moves_down_ge_2atr": sum(number(r.max_down_atr) >= 2 for r in rows),
            }
        )

    total = len(outcomes)
    milestones = (25, 50, 100, 200, 300)
    next_milestone = next((m for m in milestones if total < m), None)
    return {
        "strategy": V2_STRATEGY,
        "method": "reference-plan analytics; not exchange fills or account P&L",
        "minute_observation": "first full completed Binance 1m candle at/after publication; pre-publication portion of a minute is never used",
        "ambiguous_policy": "if stop and target occur in the same 1m candle, status is ambiguous and conservative reference result is -1R",
        "overall": _summary(outcomes),
        "cohorts": cohorts,
        "by_symbol": by_symbol,
        "decision_blockers": [
            {"reason": reason, "count": count}
            for reason, count in sorted(blocker_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
        "missed_opportunities_6h": missed,
        "next_review_milestone": next_milestone,
        "completed_decision_windows": len(opportunities),
    }
