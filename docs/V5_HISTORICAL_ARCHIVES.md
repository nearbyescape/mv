# V5 historical archive acquisition — isolated pilot

**Status:** research-only, single-month archive pilot. Not a 30-coin backtest. No changes to live V4, collector, API database, Telegram or deployment. This branch stacks on the earlier V5 Reserved/decision-audit research branches.

## Evidence and scope

The separate October 10 research PostgreSQL clone currently has 30 chosen symbols with 18,560 contiguous 1H candles and 15,876 contiguous 4H candles (zero internal gaps). The beginning of each symbol's historical series varies. It does **not** have enough 1H / all-symbol 15m / 1m data to support a multi-month V5 execution study.

`packages/contracts/v5-history-v1.json` pins the current 30-symbol research universe, the four necessary Binance USD-M USDⓈ-M klines frames (1m, 15m, 1h, 4h), 2026-01-01 through 2026-10-01 exclusive, and calendar windows:
- Indicator warm-up: January–February 2026
- Development: March–May 2026
- Validation: June–July 2026
- Untouched holdout: August–September 2026

**This partition plan is a proposal frozen in source ahead of any August–September performance examination.** October 7–9 has already influenced the V5 design, and must never be described as a fresh holdout. A symbol/month before listing, with no published archive, must be documented as unavailable; the verifier never fabricates candles, fills gaps, or silently drops symbols. Inception, delisting, exchange venue changes and historical filter revisions need explicit eligibility manifests before full replay.

## Stage 1 — validate one archive

Use `services/api/app/research/v5_archives.py` to handle *one explicit symbol, timeframe and complete calendar month per invocation*. For example from the isolated API checkout, not the live container:

```sh
cd /work/services/api
python -m app.research.v5_archives plan \
  --root /research --symbol BTCUSDT --timeframe 1h --month 2026-04
```

`plan` makes no HTTP requests and writes no files. The operation produces the expected month range, row count, URL and spec digest. Then, after a separate operator check of permissions/resources:

```sh
python -m app.research.v5_archives fetch \
  --root /research --symbol BTCUSDT --timeframe 1h --month 2026-04
python -m app.research.v5_archives verify \
  --root /research --symbol BTCUSDT --timeframe 1h --month 2026-04
```

For safety, mount only the GitHub research checkout read-only at `/work`; mount a **different temporary research archive folder** at `/research` as the only persistent writable filesystem. Use a short-lived Docker container with a separate network (not the production Compose stack), a non-root UID, resource limits, no database credentials and no Telegram tokens.

The fetch verifies publisher SHA-256 via its `.CHECKSUM`, capped streamed ZIP download, full strict UTC monthly continuity, completed candle boundaries/valid OHLCV and expected candle count. It pins an archive-local JSON evidence manifest with the research specification checksum. Repeating a verified fetch is idempotent. A changed publisher checksum **fails closed without replacing the prior bytes**. If a process stops between archive and sidecar publication, recovery is a documented manual intervention, not an implicit overwrite.

No futures trade execution, P&L or risk claims are made by this stage. Binance USD-M reference prices and historical metadata are not direct Lighter fills or contract terms.

## Next stages after pilot verification

1. Add a resumable, rate-limited multi-month acquisition ledger with bounded disk/network budgets; account for contract inception, missing monthly artifacts and publisher revisions without lookahead.
2. Cross-validate independent 1m/15m/1h/4h source series; reconstruct indicators under a fixed historical origin with timestamp-by-timestamp source/lineage evidence; prove no lookahead and exact V4 comparison parity.
3. Build uninterrupted cross-day candidate/portfolio replay, fee/slippage/funding/latency scenarios, cautious intrabar assumptions, valid risk/exposure/kill-switch state, signal delivery feasibility, and complete open-position treatment.
4. Pre-register evaluation metrics and choose policies only on development/validation data. Holdout results should be evaluated once, after implementations, dataset integrity, and comparison policies are frozen.

**Caution:** Bulk downloading all 30 markets' 1-minute archives can consume multiple GB and significant CPU/disk, and must never start until the one-month pilot passes. Do not backfill the production market collector or production database.
