# Phase 4: deterministic signal engine

Implemented and checked locally on 4 October 2026. This phase publishes reference plans and evidence to the website. It does not establish profitability or implement fills, automatic exits, Telegram, AI or exchange orders.

## Rules and arithmetic

The financial baseline is `packages/contracts/strategy-v1.json`, version `EMA-PULLBACK-ATR-v1`. Startup refuses silent edits to its supported financial rules. Indicators use the Phase 3 history origins, SMA-seeded EMA20/50, SMA200, Wilder ATR14 and 34-digit Decimal arithmetic. Both timeframes require at least 500 completed bars.

A long requires current 1H `EMA20 > EMA50 > SMA200`, previous close at or below its own EMA20, and current close strictly above its own EMA20. A short mirrors every inequality. Ordinary aligned trends, EMA equality and intrabar wick touches do not trigger entries. Source ATR14 must be positive.

Confirmation uses the completed 4H snapshot determined by the 1H close boundary, with matching EMA/SMA ordering and close beyond EMA20 in the chosen direction. At 08:00 UTC the required 4H candle opened at 04:00; at 07:00 it opened at 00:00. A missing exact snapshot waits within the entry window; it never substitutes an older or unfinished candle.

Pure strategy functions have no exchange, database or browser dependencies. Numeric evidence and levels serialize as exact strings. Browser numbers format charts/prices; the browser cannot originate a plan.

## Entry guards and frozen levels

Only a qualifying, otherwise eligible setup requests `/fapi/v1/ticker/bookTicker` for its symbol. Both bid/ask prices and quantities must be finite positive values, with bid at or below ask and a valid symbol. Preserve Binance's transaction timestamp separately from HTTP receipt time. Quote time must be after the source close, not after receipt/publication, and no more than five seconds old against the collector-adjusted exchange clock.

Use the ask for a long reference entry and bid for a short. Entry must remain strictly beyond source EMA20 and within 0.5 frozen source ATR14 of the source close. The entry window ends exactly five minutes after source close; delayed data/quotes cannot extend it. Contract validation, live collector, selected-symbol membership, current source, warm-up, contiguous lineage and checkpoint alignment are checked again before publication.

For a long, raw stop is `entry - 2 * frozen ATR`; round down to the permitted price grid. For a short, use `entry + 2 * frozen ATR` and round up. Risk distance is the absolute difference between entry and the rounded stop. Target is two times that actual risk distance from entry, rounded down for a long/up for a short. Outward stop rounding is therefore included in target distance. Invalid/nonpositive geometry or out-of-range levels reject the setup.

The USD-M price-filter grid is `(price - minPrice) % tickSize == 0`, with zero min/max bounds disabled. Rounding uses this origin. Bid/ask and entry/stop/target pass the filter. No quantity, leverage, minimum position notional, fee or funding calculation is claimed here because this phase places no orders or paper fills.

## Durable evaluation and publication

Collector and decision worker are separate processes. The worker scans about once a second, with pending retries spaced at least 1.5 seconds. HTTP calls are sequential and limited to eligible candidates. Rate limits respect `Retry-After`; unavailable/stale quotes can retry within expiry. Excess drift, wrong entry side and invalid risk geometry are terminal rejection reasons. These timings describe implementation, not measured throughput or latency guarantees.

Per-symbol/strategy cursors persist. On first activation the worker waits for live, warmed, current 1H and exact 4H heads, records a `BASELINE` decision and starts from that boundary. Downloaded history does not become live entries. On restart, retained cursors discover later completed bars in batches; expired recovered setups never become live entries.

A SHA-256 decision identity includes strategy, venue, symbol, timeframe and source-open timestamp. The database also enforces uniqueness for that boundary and one slot per symbol/strategy. Discovery, cursor changes and decisions are committed together.

