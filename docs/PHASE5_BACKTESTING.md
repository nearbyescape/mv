# Phase 5: reproducible historical research

Implemented and exercised locally on 4 October 2026. The first fixed BTCUSDT/ETHUSDT experiment is complete; its results do not establish robust profitability. See [results](PHASE5_RESULTS.md) and [verification](VERIFICATION.md).

## Frozen scope

`packages/contracts/strategy-v1.json` remains the financial strategy authority. `packages/contracts/research-v1.json` records the research universe, chronological partitions, execution assumptions, sizing and uncertainty method. Parameters and scenarios were recorded before inspecting performance. No winner was selected and no rule was tuned against these results.

Both symbols use 1H triggers and exact completed 4H confirmation. Seeded EMA20/EMA50, SMA200 and Wilder ATR14 are computed separately on each timeframe at Decimal precision 34. Both research streams retain the original 1 October 2023 00:00 UTC seed origin through every partition. The research origins differ from this installation's September/July 2026 live warm-up origins; this is not an identical historical replay of the current installation's seeds.

| Partition | Inclusive start | Exclusive end |
| --- | --- | --- |
| Development | 2024-01-01 | 2025-01-01 |
| Validation | 2025-01-01 | 2025-07-01 |
| Final evaluation | 2025-07-01 | 2026-01-01 |

Each experiment starts flat with 10,000 USDT, split into independent 5,000 USDT symbol sleeves. Entry notional plus fee cannot exceed the positive current sleeve cash. Fractional research quantities are permitted. Positions cannot cross partitions; remaining positions are closed at the last minute close. These nine runs are separate experiments, not a continuously compounded portfolio. A retrospective chronological holdout is procedural separation, not a genuinely unseen forward market sample.

## Acquired data and source audit

The pipeline downloaded 162 Binance monthly USD-M futures archives: two symbols, three intervals (1m, 1H, 4H), October 2023 through December 2025. Every archive is pinned to its published SHA-256 checksum; exact decimal strings, OHLCV validity, candle boundaries and complete contiguous monthly coverage are checked before use. The compressed files occupy approximately 100 MiB. Funding acquisition pins 2,193 actual timestamp/rate/associated-mark-price events per symbol for 2024–2025. Missing coverage blocks replay rather than becoming zero funding.

The native higher-timeframe archives disagreed with raw-minute aggregation at 20 recorded candles. Selected direct REST checks also disagreed, so REST was not used as an unquestioned replacement. Before producing performance results, the source policy was amended to derive completed UTC 1H and 4H **OHLCV** from the checksum-validated 1m archives. The audit validated 2,370,240 minute rows. It preserves the original archives, original manifest, every native discrepancy and canonical replacement. Indicators are computed on each resulting timeframe; they are not resampled from 1m indicators. Canonical aggregation is a consistent research source, not proof of tick-level exchange truth.

`source-audit.json` exposes the corrections. `dataset-manifest.json` includes archive URLs, checksums, origins, actual funding coverage and dated exchange metadata. October 2026 price filters are applied across historical periods as an explicit approximation; historical price/quantity/notional filter changes have not been reconstructed. The chosen survivors do not form a survivorship-free Binance universe.

## Execution and accounting

The pure replay package calls the same backend setup evaluator and rounded risk-plan builder used by the live engine. At decision time T, it can see only the 1H source opening at T−1H, its predecessor at T−2H and the exact aligned completed 4H bar. Warm-up and readiness failures block entry. A held simulated position blocks another entry for that symbol.

| Scenario | Taker fee each side | Full spread | Adverse slippage each fill | Publication delay |
| --- | --- | --- | --- | --- |
| Baseline | 5 bps | 2 bps | 2 bps | 1 second |
| Higher cost | 10 bps | 4 bps | 5 bps | 1 second |
| Delayed entry | 5 bps | 2 bps | 2 bps | 120 seconds |

