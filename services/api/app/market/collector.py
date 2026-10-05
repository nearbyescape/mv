"""One local writer: REST warm-up/reconciliation + routed finalized-candle WebSocket."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import random
import time

from filelock import FileLock, Timeout
import httpx
from sqlalchemy import select
from websockets.asyncio.client import connect

from mv_strategy import INTERVAL_MS
from app.operations.lease import worker_transaction
from app.database import Session
from app.models import CollectorStatus, MarketContract, WatchlistItem
from .binance import BinancePublic, RateLimited, now_ms, parse_stream_bar, validate_contract
from .store import apply_bars, repair_start

log = logging.getLogger("mv.collector")


def selected_symbols():
    with Session() as session:
        return list(session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order)))


class Collector:
    def __init__(self, public):
        self.public = public
        self.offset = 0
        self.last_event = None
        self.reconnects = 0
        self.catalog = {}
        self.catalog_at = 0.0
        self.catalog_checked_at = 0
        self.reconcile_interval = 75
        self.receive_timeout = 1

    def status(self, state, error=None):
        with worker_transaction("collector", Session) as session:
            row = session.get(CollectorStatus, "collector") or CollectorStatus(id="collector")
            row.state, row.error = state, error
            row.updated_at = now_ms()
            row.last_event_at = self.last_event
            row.clock_offset_ms, row.reconnects = self.offset, self.reconnects
            session.add(row)

    async def sync_stream(self, symbol, timeframe, server_now):
        step = INTERVAL_MS[timeframe]
        end = server_now // step * step - 1
        with Session() as session:
            start = repair_start(session, symbol, timeframe)
        bars = []
        cursor = start
        while True:
            limit = 500 if start is None else min(1000, max(1, (end - cursor + 1) // step))
            page = await self.public.klines(symbol, timeframe, end_time=end, start_time=cursor, limit=limit)
            bars.extend(page)
            if not page or start is None or page[-1].close_time >= end:
                break
            next_cursor = page[-1].open_time + step
            if cursor is not None and next_cursor <= cursor:
                raise ValueError("Exchange pagination did not advance")
            cursor = next_cursor
            if len(bars) > 100_000:
                raise ValueError("Gap exceeds the local repair budget; manual recovery required")
        with worker_transaction("collector", Session) as session:
            state = apply_bars(session, symbol, timeframe, bars, server_now)
        log.info("%s %s: %s completed bars, origin=%s", symbol, timeframe, state.count, state.history_origin)

    async def reconcile(self):
        server_now, self.offset = await self.public.clock()
        if time.monotonic() - self.catalog_at > 300 or not self.catalog:
            self.catalog = await self.public.catalog()
            self.catalog_at = time.monotonic()
            self.catalog_checked_at = now_ms()
        valid = []
        for symbol in selected_symbols():
            metadata = self.catalog.get(symbol)
            approved, reason = validate_contract(metadata)
            with worker_transaction("collector", Session) as session:
                row = session.get(MarketContract, symbol) or MarketContract(symbol=symbol)
                row.valid, row.reason, row.checked_at = approved, reason, self.catalog_checked_at
                row.metadata_json = metadata or {}
                session.add(row)
            if not approved:
                log.warning("Blocked %s: %s", symbol, reason)
                continue
            for frame in INTERVAL_MS:
                await self.sync_stream(symbol, frame, server_now)
            valid.append(symbol)
        return valid

    async def stream(self, symbols):
        streams = "/".join(f"{s.lower()}@kline_{tf}" for s in symbols for tf in INTERVAL_MS)
        address = "wss://fstream.binance.com/market/stream?streams=" + streams
        async with connect(address, open_timeout=15, close_timeout=5, ping_interval=60, ping_timeout=30, max_size=1_048_576) as ws:
            log.info("WebSocket connected: %s", ", ".join(symbols))
            last_message = last_sync = last_write = time.monotonic()
            selection = selected_symbols()
            reconciliation = None
            try:
                while True:
                    if reconciliation is not None and reconciliation.done():
                        reconciled = reconciliation.result()  # Propagate rate limits/data failures to normal recovery.
                        reconciliation = None
                        last_sync = time.monotonic()
                        if reconciled != symbols:
                            return
                    try:
                        payload = json.loads(await asyncio.wait_for(ws.recv(), timeout=self.receive_timeout))
                        if not isinstance(payload, dict):
                            raise ValueError("Malformed stream message")
                        data = payload.get("data", payload)
                        if not isinstance(data, dict) or data.get("e") != "kline":
                            if time.monotonic() - last_message > 30:
                                raise RuntimeError("WebSocket market messages stalled")
                            continue
                        parsed = parse_stream_bar(payload, symbols)
                        event_time = int(data["E"])
                        if abs(event_time - (now_ms() + self.offset)) > 5000:
                            raise ValueError("Market stream event exceeds freshness tolerance")
                        last_message = time.monotonic()
                        self.last_event = now_ms()
                        if parsed:
                            symbol, timeframe, bar = parsed
                            try:
                                with worker_transaction("collector", Session) as session:
                                    apply_bars(session, symbol, timeframe, [bar], event_time)
                            except ValueError:
                                # A missed final bar is repaired via REST before stream processing continues.
                                await self.sync_stream(symbol, timeframe, now_ms() + self.offset)
                    except asyncio.TimeoutError:
                        if time.monotonic() - last_message > 30:
                            raise RuntimeError("WebSocket market messages stalled")
                    current = time.monotonic()
                    if current - last_write >= 5:
                        self.status("streaming")
                        last_write = current
                        if selected_symbols() != selection:
                            log.info("Chosen-coin configuration changed; resubscribing")
                            return
                    if reconciliation is None and current - last_sync >= self.reconcile_interval:
                        # Read WebSocket messages throughout slow, sequential REST checks.
                        # Each database mutation remains in its own fenced transaction.
                        reconciliation = asyncio.create_task(self.reconcile())
            finally:
                if reconciliation is not None:
                    reconciliation.cancel()
                    await asyncio.gather(reconciliation, return_exceptions=True)

    async def run(self, once=False):
        backoff = 2
        try:
            while True:
                stream_started = None
                self.status("backfilling")
                try:
                    symbols = await self.reconcile()
                    if once:
                        self.status("snapshot-only")
                        return
                    if not symbols:
                        self.status("blocked", "No validated chosen contracts")
                        await asyncio.sleep(15)
                        continue
                    stream_started = time.monotonic()
                    await self.stream(symbols)
                    backoff = 2
                except Exception as exc:
                    if stream_started is not None and time.monotonic() - stream_started >= 60:
                        backoff = 2
                    delay = exc.retry_after if isinstance(exc, RateLimited) else backoff + random.random()
                    self.status("backoff", str(exc)[:300])
                    log.warning("Collector retry in %.1fs: %s", delay, exc)
                    if once:
                        raise
                    self.reconnects += 1
                    await asyncio.sleep(delay)
                    backoff = min(backoff * 2, 60)
        finally:
            if not once:
                self.status("stopped")


async def main(once=False):
    from app.operations.lease import singleton
    with singleton("collector"):
        async with httpx.AsyncClient(timeout=15) as client:
            await Collector(BinancePublic(client)).run(once=once)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Reconcile historical data and exit, without claiming a live connection")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # A single writer per local checkout. Distributed leases are a later deployment requirement.
    lock = FileLock(str(Path(__file__).resolve().parents[2] / ".collector.lock"), timeout=0)
    try:
        with lock:
            asyncio.run(main(args.once))
    except Timeout:
        raise SystemExit("A collector is already running for this local checkout")
    except KeyboardInterrupt:
        pass
