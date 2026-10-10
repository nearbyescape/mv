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


## Stage 1b — strictly bounded month-series pilot

After the one-archive integrity pilot passes, run the second entry point
`python -m app.research.v5_archive_batch` **in the same isolated read-only-code / writable-research-only container layout**, never inside the production Compose stack. It accepts exactly **one frozen-universe symbol and one timeframe**, plus an inclusive calendar-month range of **at most six months**. Example three-month 1H-only pilot:

```sh
python -m app.research.v5_archive_batch plan --root /research \
  --symbol BTCUSDT --timeframe 1h --start-month 2026-04 --end-month 2026-06

python -m app.research.v5_archive_batch fetch --root /research \
  --symbol BTCUSDT --timeframe 1h --start-month 2026-04 --end-month 2026-06 \
  --max-new-mib 64 --min-free-mib 2048 --confirm-fetch

python -m app.research.v5_archive_batch verify --root /research \
  --symbol BTCUSDT --timeframe 1h --start-month 2026-04 --end-month 2026-06
```

`plan` has **no network or disk writes**. `verify` reads local archives only.
`fetch` requires an explicit `--confirm-fetch` flag, downloads serially, sleeps at
least half a second between archives, enforces at most **256 MiB of newly downloaded
compressed ZIP bytes per invocation**, and refuses to run if available storage is
below the requested reserve plus the next archive's byte budget. Existing pinned
archives are rechecked against publisher SHA-256 without counting their bytes as
new downloads.

Each attempted month appends a fsynced evidence event to a JSONL audit ledger.
An unavailable publisher archive is labeled `SOURCE_HTTP_404_REQUIRES_REVIEW`
and **stops the batch**; 404 cannot be used to infer contract inception or fill
gaps. On interruption the next invocation revalidates any completed archive, then
continues with missing months. If archive/sidecar publication was interrupted, an
operator must inspect the orphan files instead of automatically replacing them.

The full 30-symbol, four-timeframe 2026 dataset is **not** yet authorized for
unattended bulk acquisition. The month-series pilot is only the first controlled
increment.


## Stage 1c — independent month seam and 1H/4H reconciliation

After individual monthly ZIPs have verified locally, the **read-only, offline**
`v5_archive_audit.py` entry point can verify every candle across month
boundaries and issue a SHA-256 fingerprint for the ordered decimal OHLCV
series:

```sh
python -m app.research.v5_archive_audit continuity \
  --root /research --symbol BTCUSDT --timeframe 1h \
  --start-month 2026-04 --end-month 2026-06
```

This requires no 4h history. When the corresponding three native 4h months
have also been pinned, check both series and compare the exact 1h→4h
aggregation against the independent 4h archive:

```sh
python -m app.research.v5_archive_audit reconcile-1h-4h \
  --root /research --symbol BTCUSDT \
  --start-month 2026-04 --end-month 2026-06
```

The CLI emits JSON containing counts, canonical source-series hashes, source
mismatch field counts and up to eight concrete OHLCV discrepancies. Exit code 3
means native independently published datasets disagree, **not** that the
downloader failed or that trading performance is negative. Never silently
accept one series or rewrite source candles: investigate Binance archive
corrections and document any chosen canonicalization before indicator replay.

This does not prove 1m/15m source equivalence and is not yet a historical
trading backtest. Archive source auditing remains a separate gate.


## Stage 1d — 15-minute trigger source audit

After downloading and verifying independent BTCUSDT 15m archives for
2026-04 through 2026-06 using the **existing one-symbol, one-timeframe,
six-month-capped batch CLI**, reconcile every hourly candle against four
completed 15m bars:

```sh
python -m app.research.v5_archive_audit reconcile-15m-1h \
  --root /research --symbol BTCUSDT \
  --start-month 2026-04 --end-month 2026-06
```

The command is strictly offline and read-only and audits month seams in both
timeframes. The expected BTC sample is 8,736 fifteen-minute candles and
2,184 hourly candles. It emits independently pinned source fingerprints, exact
Decimal OHLCV mismatch counts and no more than eight example discrepancies.
On any source mismatch it exits with code 3, requiring investigation before
indicator construction or V5 strategy evaluation.

**No inference of 15m execution fills is made from this aggregation.** The
separate 1m history, entry latency and exchange-specific fees/funding still
need validation before portfolio P&L research.


## Stage 1e — raw 1-minute execution-reference source validation

A separate, streaming, **read-only** audit compares each independent native
15m bar against all 15 closed 1m bars using Decimal OHLCV, with strict
month-boundary continuity, source SHA-256 manifests and a bounded mismatch
sample. The 1m archive parser uses its existing dedicated 60-second bar
validator. It does **not** infer intraminute tick order, order-book execution,
actual Lighter fills, funding or spread from OHLCV.

To control resources, first run a **single April 2026 BTCUSDT/1m acquisition**
and verify its SHA-256, complete 43,200 one-minute rows and exact independent
2,880-bar 15m aggregation. The two-month continuation is a later operator
decision. A full April–June dataset would contain 131,040 one-minute bars and
8,736 independent 15m bars.

After verified acquisition, this offline inspection compares source histories:

```sh
python -m app.research.v5_archive_audit reconcile-1m-15m \
  --root /research --symbol BTCUSDT \
  --start-month 2026-04 --end-month 2026-04
```

Any OHLCV disagreement emits `disposition=REVIEW_REQUIRED` and exits
with code 3, without editing source archives. The audit runs only in the
disposable research container, with all repository files and archived ZIPs
mounted **read-only**, and with `--network none`.


## Stage 2 — exact live-indicator reconstruction (read-only)

After three months of independently audited BTCUSDT 15m, 1h and 4h
archives, the offline `v5_indicator_audit` CLI replays the *same*
`mv_strategy.indicators.IndicatorState` implementation as the running
market collector, continuously from the **first archived candle**.
No SQL, HTTP, exchange keys, or production services are accessed:

```sh
python -m app.research.v5_indicator_audit \
  --root /research --symbol BTCUSDT \
  --start-month 2026-04 --end-month 2026-06
```

It independently verifies each source manifest and cross-month continuity,
recomputes every EMA20, EMA50, SMA200, and ATR14 from completed candles,
and asserts reconstructed `Snapshot.validate()` passes. Only the close
boundary `bar.close_time + 1` is eligible as evidence as-of time.
During each monthly transition a serialized `IndicatorState.dump()`
is restored and replayed alongside the uninterrupted original stream:
values and complete state/lineage must match exactly on every later candle.
Both snapshots and boundary checkpoints receive deterministic SHA-256
fingerprints, without writing report files or touching any live database.

**Crucial warmup:** V5 requires **500 closed bars on each timeframe**,
not just the 200 bars to compute SMA200. A 4h series starting 2026-04-01
has only 546 complete candles through June 30, so no hypothetical trade
should be evaluated in April or May on that source origin; the first
4h-eligible timestamp only occurs in late June. The January–February
2026 pinned warmup archives must be acquired before any March–May
development performance research. That research must also explicitly
test origin parity with the intended historical evaluation seed; changing
the start of EMA seeds changes values, and this audit does not claim
backtest parity with live September 2026 checkpoints.

This stage proves source-to-indicator determinism for one symbol and
fixed origin, *not* that V5's entry decisions, execution costs, or portfolio
P&L have passed historical validation.