These are labeled assumptions, not verified account-specific Binance fees or measured historical spreads. Entry uses the next eligible minute open at or after publication availability: a one-second delay advances to the next minute, never the decision candle's close. Modeled bid/ask, freshness/expiry, EMA20-side and 0.5 ATR drift guards precede a slipped fill. Evidence identifies quotes as modeled. Frozen reference stop/target prices use the shared 2 ATR stop, outward exchange rounding and actual rounded 2R reference distance. Slippage changes realized entry risk; it does not rewrite the plan.

Existing funding due at a minute open is processed before gap exits. An adverse stop gap fills at the worse open; a favorable target gap receives only the target reference. Pending EMA50 exits execute at the next eligible open, with stops still active while waiting. New entries follow; closed-hour decisions schedule later entries. Funding inside a minute precedes its unknown intrabar exit. If both stop and target are touched within a minute, stop wins. Funding/exit ordering inside that minute is approximate, not tick accuracy. All exits pay modeled spread, adverse slippage and taker fees. Positive actual funding debits longs and credits shorts using quantity and the associated funding mark; negative funding reverses the signs.

EMA50 exits use a completed 1H close at/below EMA50 for longs and at/above it for shorts, followed by the next eligible modeled open. Fees, signed funding, gross/net P&L, actual-fill risk and R values are exact backend strings. Gross P&L already incorporates modeled spread/slippage; it excludes fees and funding. Fractional sizing and absence of liquidation mean this is not a leveraged futures-account simulator.

Equity and drawdown use hourly contract-price marks after paid costs. The displayed equity curve samples those marks daily; drawdown is computed from the hourly series. Open equity excludes hypothetical unpaid liquidation fees. MAE/MFE exclude unknown exit-minute extremes and are explicitly censored. Cash and a costed passive long-perpetual benchmark use the same partitions/capital and actual funding. Monthly uncertainty uses deterministic three-calendar-month moving blocks, 2,000 replications; six/twelve-month samples remain exploratory.

## Reproduce and inspect

After installing dependencies, run from `services/api`:

```powershell
..\..\.venv\Scripts\python -m app.research prepare
..\..\.venv\Scripts\python -m app.research audit
..\..\.venv\Scripts\python -m app.research run
```

`prepare` downloads/verifies data and performs the canonical audit. `audit` reruns that audit against pinned files. A local file lock prevents overlapping acquisition/replay. Raw data is stored under ignored `research-data/`; results under ignored `artifacts/backtests/`. Reusing an existing manifest preserves its pinned dataset. Keep these local artifacts to reproduce this exact identity; upstream archives can change.

Run identity includes the dataset, research specification, strategy contract and strategy/research source hash. Source changes during replay fail publication. Reports and exports are staged and atomically published; the latest pointer is atomically replaced. Repeating the final run reproduced every report/export byte exactly. The independent `tools/verify-backtest.py` uses rational arithmetic to check every recorded trade's trigger/alignment, drift, rounding, fills, both fees, actual funding and net P&L, plus report/export hashes and the protected API response.

The **Research** workspace displays all nine experiments, costs, hourly-derived risk statistics, per-symbol results, uncertainty, provenance and limitations. Downloads include report JSON, trade CSV, full evidence JSONL, dataset manifest and source audit. Protected read-only research APIs and the server-side website proxy validate identities/hashes and restrict export names/paths. An unavailable report displays an honest empty/offline state. This pipeline does not write the live signal database, change chosen coins, place orders or send alerts.

## Remaining research and release gates

The original plan's strategy ablations, SMA benchmark, walk-forward refitting, regime classification, wider history and candidate comparison are not implemented in this first baseline. Historical order-book depth, guaranteed fills, account-specific fees, historical filters and leveraged liquidation are unverified. Continuous forward paper tracking belongs to Phase 6, with an observed pilot later. Authentication, Telegram, AI, PostgreSQL runtime, remote CI and production deployment retain their separate gates.

## Primary source references

- [Binance public-data repository](https://github.com/binance/binance-public-data): archive layout, formats and published checksum verification.
- [Binance USD-M market-data documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data): funding history, pagination, timestamps and associated mark price.

These references were checked during implementation; actual archive checksums, REST funding and local replay were exercised separately.
