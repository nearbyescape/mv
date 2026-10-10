"""Read-only V4 versus V5-candidate retrospective on full watchlist scans.

V4 remains production. This module builds no database rows and sends no
signals. It compares the current V4 1H-entry architecture with a V5 research
candidate that keeps V4 4H/1H trend qualification, arms context on a completed
1H candle, and waits for the first qualifying completed 15m trigger before the
next 1H close.

Public Binance USD-M 15m/1m data is used only for historical trigger/outcome
replay. Reference entries use the first 1m open after the completed trigger.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime, time as wall_time
from decimal import Decimal as D, localcontext, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN
import json
from statistics import median
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.database import Session
from app.market.binance import BinancePublic, now_ms
from app.models import Candle, WatchlistItem
from app.research.v4_retrospective import (
    Candidate,
    _active_scaled_count,
    _circuit_paused_scaled,
    btc_timing_reason,
    fetch_minutes,
    replay_scaled,
    simulate_with_active_cap,
)
from app.signals.service import btc_regime_guard, context_at
from mv_strategy import IndicatorState, INTERVAL_MS
from mv_strategy.indicators import PRECISION
from mv_strategy.signals import PlanRejected, PriceFilter, Quote, Snapshot
from mv_strategy.strategy_v3 import (
    BREAKOUT_ENTRY_DRIFT_MAX,
    BREAKOUT_ENTRY_EXTENSION_MAX,
    PULLBACK_ENTRY_DRIFT_MAX,
    PULLBACK_ENTRY_EXTENSION_MAX,
    RECENT_RUN_MAX,
    TP1_ALLOCATION,
    TP1_R,
    TP2_ALLOCATION,
    TP2_R,
    TP3_ALLOCATION,
    TP3_R,
)
from mv_strategy.strategy_v4 import build_plan_v4, evaluate_setup_v4
from mv_strategy.strategy_v5 import (
    CANDIDATE_STRATEGY_ID,
    candidate_id,
    evaluate_context_v5,
    evaluate_trigger_v5,
)

IST = ZoneInfo("Asia/Kolkata")
MINUTE = 60_000
MIN15 = INTERVAL_MS["15m"]
HOUR = INTERVAL_MS["1h"]
OBSERVATION_MS = 4 * HOUR
WARMUP_15M_BARS = 520
V5_ROLLING_CONCENTRATION_MS = HOUR
V5_MAX_SAME_DIRECTION_ROLLING = 2


def ist_session_bounds(day: str) -> tuple[int, int]:
    parsed = datetime.strptime(day, "%Y-%m-%d").date()
    start = datetime.combine(parsed, wall_time(9, 0), IST)
    end = datetime.combine(parsed, wall_time(23, 0), IST)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _price_filter(contract) -> PriceFilter:
    if contract is None:
        raise PlanRejected("MISSING_MARKET_CONTRACT")
    row = next(
        (
            item
            for item in contract.metadata_json.get("filters", [])
            if item.get("filterType") == "PRICE_FILTER"
        ),
        None,
    )
    if not row:
        raise PlanRejected("MISSING_PRICE_FILTER")
    return PriceFilter(
        D(row["tickSize"]),
        D(row["minPrice"]),
        D(row["maxPrice"]),
    )


def _check_value(checks: list[dict], suffix: str) -> D:
    for row in checks:
        if str(row.get("id", "")).endswith("." + suffix) and "value" in row:
            return D(row["value"])
    raise ValueError(f"missing check value: {suffix}")


def _btc_state_map(snapshots: dict[int, Snapshot]) -> dict[int, dict]:
    return {
        open_time: {
            "bar": snap.bar,
            "count": snap.count,
            "ema20": snap.ema20,
            "ema50": snap.ema50,
        }
        for open_time, snap in snapshots.items()
    }


async def _fetch_15m_snapshots(public, symbol: str, session_start: int, end_boundary: int):
    start = session_start - WARMUP_15M_BARS * MIN15
    end_time = end_boundary - 1
    bars = await public.klines(
        symbol,
        "15m",
        start_time=start,
        end_time=end_time,
        limit=1000,
    )
    if not bars or bars[0].open_time != start:
        raise ValueError(
            f"{symbol} 15m history did not start at requested warmup boundary"
        )
    for previous, current in zip(bars, bars[1:]):
        if current.open_time != previous.open_time + MIN15:
            raise ValueError(f"{symbol} 15m history is non-contiguous")

    state = IndicatorState("15m")
    result: dict[int, Snapshot] = {}
    for bar in bars:
        values = state.advance(bar)
        if any(values[key] is None for key in ("ema20", "ema50", "sma200", "atr")):
            continue
        assert state.history_origin is not None
        result[bar.open_time] = Snapshot(
            "15m",
            bar,
            values["ema20"],
            values["ema50"],
            values["sma200"],
            values["atr"],
            state.count,
            state.history_origin,
            state.lineage,
        )
    return result


def _reference_entry(minute_by_open: dict[int, object], boundary: int) -> D | None:
    bar = minute_by_open.get(boundary)
    return D(bar.open) if bar is not None else None


def _v5_reference_plan(
    symbol: str,
    context,
    trigger,
    source_1h: Snapshot,
    trigger_15m: Snapshot,
    entry: D,
    price_filter: PriceFilter,
    published_at: int,
):
    """Build research-only V5 geometry while preserving V4 scaled risk policy."""
    if context.outcome != "ARMED" or context.direction not in ("long", "short"):
        raise PlanRejected("INVALID_V5_CONTEXT")
    if trigger.outcome != "TRIGGER" or trigger.direction != context.direction:
        raise PlanRejected("INVALID_V5_TRIGGER")
    if trigger.trigger_type not in (
        "pullback_continuation_15m",
        "momentum_breakout_15m",
    ):
        raise PlanRejected("INVALID_V5_TRIGGER_TYPE")
    if trigger.recent_run_anchor is None:
        raise PlanRejected("MISSING_RECENT_RUN_ANCHOR")
    if source_1h.atr <= 0 or trigger_15m.atr <= 0:
        raise PlanRejected("NONPOSITIVE_ATR")

    setup_type = (
        "pullback_continuation"
        if trigger.trigger_type == "pullback_continuation_15m"
        else "momentum_breakout"
    )
    drift_limit = (
        PULLBACK_ENTRY_DRIFT_MAX
        if setup_type == "pullback_continuation"
        else BREAKOUT_ENTRY_DRIFT_MAX
    )
    extension_limit = (
        PULLBACK_ENTRY_EXTENSION_MAX
        if setup_type == "pullback_continuation"
        else BREAKOUT_ENTRY_EXTENSION_MAX
    )

    with localcontext() as ctx:
        ctx.prec, ctx.rounding = PRECISION, ROUND_HALF_EVEN
        price_filter.validate()
        if not price_filter.allows(entry):
            raise PlanRejected("REFERENCE_ENTRY_OFF_TICK_OR_BOUNDS")

        drift = abs(entry - trigger_15m.bar.close)
        if drift > drift_limit * trigger_15m.atr:
            raise PlanRejected("MISSED_ENTRY_PRICE_DRIFT")

        sign = D(1) if context.direction == "long" else D(-1)
        entry_extension = sign * (entry - trigger_15m.ema20) / trigger_15m.atr
        if entry_extension <= 0:
            raise PlanRejected("ENTRY_LOST_EMA20_SIDE")
        if entry_extension > extension_limit:
            raise PlanRejected("ENTRY_OVEREXTENDED")

        recent_run_entry_atr = (
            sign * (entry - trigger.recent_run_anchor) / trigger_15m.atr
        )
        if recent_run_entry_atr > RECENT_RUN_MAX:
            raise PlanRejected("RECENT_RUN_OVEREXTENDED")

        upwards = context.direction == "short"
        raw_stop = entry + (
            D(2) * source_1h.atr if upwards else -D(2) * source_1h.atr
        )
        units = (
            (raw_stop - price_filter.minimum) / price_filter.tick
        ).to_integral_value(
            rounding=ROUND_CEILING if upwards else ROUND_FLOOR
        )
        stop = price_filter.minimum + units * price_filter.tick
        risk = abs(entry - stop)
        if risk <= 0:
            raise PlanRejected("INVALID_RISK_GEOMETRY_OR_BOUNDS")

        def target_at(multiple: D):
            raw = entry + (-multiple * risk if upwards else multiple * risk)
            target_units = (
                (raw - price_filter.minimum) / price_filter.tick
            ).to_integral_value(
                rounding=ROUND_CEILING if upwards else ROUND_FLOOR
            )
            return price_filter.minimum + target_units * price_filter.tick

        tp1 = target_at(TP1_R)
        tp2 = target_at(TP2_R)
        tp3 = target_at(TP3_R)

        geometry = (
            stop < entry < tp1 < tp2 < tp3
            if context.direction == "long"
            else tp3 < tp2 < tp1 < entry < stop
        )
        if not geometry or not all(
            price_filter.allows(value)
            for value in (entry, stop, tp1, tp2, tp3)
        ):
            raise PlanRejected("INVALID_RISK_GEOMETRY_OR_BOUNDS")

        tp1_r = abs(tp1 - entry) / risk
        tp2_r = abs(tp2 - entry) / risk
        tp3_r = abs(tp3 - entry) / risk
        return {
            "strategy": CANDIDATE_STRATEGY_ID,
            "risk_policy": "RISK-ATR14-SCALED-TP-v5-candidate",
            "symbol": symbol,
            "direction": context.direction,
            "setup_type": setup_type,
            "trend_regime": context.regime,
            "entry": str(entry),
            "stop": str(stop),
            "risk_distance": str(risk),
            "frozen_atr": str(source_1h.atr),
            "tp1": str(tp1),
            "tp2": str(tp2),
            "tp3": str(tp3),
            "target": str(tp3),
            "tp1_r": str(tp1_r),
            "tp2_r": str(tp2_r),
            "tp3_r": str(tp3_r),
            "reward_risk": str(tp3_r),
            "published_at": published_at,
            "entry_drift": str(drift),
            "entry_drift_limit_atr": str(drift_limit),
            "entry_extension_atr": str(entry_extension),
            "recent_run_entry_atr": str(recent_run_entry_atr),
            "trigger_timeframe": "15m",
            "context_timeframe": "1h",
            "confirmation_timeframe": "4h",
            "exit_management": {
                "tp1_allocation": str(TP1_ALLOCATION),
                "tp2_allocation": str(TP2_ALLOCATION),
                "tp3_allocation": str(TP3_ALLOCATION),
                "after_tp1": "move_remaining_stop_to_entry",
                "after_tp2": "move_remaining_stop_to_tp1",
                "maximum_realized_r": str(
                    TP1_ALLOCATION * tp1_r
                    + TP2_ALLOCATION * tp2_r
                    + TP3_ALLOCATION * tp3_r
                ),
                "reference_only": True,
            },
            "execution": "retrospective-reference-only",
        }


def _candidate(
    *,
    signal_id: str,
    symbol: str,
    direction: str,
    group_open: int,
    published_at: int,
    setup_type: str,
    regime: str,
    recent_run_atr: D,
    source_extension_atr: D,
    plan: dict | None,
    preliminary_reason: str | None,
    observation_end_open: int | None,
):
    return Candidate(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        source_open_time=group_open,
        source_close=published_at,
        published_at=published_at,
        setup_type=setup_type,
        regime=regime,
        recent_run_atr=recent_run_atr,
        source_extension_atr=source_extension_atr,
        favorable_050_at=None,
        adverse_050_at=None,
        historical_last_minute_open_time=observation_end_open,
        v4_plan=plan,
        preliminary_reason=preliminary_reason,
    )


def balanced_15m_filter_reason(
    row: Candidate,
    snapshots: dict[str, dict[int, Snapshot]],
) -> str | None:
    """Experimental emerging-trend entry filter; completed symbol-specific 15m only.

    No future candle, no BTC proxy, and no change to the V4 strategy rules.
    V4-qualified established entries remain eligible. Missing 15m data fails
    closed for emerging entries rather than being treated as confirmation.
    """
    if row.preliminary_reason is not None:
        return None  # Retain the earlier V4/V5 reason without hiding it.
    if row.regime == "established":
        return None
    if row.regime != "emerging" or row.direction not in ("long", "short"):
        return "BALANCED_UNSUPPORTED_REGIME"
    bars = snapshots.get(row.symbol, {})
    current = bars.get(row.published_at - MIN15)
    previous = bars.get(row.published_at - 2 * MIN15)
    if (
        current is None
        or previous is None
        or current.timeframe != "15m"
        or previous.timeframe != "15m"
        or current.count < 500
        or previous.count < 499
        or current.bar.open_time != row.published_at - MIN15
        or previous.bar.open_time != row.published_at - 2 * MIN15
        or current.bar.close_time + 1 != row.published_at
        or previous.bar.close_time + 1 != current.bar.open_time
        or current.history_origin != previous.history_origin
    ):
        return "BALANCED_15M_DATA_UNAVAILABLE"
    sign = D(1) if row.direction == "long" else D(-1)
    confirmed = (
        sign * (current.ema20 - current.ema50) > 0
        and sign * (current.ema20 - previous.ema20) > 0
        and sign * (current.bar.close - current.ema20) > 0
    )
    return None if confirmed else "BALANCED_15M_NOT_ALIGNED"


def make_balanced_candidates(
    v5_candidates: list[Candidate],
    snapshots: dict[str, dict[int, Snapshot]],
) -> tuple[list[Candidate], dict[str, int]]:
    """Clone the hybrid cohort before independently replaying portfolio guards."""
    result: list[Candidate] = []
    reasons: Counter = Counter()
    for original in v5_candidates:
        reason = balanced_15m_filter_reason(original, snapshots)
        reasons[reason or "UNCHANGED_OR_CONFIRMED"] += 1
        result.append(
            replace(
                original,
                signal_id="balanced-" + original.signal_id,
                preliminary_reason=original.preliminary_reason or reason,
                capped_reason=None,
            )
        )
    return result, dict(sorted(reasons.items()))


def _observation_end_open(published_at: int, available_boundary: int):
    end_boundary = min(published_at + OBSERVATION_MS, available_boundary)
    if end_boundary <= published_at:
        return None
    return end_boundary - MINUTE


def simulate_v5_with_safety(
    candidates: list[Candidate],
    max_active: int = 6,
    max_same_direction_rolling: int = V5_MAX_SAME_DIRECTION_ROLLING,
) -> list[Candidate]:
    """Chronological V5 safety replay with a rolling concentration guard.

    V4 evaluated one market-wide cluster per completed 1H candle. V5 can
    evaluate four completed 15m trigger clusters per hour, so carrying V4's
    per-cluster limit forward unchanged would create a concentration loophole.
    The V5 candidate therefore allows at most two same-direction publications
    in the prior rolling hour while retaining V4 session dedupe, circuit
    breaker, and six-active-directional-reference cap.
    """
    published: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    grouped: dict[int, list[Candidate]] = {}
    for row in candidates:
        grouped.setdefault(row.published_at, []).append(row)

    for publication_at in sorted(grouped):
        for row in sorted(
            grouped[publication_at],
            key=lambda item: item.ranking,
        ):
            if row.preliminary_reason:
                row.capped_reason = row.preliminary_reason
                continue

            key = (row.symbol, row.direction)
            if key in seen:
                row.capped_reason = "SAME_DIRECTION_SIGNAL_THIS_SESSION"
                continue

            if _circuit_paused_scaled(
                published,
                row.direction,
                row.published_at,
            ):
                row.capped_reason = "DIRECTIONAL_CIRCUIT_BREAKER"
                continue

            if (
                _active_scaled_count(
                    published,
                    row.direction,
                    row.published_at,
                )
                >= max_active
            ):
                row.capped_reason = "ACTIVE_DIRECTIONAL_EXPOSURE_LIMIT"
                continue

            recent_same_direction = sum(
                prior.direction == row.direction
                and prior.published_at
                > row.published_at - V5_ROLLING_CONCENTRATION_MS
                and prior.published_at <= row.published_at
                for prior in published
            )
            if recent_same_direction >= max_same_direction_rolling:
                row.capped_reason = (
                    "ROLLING_MARKET_DIRECTION_CONCENTRATION_LIMIT"
                )
                continue

            row.capped_reason = "WOULD_PUBLISH_V4"
            seen.add(key)
            published.append(row)

    return candidates


def _replay_candidates_for_portfolio(
    candidates: list[Candidate],
    minute_cache: dict[str, list],
):
    """Replay through all available data so safety-cap state is chronological."""
    for row in candidates:
        if row.v4_plan is None or row.historical_last_minute_open_time is None:
            continue
        bars = [
            bar
            for bar in minute_cache.get(row.symbol, [])
            if bar.open_time <= row.historical_last_minute_open_time
        ]
        row.v4_scaled_outcome = replay_scaled(row, bars)


def _is_mature_4h(row: Candidate, available_boundary: int) -> bool:
    return available_boundary >= row.published_at + OBSERVATION_MS


def _analysis_4h_outcomes(
    candidates: list[Candidate],
    minute_cache: dict[str, list],
    available_boundary: int,
):
    outcomes = {}
    mature_ids = set()
    for row in candidates:
        if row.v4_plan is None:
            continue
        analysis_boundary = min(
            row.published_at + OBSERVATION_MS,
            available_boundary,
        )
        if analysis_boundary <= row.published_at:
            continue
        if _is_mature_4h(row, available_boundary):
            mature_ids.add(row.signal_id)
        bars = [
            bar
            for bar in minute_cache.get(row.symbol, [])
            if row.published_at <= bar.open_time < analysis_boundary
        ]
        outcomes[row.signal_id] = replay_scaled(row, bars)
    return outcomes, mature_ids


def _outcome_metrics(rows: list[Candidate], outcomes_by_id: dict[str, dict]):
    outcomes = [
        outcomes_by_id[row.signal_id]
        for row in rows
        if row.signal_id in outcomes_by_id
        and outcomes_by_id[row.signal_id] is not None
    ]
    resolved = [
        out for out in outcomes if out.get("conservative_r") is not None
    ]

    ordering = Counter()
    for out in outcomes:
        favorable = out.get("favorable_050_at")
        adverse = out.get("adverse_050_at")
        if favorable is not None and adverse is not None:
            if favorable < adverse:
                ordering["FAVORABLE_FIRST"] += 1
            elif adverse < favorable:
                ordering["ADVERSE_FIRST"] += 1
            else:
                ordering["AMBIGUOUS_SAME_1M"] += 1
        elif favorable is not None:
            ordering["FAVORABLE_FIRST"] += 1
        elif adverse is not None:
            ordering["ADVERSE_FIRST"] += 1
        else:
            ordering["NEITHER"] += 1

    mfe = [
        D(out["mfe_r"])
        for out in outcomes
        if out.get("mfe_r") is not None
    ]
    mae = [
        D(out["mae_r"])
        for out in outcomes
        if out.get("mae_r") is not None
    ]
    total_r = sum(
        (D(out["conservative_r"]) for out in resolved),
        D(0),
    )
    return {
        "candidates": len(rows),
        "observed": len(outcomes),
        "resolved": len(resolved),
        "status": dict(
            sorted(
                Counter(
                    out.get("status", "missing")
                    for out in outcomes
                ).items()
            )
        ),
        "half_r_ordering": dict(sorted(ordering.items())),
        "tp1_reached": sum(
            bool(out.get("tp1_reached")) for out in outcomes
        ),
        "tp2_reached": sum(
            bool(out.get("tp2_reached")) for out in outcomes
        ),
        "tp3_reached": sum(
            bool(out.get("tp3_reached")) for out in outcomes
        ),
        "conservative_r_sum_resolved": str(total_r),
        "conservative_r_mean_resolved": (
            str(total_r / len(resolved)) if resolved else None
        ),
        "median_mfe_r": str(median(mfe)) if mfe else None,
        "median_mae_r": str(median(mae)) if mae else None,
    }


def _summary(
    candidates: list[Candidate],
    analysis_outcomes: dict[str, dict],
    mature_ids: set[str],
):
    published = [
        row for row in candidates if row.capped_reason == "WOULD_PUBLISH_V4"
    ]
    mature = [row for row in published if row.signal_id in mature_ids]
    metrics = _outcome_metrics(published, analysis_outcomes)
    mature_metrics = _outcome_metrics(mature, analysis_outcomes)

    return {
        "raw_candidates": len(candidates),
        "preliminary_reasons": dict(
            sorted(
                Counter(
                    row.preliminary_reason or "ELIGIBLE"
                    for row in candidates
                ).items()
            )
        ),
        "portfolio_reasons": dict(
            sorted(Counter(row.capped_reason for row in candidates).items())
        ),
        "published": len(published),
        "directions": dict(
            sorted(Counter(row.direction for row in published).items())
        ),
        "setup_types": dict(
            sorted(Counter(row.setup_type for row in published).items())
        ),
        **metrics,
        "mature_4h": mature_metrics,
    }


def _signal_rows(
    candidates: list[Candidate],
    meta: dict[str, dict],
    analysis_outcomes: dict[str, dict],
):
    result = []
    for row in candidates:
        if row.capped_reason != "WOULD_PUBLISH_V4":
            continue
        result.append(
            {
                "id": row.signal_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "published_at": row.published_at,
                "setup_type": row.setup_type,
                "regime": row.regime,
                "recent_run_atr": str(row.recent_run_atr),
                "source_extension_atr": str(row.source_extension_atr),
                "outcome_4h": analysis_outcomes.get(row.signal_id),
                "portfolio_outcome_full_available": row.v4_scaled_outcome,
                **meta.get(row.signal_id, {}),
            }
        )
    return result


async def run_day(day: str):
    session_start, session_end = ist_session_bounds(day)
    current_now = now_ms()
    last_complete_15m_boundary = (current_now // MIN15) * MIN15
    trigger_data_end = min(session_end, last_complete_15m_boundary)

    last_complete_minute_boundary = (current_now // MINUTE) * MINUTE
    available_outcome_boundary = min(
        session_end + OBSERVATION_MS,
        last_complete_minute_boundary,
    )

    with Session() as session:
        symbols = list(
            session.scalars(
                select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order)
            )
        )
        source_opens = {}
        for symbol in symbols:
            source_opens[symbol] = list(
                session.scalars(
                    select(Candle.open_time)
                    .where(
                        Candle.symbol == symbol,
                        Candle.timeframe == "1h",
                        Candle.open_time >= session_start - HOUR,
                        Candle.open_time < session_end - HOUR,
                    )
                    .order_by(Candle.open_time)
                )
            )

    if not symbols:
        raise ValueError("Watchlist is empty")

    snapshot_cache: dict[str, dict[int, Snapshot]] = {}
    minute_cache: dict[str, list] = {}

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
        public = BinancePublic(client)
        for symbol in symbols:
            snapshot_cache[symbol] = await _fetch_15m_snapshots(
                public,
                symbol,
                session_start,
                trigger_data_end,
            )
        if available_outcome_boundary > session_start:
            outcome_end_open = available_outcome_boundary - MINUTE
            for symbol in symbols:
                minute_cache[symbol] = await fetch_minutes(
                    public,
                    symbol,
                    session_start,
                    outcome_end_open,
                )
        else:
            minute_cache = {symbol: [] for symbol in symbols}

    minute_by_open = {
        symbol: {bar.open_time: bar for bar in bars}
        for symbol, bars in minute_cache.items()
    }
    btc_states = _btc_state_map(snapshot_cache["BTCUSDT"])

    v4_candidates: list[Candidate] = []
    v5_candidates: list[Candidate] = []
    v4_meta: dict[str, dict] = {}
    v5_meta: dict[str, dict] = {}
    v4_setup_reasons = Counter()
    v5_context_reasons = Counter()
    v5_trigger_reasons = Counter()

    with Session() as session:
        for symbol in symbols:
            for source_open in source_opens[symbol]:
                source_close = source_open + HOUR
                if not session_start <= source_close < session_end:
                    continue
                if source_close > current_now:
                    continue

                current, previous, confirmation, structure, contract, _ = context_at(
                    session, symbol, source_open
                )
                if current is None:
                    v4_setup_reasons["MISSING_SOURCE_SNAPSHOT"] += 1
                    v5_context_reasons["MISSING_SOURCE_SNAPSHOT"] += 1
                    continue

                v4_setup = evaluate_setup_v4(
                    current, previous, confirmation, structure
                )
                v4_setup_reasons[v4_setup.reason] += 1
                if v4_setup.outcome in ("LONG_SETUP", "SHORT_SETUP"):
                    direction = v4_setup.direction
                    assert direction in ("long", "short")
                    preliminary = None
                    plan = None

                    btc_reason, _ = btc_regime_guard(
                        session, symbol, direction, source_open
                    )
                    if btc_reason:
                        preliminary = btc_reason
                    if preliminary is None:
                        preliminary = btc_timing_reason(
                            btc_states, source_close, direction
                        )

                    entry = _reference_entry(
                        minute_by_open.get(symbol, {}),
                        source_close,
                    )
                    if preliminary is None and entry is None:
                        preliminary = "REFERENCE_ENTRY_UNAVAILABLE"

                    if preliminary is None:
                        try:
                            pf = _price_filter(contract)
                            quote = Quote(
                                symbol,
                                entry,
                                entry,
                                D(1),
                                D(1),
                                source_close,
                                source_close,
                            )
                            plan = build_plan_v4(
                                symbol,
                                v4_setup,
                                current,
                                quote,
                                pf,
                                source_close,
                            )
                        except PlanRejected as exc:
                            preliminary = exc.code

                    recent_run = _check_value(
                        v4_setup.checks, "recent_run_atr"
                    )
                    source_extension = _check_value(
                        v4_setup.checks, "source_extension_atr"
                    )
                    identity = "v4-full-" + str(
                        source_open
                    ) + "-" + symbol
                    end_open = (
                        available_outcome_boundary - MINUTE
                        if available_outcome_boundary > source_close
                        else None
                    )
                    row = _candidate(
                        signal_id=identity,
                        symbol=symbol,
                        direction=direction,
                        group_open=source_open,
                        published_at=source_close,
                        setup_type=v4_setup.setup_type,
                        regime=v4_setup.regime,
                        recent_run_atr=recent_run,
                        source_extension_atr=source_extension,
                        plan=plan,
                        preliminary_reason=preliminary,
                        observation_end_open=end_open,
                    )
                    v4_candidates.append(row)
                    v4_meta[identity] = {
                        "source_1h_open": source_open,
                        "source_1h_close": source_close,
                        "entry_reference": str(entry) if entry is not None else None,
                    }

                    # Hybrid V5 keeps every original V4 setup path intact.
                    # The 15m layer is an additive rescue lane only for
                    # otherwise trend-aligned 1H no-trigger decisions.
                    v5_base_identity = (
                        "v5-base-" + str(source_open) + "-" + symbol
                    )
                    v5_base = _candidate(
                        signal_id=v5_base_identity,
                        symbol=symbol,
                        direction=direction,
                        group_open=source_open,
                        published_at=source_close,
                        setup_type=v4_setup.setup_type,
                        regime=v4_setup.regime,
                        recent_run_atr=recent_run,
                        source_extension_atr=source_extension,
                        plan=plan,
                        preliminary_reason=preliminary,
                        observation_end_open=end_open,
                    )
                    v5_candidates.append(v5_base)
                    v5_meta[v5_base_identity] = {
                        "lane": "v4_base",
                        "source_1h_open": source_open,
                        "source_1h_close": source_close,
                        "entry_reference": (
                            str(entry) if entry is not None else None
                        ),
                    }
                    v5_context_reasons["V4_BASE_SETUP"] += 1
                    continue

                if (
                    v4_setup.reason
                    != "NO_PULLBACK_OR_BREAKOUT_TRIGGER"
                    or v4_setup.direction not in ("long", "short")
                    or v4_setup.regime is None
                ):
                    v5_context_reasons[
                        "RESCUE_NOT_ELIGIBLE_" + v4_setup.reason
                    ] += 1
                    continue

                armed = evaluate_context_v5(
                    current, previous, confirmation, structure
                )
                v5_context_reasons[armed.reason] += 1
                if armed.outcome != "ARMED":
                    continue

                direction = armed.direction
                assert direction in ("long", "short")

                found_trigger = False
                for trigger_open in range(
                    source_close,
                    min(source_close + HOUR, session_end),
                    MIN15,
                ):
                    published_at = trigger_open + MIN15
                    if published_at >= session_end:
                        break
                    if published_at > current_now:
                        break

                    current_15 = snapshot_cache[symbol].get(trigger_open)
                    previous_15 = snapshot_cache[symbol].get(
                        trigger_open - MIN15
                    )
                    structure_15 = [
                        snapshot_cache[symbol].get(
                            trigger_open - n * MIN15
                        )
                        for n in range(12, 0, -1)
                    ]
                    if (
                        current_15 is None
                        or previous_15 is None
                        or any(item is None for item in structure_15)
                    ):
                        v5_trigger_reasons["MISSING_15M_CONTEXT"] += 1
                        continue

                    trigger = evaluate_trigger_v5(
                        direction,
                        current_15,
                        previous_15,
                        structure_15,
                    )
                    v5_trigger_reasons[trigger.reason] += 1
                    if trigger.outcome != "TRIGGER":
                        continue

                    found_trigger = True
                    preliminary = None
                    plan = None

                    btc_reason, _ = btc_regime_guard(
                        session, symbol, direction, source_open
                    )
                    if btc_reason:
                        preliminary = btc_reason
                    if preliminary is None:
                        preliminary = btc_timing_reason(
                            btc_states, published_at, direction
                        )

                    entry = _reference_entry(
                        minute_by_open.get(symbol, {}),
                        published_at,
                    )
                    if preliminary is None and entry is None:
                        preliminary = "REFERENCE_ENTRY_UNAVAILABLE"

                    if preliminary is None:
                        try:
                            plan = _v5_reference_plan(
                                symbol,
                                armed,
                                trigger,
                                current,
                                current_15,
                                entry,
                                _price_filter(contract),
                                published_at,
                            )
                        except PlanRejected as exc:
                            preliminary = exc.code

                    setup_type = (
                        "pullback_continuation"
                        if trigger.trigger_type
                        == "pullback_continuation_15m"
                        else "momentum_breakout"
                    )
                    identity = candidate_id(
                        symbol,
                        source_open,
                        trigger_open,
                    )
                    end_open = (
                        available_outcome_boundary - MINUTE
                        if available_outcome_boundary > published_at
                        else None
                    )
                    row = _candidate(
                        signal_id=identity,
                        symbol=symbol,
                        direction=direction,
                        group_open=trigger_open,
                        published_at=published_at,
                        setup_type=setup_type,
                        regime=armed.regime,
                        recent_run_atr=trigger.recent_run_atr,
                        source_extension_atr=trigger.source_extension_atr,
                        plan=plan,
                        preliminary_reason=preliminary,
                        observation_end_open=end_open,
                    )
                    v5_candidates.append(row)
                    v5_meta[identity] = {
                        "lane": "15m_rescue",
                        "context_1h_open": source_open,
                        "context_1h_close": source_close,
                        "trigger_15m_open": trigger_open,
                        "trigger_15m_close": published_at,
                        "entry_reference": str(entry) if entry is not None else None,
                    }

                if not found_trigger:
                    v5_trigger_reasons["NO_TRIGGER_IN_ARM_WINDOW"] += 1

    # Portfolio safety must see the full available path, not only the
    # four-hour comparison window. Otherwise an actually-resolved early signal
    # could be incorrectly counted as active for the rest of the session.
    _replay_candidates_for_portfolio(v4_candidates, minute_cache)
    _replay_candidates_for_portfolio(v5_candidates, minute_cache)

    # Compare the experimental Balanced policy on independently cloned rows.
    # The original V4 baseline and hybrid candidates remain unchanged.
    balanced_candidates, balanced_filter_reasons = make_balanced_candidates(
        v5_candidates, snapshot_cache
    )
    balanced_meta = {
        "balanced-" + key: {**value, "entry_policy": "balanced_15m_emerging"}
        for key, value in v5_meta.items()
    }

    simulate_with_active_cap(v4_candidates)
    simulate_v5_with_safety(v5_candidates)
    simulate_v5_with_safety(balanced_candidates)

    v4_analysis, v4_mature_ids = _analysis_4h_outcomes(
        v4_candidates,
        minute_cache,
        available_outcome_boundary,
    )
    v5_analysis, v5_mature_ids = _analysis_4h_outcomes(
        v5_candidates,
        minute_cache,
        available_outcome_boundary,
    )
    balanced_analysis, balanced_mature_ids = _analysis_4h_outcomes(
        balanced_candidates,
        minute_cache,
        available_outcome_boundary,
    )

    return {
        "ist_date": day,
        "read_only": True,
        "observation_window_hours": 4,
        "watchlist_size": len(symbols),
        "source_1h_rows": sum(len(rows) for rows in source_opens.values()),
        "v4": {
            "architecture": "4H confirmation -> completed 1H setup/entry",
            "setup_reasons": dict(sorted(v4_setup_reasons.items())),
            "summary": _summary(
                v4_candidates, v4_analysis, v4_mature_ids
            ),
            "signals": _signal_rows(
                v4_candidates, v4_meta, v4_analysis
            ),
        },
        "v5_candidate": {
            "architecture": (
                "preserve V4 base setups + rescue only V4 "
                "NO_PULLBACK_OR_BREAKOUT_TRIGGER decisions with completed "
                "15m microtrend-aligned pullback/breakout triggers -> "
                "rolling-60m concentration safety"
            ),
            "context_reasons": dict(sorted(v5_context_reasons.items())),
            "trigger_reasons": dict(sorted(v5_trigger_reasons.items())),
            "summary": _summary(
                v5_candidates, v5_analysis, v5_mature_ids
            ),
            "signals": _signal_rows(
                v5_candidates, v5_meta, v5_analysis
            ),
        },
        "v5_balanced": {
            "architecture": (
                "hybrid V5 candidates; established entries unchanged; emerging "
                "entries require symbol-specific completed 15m EMA20/EMA50 "
                "alignment, EMA20 slope and close on the directional EMA20 side; "
                "same rolling concentration and risk replay"
            ),
            "filter_reasons": balanced_filter_reasons,
            "summary": _summary(
                balanced_candidates, balanced_analysis, balanced_mature_ids
            ),
            "signals": _signal_rows(
                balanced_candidates, balanced_meta, balanced_analysis
            ),
        },
    }


def _aggregate_metric(rows: list[dict]):
    candidates = sum(row["candidates"] for row in rows)
    observed = sum(row["observed"] for row in rows)
    resolved = sum(row["resolved"] for row in rows)
    tp1 = sum(row["tp1_reached"] for row in rows)
    tp2 = sum(row["tp2_reached"] for row in rows)
    tp3 = sum(row["tp3_reached"] for row in rows)
    conservative = sum(
        (D(row["conservative_r_sum_resolved"]) for row in rows),
        D(0),
    )
    favorable = sum(
        row["half_r_ordering"].get("FAVORABLE_FIRST", 0)
        for row in rows
    )
    adverse = sum(
        row["half_r_ordering"].get("ADVERSE_FIRST", 0)
        for row in rows
    )
    return {
        "candidates": candidates,
        "observed": observed,
        "resolved": resolved,
        "tp1_reached": tp1,
        "tp2_reached": tp2,
        "tp3_reached": tp3,
        "tp1_rate_observed": (
            str(D(tp1) / observed) if observed else None
        ),
        "favorable_half_r_first": favorable,
        "adverse_half_r_first": adverse,
        "favorable_half_r_first_rate_observed": (
            str(D(favorable) / observed) if observed else None
        ),
        "conservative_r_sum_resolved": str(conservative),
        "conservative_r_mean_resolved": (
            str(conservative / resolved) if resolved else None
        ),
    }


def _aggregate(reports: list[dict], key: str):
    summaries = [report[key]["summary"] for report in reports]
    all_observed = _aggregate_metric(summaries)
    all_observed["published"] = sum(
        row["published"] for row in summaries
    )
    all_observed["mature_4h"] = _aggregate_metric(
        [row["mature_4h"] for row in summaries]
    )
    return all_observed


async def main_async(days: list[str]):
    reports = []
    for day in days:
        reports.append(await run_day(day))

    result = {
        "study": "MV V4 baseline vs V5 hybrid vs V5 Balanced (research-only)",
        "read_only": True,
        "days": days,
        "interpretation": (
            "Full-watchlist counterfactual preserving V4 base setups and "
            "adding 15m rescue only after trend-aligned V4 no-trigger rows; "
            "Balanced adds a completed symbol-specific 15m gate to emerging "
            "entries while preserving established entries. "
            "Public Binance 15m triggers, first-1m-open reference entries, "
            "V4 scaled exits, and V5 rolling concentration safety. "
            "This is an incomplete-cost, fixed-four-hour retrospective; "
            "not a production signal, a full backtest, or proof of profitability."
        ),
        "reports": reports,
        "combined": {
            "v4": _aggregate(reports, "v4"),
            "v5_candidate": _aggregate(reports, "v5_candidate"),
            "v5_balanced": _aggregate(reports, "v5_balanced"),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ist-date",
        action="append",
        required=True,
        help="IST date YYYY-MM-DD; repeat to compare multiple days",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.ist_date))


if __name__ == "__main__":
    main()
