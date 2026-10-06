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
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, text

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
    preliminary_reason: str | None = None
    final_reason: str | None = None

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
        passed = (
            bar.close > current["ema20"] > current["ema50"]
            and current["ema20"] >= previous["ema20"]
        )
    else:
        passed = (
            bar.close < current["ema20"] < current["ema50"]
            and current["ema20"] <= previous["ema20"]
        )
    return None if passed else "BTC_15M_TIMING_CONFLICT"


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
                        build_plan_v4(
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
    return {
        "ist_date": day,
        "source_strategy": V2,
        "candidate_strategy": "MV-TREND-DUAL-v4",
        "read_only": True,
        "v2_publications": len(candidates),
        "v4_would_publish": reasons.get("WOULD_PUBLISH_V4", 0),
        "suppressed": len(candidates) - reasons.get("WOULD_PUBLISH_V4", 0),
        "reasons": dict(sorted(reasons.items())),
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
