"""Independent V2 outcome analytics worker.

This worker never imports the signal worker and never writes signal decision,
plan, slot or event tables.
"""
import argparse
import asyncio
import logging
from decimal import Decimal as D
from pathlib import Path

import httpx
from filelock import FileLock, Timeout
from sqlalchemy import select

from app.database import Session
from app.market.binance import BinancePublic, RateLimited, now_ms
from app.models import ServiceLease, SignalOutcome
from app.operations.lease import OWNERS, singleton, worker_transaction
from .service import (
    MINUTE_MS,
    MinuteBar,
    apply_minute,
    mark_source_revisions,
    seed_decision_opportunities,
    seed_signal_outcomes,
    update_decision_opportunities,
)

log = logging.getLogger("mv.analytics")


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


async def fetch_completed_minutes(public, symbol, start, server_now):
    last_completed_open = server_now // MINUTE_MS * MINUTE_MS - MINUTE_MS
    if start > last_completed_open:
        return []
    bars = []
    cursor = start
    while cursor <= last_completed_open:
        rows = await public.get(
            "/fapi/v1/klines",
            symbol=symbol,
            interval="1m",
            startTime=cursor,
            endTime=last_completed_open + MINUTE_MS - 1,
            limit=1000,
        )
        parsed = [parse_minute(row) for row in rows]
        parsed = [bar for bar in parsed if cursor <= bar.open_time <= last_completed_open]
        if not parsed:
            break
        if parsed[0].open_time != cursor:
            raise ValueError("Binance 1m outcome history has a gap at requested cursor")
        for previous, current in zip(parsed, parsed[1:]):
            if current.open_time != previous.open_time + MINUTE_MS:
                raise ValueError("Binance 1m outcome history is non-contiguous")
        bars.extend(parsed)
        next_cursor = parsed[-1].open_time + MINUTE_MS
        if next_cursor <= cursor:
            raise ValueError("Binance 1m outcome pagination did not advance")
        cursor = next_cursor
        if len(parsed) < 1000:
            break
    return bars


def sync_local_analytics(now):
    with worker_transaction("outcome-analytics", Session) as session:
        seeded_signals = seed_signal_outcomes(session, now)
        seeded_decisions = seed_decision_opportunities(session, now)
        revisions = mark_source_revisions(session, now)
        decisions = update_decision_opportunities(session, now)
        lease = session.get(ServiceLease, "outcome-analytics")
        if lease is not None:
            lease.heartbeat = now
        return seeded_signals, seeded_decisions, revisions, decisions


async def run(once=False):
    async with httpx.AsyncClient(timeout=15) as client:
        public = BinancePublic(client)
        while True:
            now = now_ms()
            seeded = sync_local_analytics(now)
            if any(seeded):
                log.info(
                    "analytics sync: signal_rows=%s decision_rows=%s revisions=%s decision_updates=%s",
                    *seeded,
                )

            try:
                server_now, _ = await public.clock()
            except RateLimited as exc:
                log.warning("Analytics clock rate limited; retrying in %.1fs", exc.retry_after)
                if once:
                    raise
                await asyncio.sleep(exc.retry_after)
                continue

            with Session() as session:
                active = list(
                    session.scalars(
                        select(SignalOutcome)
                        .where(SignalOutcome.status == "open")
                        .order_by(SignalOutcome.symbol, SignalOutcome.published_at, SignalOutcome.signal_id)
                    )
                )

            grouped = {}
            for row in active:
                start = row.first_observed_minute if row.last_minute_open_time is None else row.last_minute_open_time + MINUTE_MS
                grouped.setdefault(row.symbol, []).append((row.signal_id, start))

            for symbol, signals in grouped.items():
                start = min(item[1] for item in signals)
                try:
                    bars = await fetch_completed_minutes(public, symbol, start, server_now)
                except RateLimited as exc:
                    log.warning("Analytics %s rate limited; retrying later", symbol)
                    if once:
                        raise
                    await asyncio.sleep(exc.retry_after)
                    break
                except Exception as exc:
                    log.warning("Analytics fetch failed for %s: %s", symbol, exc)
                    with worker_transaction("outcome-analytics", Session) as session:
                        for signal_id, _ in signals:
                            row = session.get(SignalOutcome, signal_id)
                            if row and row.status == "open":
                                row.error_code = type(exc).__name__[:80]
                                row.updated_at = now_ms()
                    continue

                if not bars:
                    continue
                with worker_transaction("outcome-analytics", Session) as session:
                    for signal_id, required_start in signals:
                        row = session.get(SignalOutcome, signal_id)
                        if row is None or row.status != "open":
                            continue
                        for bar in bars:
                            if bar.open_time < required_start:
                                continue
                            apply_minute(row, bar)
                            if row.status != "open":
                                break

            sync_local_analytics(now_ms())
            if once:
                return
            await asyncio.sleep(15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        with FileLock(str(Path(__file__).resolve().parents[2] / ".analytics.lock"), timeout=0), singleton("outcome-analytics"):
            asyncio.run(run(args.once))
    except (Timeout, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
