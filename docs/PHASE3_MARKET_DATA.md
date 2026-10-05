# Phase 3: market data and indicators

Implemented locally on 3 October 2026. Signals were disabled then; the separate worker and website journal are now implemented in [Phase 4](PHASE4_SIGNAL_ENGINE.md). Public reads require no Binance account key; there are no account or order endpoints.

## Data path

Chosen coins in SQLite → Binance contract validation → REST history/repair → finalized WebSocket candles → atomic candle, indicator snapshot and checkpoint transaction → protected FastAPI read → server-only Next.js proxy → chart.

The collector is a separate process. Stopping it does not stop the API or hide retained history. The dashboard distinguishes retained data from a live, ready feed. DeepSeek is not part of this path.

## Contracts and collection

- Only chosen symbols, originally maximum 20; release 0.8.1 raises the validated boundary to 30. Two streams per symbol cover 1H and 4H.
- Require `TRADING`, `PERPETUAL`, USDT quote/margin and crypto `underlyingType=COIN`. Verify positive price tick, quantity step/minimum and minimum notional filters.
- Catalog fetch TTL: 300 seconds. Readiness refuses validation older than 600 seconds; cached validation retains its actual fetch timestamp.
- Cold start downloads 500 completed candles per timeframe. Current unfinished candles are excluded using the Binance server-time boundary.
- The live connection uses `wss://fstream.binance.com/market/stream?streams=...` and resubscribes when chosen coins change.
- Partial candle messages are validated for schema/symbol/timeframe/OHLCV and refresh stream liveness; only `x=true` bars enter storage. A finalized bar requires event time after its close boundary. Event time must be within five seconds of the synchronized exchange clock.
- REST reconciliation runs about every 75 seconds, refreshes clock offset and revisits the last three bars. It repairs detected historical gaps using paginated requests. Valid changed source bars trigger full replay from the retained origin.
- HTTP 418/429 respects `Retry-After`. Other failures reconnect with exponential backoff, jitter and a 60-second cap. A stable stream resets backoff. Stalled market messages and invalid events reconnect.

Recent lookback requests use the needed small limit; cold history uses 500 and long repairs use at most 1,000 per page. This avoids requesting 1,000 candles every time three suffice. Exchange I/O is sequential in this local milestone; there is no claim of production throughput.

## Financial arithmetic

`packages/strategy` uses Python Decimal with precision 34 and half-even arithmetic. Exchange OHLCV strings persist exactly; JSON outputs remain strings. Float conversion occurs only in browser chart rendering.

- EMA20 is seeded with the first 20 closes, at zero-based index 19; EMA50 uses the first 50, at index 49. Later values use alpha `2/(period+1)`.
- SMA200 is the mean of the current 200 closes, first available at index 199.
- True range begins at candle index 1 because it needs a previous close. Wilder ATR14 is seeded with ranges from indices 1 through 14, first available at index 14. Later ATR is `(13 * previous ATR + current TR) / 14`.
- Mathematical availability is separate from operational readiness: both timeframes require at least 500 completed bars.
- Required 4H confirmation is derived from the 1H close boundary, never message arrival order. At 08:00 UTC, the required 4H source opened at 04:00; at 07:00 the source opened at 00:00. A missing required snapshot blocks confirmation.

Source timestamps must align to the timeframe and be contiguous. Invalid geometry, negative volume, non-finite prices, duplicates, time reversal and gaps are rejected before advancing state. The collector emits indicators, not financial plans. Entry/stop/target rounding is implemented by the separate Phase 4 engine.

## Persistence and recovery

Candles and indicator snapshots have a `(symbol, timeframe, open_time)` primary key. Source hashes detect changed final bars; rolling lineage ties snapshots to their source history. Versioned checkpoints store recursive EMA/ATR values, previous close, the 200-close window, original history origin and count.

A normal append restores its checkpoint and advances only new bars. Restart lookbacks are idempotent and do not reseed from the latest 500 bars. A correction or restored old missing bar replays all retained source history from the original origin, in the same transaction as snapshots and checkpoint. Failure rolls the transaction back.

The local checkout uses FileLock to enforce one collector writer. The retained history has no rolling deletion policy. A gap repair is bounded to about 100,000 returned bars; an excessive repair reports a recovery error. Full replay and gap scanning grow with retained history. Retention, database corruption recovery, long-history optimization, distributed leases and PostgreSQL concurrency require separate production work.

## Readiness and website

`GET /v1/markets` returns chosen-market summaries; `GET /v1/markets/{symbol}?timeframe=1h|4h` returns at most 120 chart bars, exact indicator strings and provenance. Unchosen symbols return 404. The local bearer token stays in the server-side proxy.

Readiness requires a current validated contract, 500 bars on both timeframes, expected latest completed boundaries, matching snapshot/checkpoint lineage, a streaming collector, and heartbeat/received-event ages within 30 seconds. Clock offset beyond five seconds also blocks readiness. Status distinguishes ready, pending validation, blocked contract, warming up and stale.

Charts poll every ten seconds after the previous request completes. Summary/health polling is every fifteen seconds. The chart shows the last completed close rather than a live tradable quote; the percentage is the change between the latest two completed candles, not a 24-hour return. Quotes and reference plans are handled separately by the Phase 4 engine.

On API failure, retained chart data are labeled unavailable. There is no automatic synthetic fallback. Explicit Demo mode supports BTC/ETH illustrations. The default journal now contains committed Phase 4 plans only; synthetic journal/setup examples appear only in Demo mode.

## Running and checking

Follow the current four-process setup in `README.md` (API, collector, signal worker, web). For a historical-only snapshot, use `python -m app.market.collector --once` from `services/api`; this reports `snapshot-only`, not live.

From the repository root, with API and collector running:

```powershell
.venv\Scripts\python tools/verify-market-data.py
node tools/check-integration.mjs
node tools/check-accessibility.mjs
node tools/capture-preview.mjs
```

The read-only market check compares the most recent three stored bars on each chosen timeframe directly with Binance REST, verifies a bit-identical full checkpoint replay, compares all four indicators to independent rational calculations, and requires current API market readiness without assuming signals are disabled. It saves a report under ignored `artifacts/`. It intentionally fails when the feed is not ready and uses real network data, separately from deterministic CI tests.

## Source references

- [Binance USD-M REST market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data): time, catalog, candle limits and request weights.
- [Binance routed WebSocket connection](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Connect): `/market` routing, combined streams, connection lifetime and ping/pong rules.
- [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html): connection, timeout and keepalive API.

Official exchange documentation was checked during implementation. Actual REST and market WebSocket connectivity were also exercised locally; see `VERIFICATION.md` for the observed results and remaining limits.