Evaluation captures source evidence/eligibility inside a transaction, then obtains the quote outside it. Final publication re-reads the source/metadata fingerprint and all guards. A change during quote retrieval causes a retry. The final transaction atomically commits decision outcome, immutable plan/evidence, reserved slot and published event. SQLite uses `BEGIN IMMEDIATE` before final reads; operator writes do too. Rollback/constraint tests verify that a failed commit leaves no partial plan/slot/event.

One FileLock prevents duplicate local decision workers. SQLite constraints/transactions support this local checkout. Distributed leases, multiple-machine races and PostgreSQL isolation/concurrency remain production work; they are not verified by SQLite tests.

## Slot state and corrections

Published plans reserve a slot until their five-minute entry window closes. An unaccepted reservation expires and frees the slot. An operator can **Mark as held** while the plan remains actionable, or **Release signal slot**. Retries are idempotent and recorded as events. Held slots survive entry expiry and block further signals for that coin until explicit release.

This is operator-reported state, not exchange position detection, a fill model or a trade ledger. The contract's EMA50 trend exit and stop/target observation belong to the later paper lifecycle. They do not silently auto-release an operator-held slot in this phase.

Every ten seconds the worker compares retained source, previous and confirmation lineage with published evidence, for the latest 100 plans plus all active slots. A corrected/missing source produces one source-revised event and withdraws entry eligibility. Reserved slots are released; held slots remain until operator release. Original levels, ATR and evidence never change. Older inactive records outside this scan are not continuously audited for later revisions.

Evidence SHA-256 covers exact snapshots, origins, lineage/source hashes, contract/metadata, rules, quote and guards. A separate checksum covers the frozen plan, including its evidence hash. Read/action paths block entry actions when checksums fail. These detect inconsistent stored content; they are not signed proofs against an attacker able to rewrite data and hashes.

## Website and API

Protected `GET /v1/signals` returns recent plans plus every active slot owner, latest 25 decisions, engine heartbeat and exchange-adjusted server time. `GET /v1/signals/{id}` provides detail. `POST /v1/signals/{id}/slot` accepts bounded hold/release notes. Invalid transitions return 409; the client updates state only after successful persistence and refresh.

The Next.js proxy keeps the local credential server-side. Writes require same-origin loopback requests. The default journal shows committed plans only, with an honest empty state. Signal polling runs every eight seconds after completion; local expiry updates between polls. Cached records remain visible on API failure with actions paused. Evidence JSON and CSV exports preserve backend numeric strings.

The responsive workspace includes real charts, an engine monitor, frozen levels, exact evidence tables, guards, checksums, UTC timestamps and events. Tables scroll internally with keyboard access. Explicit Demo mode retains labeled illustrations and is never a fallback for failed live data.

AI and Telegram are displayed as not configured. Future AI work may annotate persisted evidence asynchronously; it cannot originate signals, change levels or block deterministic publication.

## Run and verify

Use the four processes in `README.md`, including `python -m app.signals.worker` from `services/api`. Apply Alembic through revision `0003_signal_engine`. `--once` performs one scan and ends with stopped status.

Pure arithmetic, state-machine, isolated service/API and desktop/mobile browser checks are recorded in `VERIFICATION.md`. The browser fixture comes from the actual backend evaluated against controlled bars and never enters the live journal. `tools/verify-signal-engine.py` checks actual worker/cursors, stored checksums and fresh public quotes without changing state.

Real baselines, fresh quotes and an actual BTC long publication at the 4 October 02:00 UTC close were observed; ETH had no fresh trigger. The real journal/evidence download matched the plan, independent rational rule/rounding checks passed, and its unaccepted slot expired after five minutes while retaining the plan. Operator transitions/failure scenarios remain isolated test demonstrations. The subsequent [Phase 5 historical evaluation](PHASE5_RESULTS.md) includes execution/costs and does not establish robust profitability; continuous paper tracking remains later work.

## Primary references

- [Binance USD-M market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data): symbol-specific book ticker, quantities, transaction timestamp and request weights.
- [Binance USD-M common definitions](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/common-definition): PRICE_FILTER bounds and min-price-relative tick grid.

These official references were checked during implementation; actual public quotes were exercised separately.
