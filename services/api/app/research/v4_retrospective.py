"""Read-only retrospective for the V4 safety governor.

This module never writes MV tables. It re-evaluates historical V2 publications
with the V4 setup/entry rules, pulls public BTCUSDT 15m candles for the timing
veto, then simulates V4 session dedupe, concentration and deterioration
circuit-breaker behavior in chronological order.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, time as wall_time
from decimal import Decimal as D
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text

from app.analytics.service import (
    MINUTE_MS,
    MinuteBar,
    apply_minute,
    first_full_minute,
)
from app.database import Session
from app.market.binance import BinancePublic
from app.models import SignalDecision, SignalOutcome, SignalPlan
from app.signals.service import btc_regime_guard, context_at
from mv_strategy.indicators import INTERVAL_MS, IndicatorState
from mv_strategy.signals import PlanRejected, PriceFilter, Quote
from mv_strategy.strategy_v4 import build_plan_v4, evaluate_setup_v4

V2 = "MV-TREND-DUAL-v2"
IST = ZoneInfo("Asia/Kolkata")
MIN15 = INTERVAL_MS["15m"]
HOUR = INTERVAL_MS["1h"]
CIRCUIT_WINDOW = 120 * 60_000
CIRCUIT_PAUSE = 120 * 60_000


@dataclass
class Candidate:
    signal_id: str
    symbol: str
    direction: str
    source_open_time: int
    source_close: int
    published_at: int
    setup_type: str
    regime: str
    recent_run_atr: D
    source_extension_atr: D
    favorable_050_at: int | None
    adverse_050_at: int | None
    historical_status: str | None = None
    historical_mfe_r: str | None = None
    historical_mae_r: str | None = None
    historical_conservative_r: str | None = None
    historical_last_minute_open_time: int | None = None
    v4_plan: dict | None = None
    v4_scaled_outcome: dict | None = None
    preliminary_reason: str | None = None
    final_reason: str | None = None
    capped_reason: str | None = None

    @property
    def ranking(self):
        return (
            self.recent_run_atr,
            self.source_extension_atr,
            0 if self.regime == "established" else 1,
            self.symbol,
        )


def ist_session_bounds(day: str) -> tuple[int, int]:
    parsed = datetime.strptime(day, "%Y-%m-%d").date()
    start = datetime.combine(parsed, wall_time(9, 0), IST)
    end = datetime.combine(parsed, wall_time(23, 0), IST)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _check_value(setup, suffix: str) -> D:
    for row in setup.checks:
        if row["id"].endswith("." + suffix) and "value" in row:
            return D(row["value"])
    raise ValueError(f"V4 setup is missing {suffix}")


def _quote(evidence: dict, symbol: str) -> Quote:
    row = evidence.get("quote") or {}
    return Quote(
        symbol,
        D(row["bid"]),
        D(row["ask"]),
        D(row["bid_qty"]),
        D(row["ask_qty"]),
        int(row["time"]),
        int(row["received_at"]),
    )


def _price_filter(evidence: dict) -> PriceFilter:
    metadata = evidence.get("metadata") or {}
    row = next(
        item
        for item in metadata.get("filters", [])
        if item.get("filterType") == "PRICE_FILTER"
    )
    return PriceFilter(D(row["tickSize"]), D(row["minPrice"]), D(row["maxPrice"]))


def parse_minute(row):
    if not isinstance(row, list) or len(row) < 7:
        raise ValueError("Malformed Binance 1m candle")
    if any(not isinstance(value, str) for value in row[1:6]):
        raise ValueError("Binance 1m OHLCV values must be decimal strings")
    bar = MinuteBar(
        open_time=int(row[0]),
        close_time=int(row[6]),
        open=D(row[1]),
        high=D(row[2]),
        low=D(row[3]),
        close=D(row[4]),
        volume=D(row[5]),
    )
    bar.validate()
    return bar


async def fetch_minutes(public, symbol: str, start: int, end_open: int):
    if end_open < start:
        return []
    bars = []
    cursor = start
    while cursor <= end_open:
        rows = await public.get(
            "/fapi/v1/klines",
            symbol=symbol,
            interval="1m",
            startTime=cursor,
            endTime=end_open + MINUTE_MS - 1,
            limit=1000,
        )
        parsed = [
            parse_minute(row)
            for row in rows
            if cursor <= int(row[0]) <= end_open
        ]
        if not parsed:
            break
        if parsed[0].open_time != cursor:
            raise ValueError(
                f"{symbol} 1m retrospective history has a gap at {cursor}"
            )
        for previous, current in zip(parsed, parsed[1:]):
            if current.open_time != previous.open_time + MINUTE_MS:
                raise ValueError(
                    f"{symbol} 1m retrospective history is non-contiguous"
                )
        bars.extend(parsed)
        next_cursor = parsed[-1].open_time + MINUTE_MS
        if next_cursor <= cursor:
            raise ValueError("1m retrospective pagination did not advance")
        cursor = next_cursor
        if len(parsed) < 1000:
            break
    return bars


def replay_scaled(row: Candidate, bars: list[MinuteBar]):
    if row.v4_plan is None:
        return None
    p = row.v4_plan
    start = first_full_minute(row.published_at)
    outcome = SimpleNamespace(
        strategy="MV-TREND-DUAL-v4",
        direction=row.direction,
        entry=p["entry"],
        stop=p["stop"],
        risk_distance=p["risk_distance"],
        tp1=p["tp1"],
        tp2=p["tp2"],
        tp3=p["tp3"],
        tp1_r=p["tp1_r"],
        tp2_r=p["tp2_r"],
        tp3_r=p["tp3_r"],
        first_observed_minute=start,
        last_minute_open_time=None,
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
        observed_bars=0,
        updated_at=row.published_at,
        error_code=None,
    )
    last_bar = None
    for bar in bars:
        if bar.open_time < start:
            continue
        apply_minute(outcome, bar)
        last_bar = bar
        if outcome.status != "open":
            break
    mark_r = None
    if last_bar is not None and outcome.status == "open":
        entry = D(p["entry"])
        risk = D(p["risk_distance"])
        mark_r = (
            (last_bar.close - entry) / risk
            if row.direction == "long"
            else (entry - last_bar.close) / risk
        )
    return {
        "status": outcome.status,
        "terminal_at": outcome.terminal_at,
        "conservative_r": outcome.conservative_r,
        "mfe_r": outcome.mfe_r,
        "mae_r": outcome.mae_r,
        "tp1_reached": outcome.favorable_100_at is not None,
        "tp2_reached": outcome.favorable_150_at is not None,
        "tp3_reached": outcome.favorable_200_at is not None,
        "favorable_050_at": outcome.favorable_050_at,
        "adverse_050_at": outcome.adverse_050_at,
        "observed_bars": outcome.observed_bars,
        "mark_r": str(mark_r) if mark_r is not None else None,
        "last_observed_open_time": (
            last_bar.open_time if last_bar is not None else None
        ),
    }


async def survivor_minute_cache(public, survivors: list[Candidate], max_boundary: int):
    cache = {}
    for row in survivors:
        if row.v4_plan is None:
            continue
        start = first_full_minute(row.published_at)
        end_open = max_boundary - MINUTE_MS
        if row.historical_last_minute_open_time is not None:
            end_open = min(end_open, row.historical_last_minute_open_time)
        cache[row.signal_id] = await fetch_minutes(
            public, row.symbol, start, end_open
        )
    return cache


def portfolio_health_at(
    survivors: list[Candidate],
    minute_cache: dict[str, list[MinuteBar]],
    boundary: int,
):
    result = {}
    for direction in ("long", "short"):
        rows = []
        for row in survivors:
            if row.direction != direction or row.published_at >= boundary:
                continue
            bars = [
                bar
                for bar in minute_cache.get(row.signal_id, [])
                if bar.open_time <= boundary - MINUTE_MS
            ]
            replay = replay_scaled(row, bars)
            if replay is None or replay["status"] != "open":
                continue
            mark_r = D(replay["mark_r"])
            rows.append(
                {
                    "signal_id": row.signal_id,
                    "symbol": row.symbol,
                    "published_at": row.published_at,
                    "mark_r": str(mark_r),
                    "mfe_r": replay["mfe_r"],
                    "mae_r": replay["mae_r"],
                    "tp1_reached": replay["tp1_reached"],
                    "adverse_050_at": replay["adverse_050_at"],
                }
            )
        marks = [D(row["mark_r"]) for row in rows]
        result[direction] = {
            "active_count": len(rows),
            "below_entry_count": sum(mark < 0 for mark in marks),
            "at_or_below_minus_025_count": sum(
                mark <= D("-0.25") for mark in marks
            ),
            "at_or_below_minus_050_count": sum(
                mark <= D("-0.50") for mark in marks
            ),
            "average_mark_r": (
                str(sum(marks, D(0)) / len(marks)) if marks else None
            ),
            "minimum_mark_r": str(min(marks)) if marks else None,
            "signals": rows,
        }
    return result


async def scaled_outcome(public, row: Candidate):
    if row.v4_plan is None:
        return None
    end_open = row.historical_last_minute_open_time
    if end_open is None:
        return {
            "status": "unobserved",
            "observed_bars": 0,
            "conservative_r": None,
            "mfe_r": "0",
            "mae_r": "0",
            "mark_r": None,
            "last_observed_open_time": None,
        }
    start = first_full_minute(row.published_at)
    bars = await fetch_minutes(public, row.symbol, start, end_open)
    return replay_scaled(row, bars)


def _circuit_paused(published: list[Candidate], direction: str, now: int) -> bool:
    rows = [
        row
        for row in published
        if row.direction == direction
        and row.adverse_050_at is not None
        and row.adverse_050_at <= now
        and (
            row.favorable_050_at is None
            or row.adverse_050_at <= row.favorable_050_at
        )
        and row.published_at >= now - CIRCUIT_WINDOW - CIRCUIT_PAUSE
    ]
    rows.sort(key=lambda row: (row.adverse_050_at, row.signal_id))
    for index, row in enumerate(rows):
        trigger = row.adverse_050_at
        if trigger is None or now >= trigger + CIRCUIT_PAUSE:
            continue
        clustered = [
            other
            for other in rows[: index + 1]
            if other.adverse_050_at is not None
            and other.adverse_050_at <= trigger
            and trigger - CIRCUIT_WINDOW <= other.published_at <= trigger
        ]
        if len(clustered) >= 2:
            return True
    return False


def circuit_events(published: list[Candidate]) -> list[dict]:
    """Return every distinct directional pause trigger implied by published rows."""
    events = []
    seen = set()
    for direction in ("long", "short"):
        rows = [
            row
            for row in published
            if row.direction == direction
            and row.adverse_050_at is not None
            and (
                row.favorable_050_at is None
                or row.adverse_050_at <= row.favorable_050_at
            )
        ]
        rows.sort(key=lambda row: (row.adverse_050_at, row.signal_id))
        for index, row in enumerate(rows):
            trigger = row.adverse_050_at
            clustered = [
                other
                for other in rows[: index + 1]
                if other.adverse_050_at is not None
                and other.adverse_050_at <= trigger
                and trigger - CIRCUIT_WINDOW <= other.published_at <= trigger
            ]
            if len(clustered) < 2:
                continue
            pair = clustered[-2:]
            key = (direction, trigger, tuple(item.signal_id for item in pair))
            if key in seen:
                continue
            seen.add(key)
            events.append(
                {
                    "direction": direction,
                    "triggered_at": trigger,
                    "pause_until": trigger + CIRCUIT_PAUSE,
                    "signals": [
                        {
                            "signal_id": item.signal_id,
                            "symbol": item.symbol,
                            "published_at": item.published_at,
                            "adverse_050_at": item.adverse_050_at,
                            "favorable_050_at": item.favorable_050_at,
                        }
                        for item in pair
                    ],
                }
            )
    return sorted(events, key=lambda row: (row["triggered_at"], row["direction"]))


def simulate(candidates: list[Candidate]) -> list[Candidate]:
    published: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    grouped: dict[int, list[Candidate]] = defaultdict(list)
    for row in candidates:
        grouped[row.source_open_time].append(row)

    for source_open in sorted(grouped):
        group = grouped[source_open]
        cluster_count: Counter[str] = Counter()
        for row in sorted(group, key=lambda item: item.ranking):
            if row.preliminary_reason:
                row.final_reason = row.preliminary_reason
                continue
            key = (row.symbol, row.direction)
            if key in seen:
                row.final_reason = "SAME_DIRECTION_SIGNAL_THIS_SESSION"
                continue
            if _circuit_paused(published, row.direction, row.published_at):
                row.final_reason = "DIRECTIONAL_CIRCUIT_BREAKER"
                continue
            if cluster_count[row.direction] >= 2:
                row.final_reason = "MARKET_DIRECTION_CONCENTRATION_LIMIT"
                continue
            row.final_reason = "WOULD_PUBLISH_V4"
            cluster_count[row.direction] += 1
            seen.add(key)
            published.append(row)
    return candidates


def _scaled_milestone(row: Candidate, key: str):
    replay = row.v4_scaled_outcome or {}
    return replay.get(key)


def _circuit_paused_scaled(
    published: list[Candidate], direction: str, now: int
) -> bool:
    rows = []
    for row in published:
        if row.direction != direction:
            continue
        adverse = _scaled_milestone(row, "adverse_050_at")
        favorable = _scaled_milestone(row, "favorable_050_at")
        if adverse is None or adverse > now:
            continue
        if favorable is not None and adverse > favorable:
            continue
        if row.published_at < now - CIRCUIT_WINDOW - CIRCUIT_PAUSE:
            continue
        rows.append((row, adverse, favorable))
    rows.sort(key=lambda item: (item[1], item[0].signal_id))
    for index, (_, trigger, _) in enumerate(rows):
        if now >= trigger + CIRCUIT_PAUSE:
            continue
        clustered = [
            item
            for item in rows[: index + 1]
            if item[1] <= trigger
            and trigger - CIRCUIT_WINDOW <= item[0].published_at <= trigger
        ]
        if len(clustered) >= 2:
            return True
    return False


def _active_scaled_count(
    published: list[Candidate], direction: str, now: int
) -> int:
    active = 0
    for row in published:
        if row.direction != direction or row.published_at >= now:
            continue
        replay = row.v4_scaled_outcome or {}
        terminal = replay.get("terminal_at")
        status = replay.get("status")
        if status in (None, "unobserved") or terminal is None or terminal >= now:
            active += 1
    return active


def simulate_with_active_cap(
    candidates: list[Candidate], max_active: int = 6
) -> list[Candidate]:
    """Second-pass exact simulation after survivor outcomes are replayed."""
    published: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    grouped: dict[int, list[Candidate]] = defaultdict(list)
    for row in candidates:
        grouped[row.source_open_time].append(row)

    for source_open in sorted(grouped):
        cluster_count: Counter[str] = Counter()
        for row in sorted(grouped[source_open], key=lambda item: item.ranking):
            if row.preliminary_reason:
                row.capped_reason = row.preliminary_reason
                continue
            key = (row.symbol, row.direction)
            if key in seen:
                row.capped_reason = "SAME_DIRECTION_SIGNAL_THIS_SESSION"
                continue
            if _circuit_paused_scaled(published, row.direction, row.published_at):
                row.capped_reason = "DIRECTIONAL_CIRCUIT_BREAKER"
                continue
            if (
                _active_scaled_count(published, row.direction, row.published_at)
                >= max_active
            ):
                row.capped_reason = "ACTIVE_DIRECTIONAL_EXPOSURE_LIMIT"
                continue
            if cluster_count[row.direction] >= 2:
                row.capped_reason = "MARKET_DIRECTION_CONCENTRATION_LIMIT"
                continue
            row.capped_reason = "WOULD_PUBLISH_V4"
            cluster_count[row.direction] += 1
            seen.add(key)
            published.append(row)
    return candidates


async def btc_15m_states(boundaries: list[int]) -> dict[int, dict]:
    if not boundaries:
        return {}
    first = min(boundaries)
    last = max(boundaries)
    start = first - 500 * MIN15
    end = last - 1
    expected = (end - start + 1) // MIN15
    if expected > 1000:
        raise ValueError("Retrospective BTC 15m window exceeds one bounded request")

    async with httpx.AsyncClient(timeout=20) as client:
        bars = await BinancePublic(client).klines(
            "BTCUSDT",
            "15m",
            start_time=start,
            end_time=end,
            limit=max(500, expected),
        )
    if not bars or bars[0].open_time != start:
        raise ValueError("BTC 15m history did not start at the requested warmup boundary")
    for previous, current in zip(bars, bars[1:]):
        if current.open_time != previous.open_time + MIN15:
            raise ValueError("BTC 15m retrospective history is non-contiguous")

    state = IndicatorState("15m")
    snapshots: dict[int, dict] = {}
    for bar in bars:
        values = state.advance(bar)
        snapshots[bar.open_time] = {
            "bar": bar,
            "count": state.count,
            "ema20": values["ema20"],
            "ema50": values["ema50"],
        }
    return snapshots


def btc_timing_reason(
    snapshots: dict[int, dict], boundary: int, direction: str
) -> str | None:
    current = snapshots.get(boundary - MIN15)
    previous = snapshots.get(boundary - 2 * MIN15)
    if (
        not current
        or not previous
        or current["count"] < 500
        or previous["count"] < 499
        or current["ema20"] is None
        or current["ema50"] is None
        or previous["ema20"] is None
    ):
        return "BTC_15M_TIMING_UNAVAILABLE"
    bar = current["bar"]
    if direction == "long":
        contradicted = (
            bar.close < current["ema20"] < current["ema50"]
            and current["ema20"] < previous["ema20"]
        )
    else:
        contradicted = (
            bar.close > current["ema20"] > current["ema50"]
            and current["ema20"] > previous["ema20"]
        )
    return "BTC_15M_TIMING_CONFLICT" if contradicted else None


def load_candidates(day: str) -> list[Candidate]:
    start, end = ist_session_bounds(day)
    candidates: list[Candidate] = []
    with Session.begin() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        plans = list(
            session.scalars(
                select(SignalPlan)
                .where(
                    SignalPlan.strategy == V2,
                    SignalPlan.created_at >= start,
                    SignalPlan.created_at < end,
                )
                .order_by(SignalPlan.created_at, SignalPlan.id)
            )
        )
        for plan in plans:
            decision = session.get(SignalDecision, plan.id)
            outcome = session.get(SignalOutcome, plan.id)
            if decision is None:
                raise ValueError(f"Missing decision for {plan.id}")
            current, previous, confirmation, structure, contract, evidence = context_at(
                session, plan.symbol, decision.source_open_time
            )
            reason = None
            v4_plan = None
            setup = evaluate_setup_v4(current, previous, confirmation, structure) if current else None
            if setup is None or setup.outcome not in ("LONG_SETUP", "SHORT_SETUP"):
                reason = setup.reason if setup else "MISSING_SOURCE_SNAPSHOT"
                direction = decision.direction or plan.plan_json.get("direction")
                setup_type = plan.plan_json.get("setup_type") or "unknown"
                regime = plan.plan_json.get("trend_regime") or "unknown"
                recent = D("999")
                extension = D("999")
            else:
                direction = setup.direction
                setup_type = setup.setup_type
                regime = setup.regime
                recent = _check_value(setup, "recent_run_atr")
                extension = _check_value(setup, "source_extension_atr")
                btc_reason, _ = btc_regime_guard(
                    session, plan.symbol, direction, decision.source_open_time
                )
                if btc_reason:
                    reason = btc_reason
                if reason is None:
                    try:
                        v4_plan = build_plan_v4(
                            plan.symbol,
                            setup,
                            current,
                            _quote(plan.evidence_json, plan.symbol),
                            _price_filter(plan.evidence_json),
                            plan.created_at,
                        )
                    except PlanRejected as exc:
                        reason = exc.code

            candidates.append(
                Candidate(
                    signal_id=plan.id,
                    symbol=plan.symbol,
                    direction=direction,
                    source_open_time=decision.source_open_time,
                    source_close=decision.source_open_time + HOUR,
                    published_at=plan.created_at,
                    setup_type=setup_type,
                    regime=regime,
                    recent_run_atr=recent,
                    source_extension_atr=extension,
                    favorable_050_at=outcome.favorable_050_at if outcome else None,
                    adverse_050_at=outcome.adverse_050_at if outcome else None,
                    historical_status=outcome.status if outcome else None,
                    historical_mfe_r=outcome.mfe_r if outcome else None,
                    historical_mae_r=outcome.mae_r if outcome else None,
                    historical_conservative_r=(
                        outcome.conservative_r if outcome else None
                    ),
                    historical_last_minute_open_time=(
                        outcome.last_minute_open_time if outcome else None
                    ),
                    v4_plan=v4_plan,
                    preliminary_reason=reason,
                )
            )
    return candidates


async def run(day: str) -> dict:
    candidates = load_candidates(day)
    states = await btc_15m_states([row.source_close for row in candidates])
    for row in candidates:
        if row.preliminary_reason is None:
            row.preliminary_reason = btc_timing_reason(
                states, row.source_close, row.direction
            )
    simulate(candidates)
    reasons = Counter(row.final_reason for row in candidates)
    survivors = [
        row for row in candidates if row.final_reason == "WOULD_PUBLISH_V4"
    ]
    portfolio_health = {}
    if survivors:
        async with httpx.AsyncClient(timeout=20) as client:
            public = BinancePublic(client)
            for row in survivors:
                row.v4_scaled_outcome = await scaled_outcome(public, row)
            boundaries = sorted({row.source_close for row in candidates})
            minute_cache = await survivor_minute_cache(
                public, survivors, max(boundaries)
            )
            portfolio_health = {
                str(boundary): portfolio_health_at(
                    survivors, minute_cache, boundary
                )
                for boundary in boundaries
            }
    simulate_with_active_cap(candidates)
    capped_survivors = [
        row for row in candidates if row.capped_reason == "WOULD_PUBLISH_V4"
    ]
    capped_reasons = Counter(row.capped_reason for row in candidates)
    suppressed = [
        row for row in candidates if row.final_reason != "WOULD_PUBLISH_V4"
    ]
    circuit = circuit_events(survivors)
    by_close = {}
    for row in candidates:
        key = str(row.source_close)
        bucket = by_close.setdefault(
            key,
            {"v2_publications": 0, "v4_would_publish": 0, "symbols": []},
        )
        bucket["v2_publications"] += 1
        if row.final_reason == "WOULD_PUBLISH_V4":
            bucket["v4_would_publish"] += 1
        bucket["symbols"].append(
            {
                "symbol": row.symbol,
                "direction": row.direction,
                "result": row.final_reason,
            }
        )
    return {
        "ist_date": day,
        "source_strategy": V2,
        "candidate_strategy": "MV-TREND-DUAL-v4",
        "read_only": True,
        "interpretation": (
            "Counterfactual safety diagnostic using actual V2 publications and "
            "their observational reference outcomes; not a profitability backtest."
        ),
        "v2_publications": len(candidates),
        "v4_would_publish": reasons.get("WOULD_PUBLISH_V4", 0),
        "v4_with_active_exposure_cap_would_publish": capped_reasons.get(
            "WOULD_PUBLISH_V4", 0
        ),
        "active_exposure_cap": 6,
        "active_exposure_cap_reasons": dict(sorted(capped_reasons.items())),
        "active_exposure_cap_scaled_conservative_r_sum": str(
            sum(
                (
                    D(row.v4_scaled_outcome["conservative_r"])
                    for row in capped_survivors
                    if row.v4_scaled_outcome
                    and row.v4_scaled_outcome.get("conservative_r") is not None
                ),
                D(0),
            )
        ),
        "suppressed": len(candidates) - reasons.get("WOULD_PUBLISH_V4", 0),
        "reasons": dict(sorted(reasons.items())),
        "directional_circuit_breaker_events": circuit,
        "directional_circuit_breaker_triggered": bool(circuit),
        "survivor_historical_statuses": dict(
            sorted(Counter(row.historical_status or "missing" for row in survivors).items())
        ),
        "survivor_v4_scaled_statuses": dict(
            sorted(
                Counter(
                    (row.v4_scaled_outcome or {}).get("status", "missing")
                    for row in survivors
                ).items()
            )
        ),
        "survivor_v4_scaled_conservative_r_sum": str(
            sum(
                (
                    D(row.v4_scaled_outcome["conservative_r"])
                    for row in survivors
                    if row.v4_scaled_outcome
                    and row.v4_scaled_outcome.get("conservative_r") is not None
                ),
                D(0),
            )
        ),
        "suppressed_historical_statuses": dict(
            sorted(Counter(row.historical_status or "missing" for row in suppressed).items())
        ),
        "by_source_close": by_close,
        "portfolio_health_by_source_close": portfolio_health,
        "signals": [
            {
                "v2_signal_id": row.signal_id,
                "symbol": row.symbol,
                "direction": row.direction,
                "source_open_time": row.source_open_time,
                "source_close": row.source_close,
                "setup_type": row.setup_type,
                "regime": row.regime,
                "recent_run_atr": str(row.recent_run_atr),
                "source_extension_atr": str(row.source_extension_atr),
                "result": row.final_reason,
                "result_with_active_exposure_cap": row.capped_reason,
                "historical_reference_outcome": {
                    "status": row.historical_status,
                    "mfe_r": row.historical_mfe_r,
                    "mae_r": row.historical_mae_r,
                    "conservative_r": row.historical_conservative_r,
                    "favorable_050_at": row.favorable_050_at,
                    "adverse_050_at": row.adverse_050_at,
                },
                "counterfactual_v4_scaled_outcome": row.v4_scaled_outcome,
            }
            for row in candidates
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ist-date", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    result = asyncio.run(run(args.ist_date))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
