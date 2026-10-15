# V7Sonic — microstructure evidence + prospective paper scanner (V1)

**Classification:** Development / research only. NOT a production release.
Not a trained or independently calibrated strategy. No claims of profit,
predictive probabilities, live fills, or verified stop/target crossing.

## What was implemented

- Six existing liquid USDT futures symbols: BTC, ETH, SOL, XRP, DOGE, BNB.
- Strict public REST-only fixed-origin reads:
  `/fapi/v1/time`, `/fapi/v1/depth?limit=20`,
  `/fapi/v1/openInterest`, `/futures/data/takerlongshortRatio?period=5m`,
  `/fapi/v1/premiumIndex`.
- Evidence fields: receive time, server clock, 20-level book update ID, spread,
  top-10 liquidity imbalance, illustrative $1,000 impact, latest completed
  5m taker buy/sell volume, open interest, mark and latest funding rate.
- Reject malformed, crossed, mismatched, clock-skewed, incomplete and stale
  observations. **A REST depth snapshot cannot verify book sequence or
  simultaneous matching of five separate endpoint responses.**
- A frozen *hypothesis*: compare sequential 5-minute observations.
  Require increasing OI, directional completed-period aggressive flow,
  compatible depth imbalance, non-extreme funding, sufficiently narrow
  spread / displayed liquidity, an upcoming funding boundary beyond
  the 120-minute paper observation horizon, and favorable illustrative
  after-cost target. We reject references that might cross an unmodeled
  funding settlement rather than silently assume it costs nothing.
  Otherwise **ABSTAIN**. This is NOT a trained win probability.
- Independent, append-only SQLite research journal; SHA256 payloads and
  chain links, duplicate-safe insertion, three-hour symbol cooldown and
  maximum four overlapping reference ideas. SHA256 is not an
  authenticated exchange signature.
- Subsequent **15, 30, 60, 120-minute** time-point observations produce
  separate marked net R measurements against the previously frozen paper
  entry, with opposing book touch and modeled 8bps per side fees/slippage.
  The snapshot-based marks do **not** verify intrabar stop or target fills.
- No legacy `SignalPlan`, `SignalEvent`, `TelegramDelivery`, live PostgreSQL,
  `V7ClientApproval`, or exchange order writes. Production Compose remains
  untouched; retired V4 engine must stay stopped.

## Execute safely

**Offline report (no Binance network):**

```bash
python -m app.microstructure.cli --db /absolute/private/path/evidence.sqlite report
```

Read-only report requires an existing journal; otherwise exits with an
error instead of inventing measurements.

**One explicit bounded six-market public observation:**

```bash
python -m app.microstructure.cli --db /absolute/private/path/evidence.sqlite \
  observe --allow-public-market-data --confirm-paper-only --iterations 1
```

One observation cannot create a trade: two separate recent observations
are required. Network use is explicit and public GET only; a missing
endpoint fails the batch instead of manufacturing values.

**Optional opt-in collector, separate Docker Compose project:**

```bash
mkdir -p artifacts/v7-microstructure-paper
sudo chown 10001:10001 artifacts/v7-microstructure-paper
docker compose -f compose.microstructure-paper.yml \
  --profile isolated-research up -d --build prospective-collector
```

The independent `mv-v7-microstructure-paper` project has **no published
ports, no secrets, no production database or Telegram mounts**, and its
container restart policy is `no`. It polls no faster than 5 minutes.
This is an example operator-controlled launch, **not something executed
by this change**. Check the exact compose config and destination rights
before starting it; do not append it to production compose arguments.

Stop (does not modify V4):
```bash
docker compose -f compose.microstructure-paper.yml \
  --profile isolated-research stop prospective-collector
```

Report, with a separately launched disposable API image and journal mounted
read-only, or from a Python environment containing this package:
```bash
python -m app.microstructure.cli \
  --db /absolute/private/path/evidence.sqlite report
```

## Interpretation and gates

- The first useful prospective measurement requires separate completed
  historical **observations** that were captured before subsequent prices.
  No six-month candles-only backtest can validate depth or order flow.
- The measured positive-at-horizon fraction is **not** a trade win rate.
  A price could cross an unseen stop and recover between samples.
- Test realistic fill simulation with granular quotes, latency and
  exchange-fee/funding records before publishing anything.
- Minimum next experiment: several weeks of contiguous live-collected
  evidence across different sessions, followed by frozen-rule,
  independent out-of-sample evaluation with costs, day-cluster CIs and
  explicit sample count requirements. Compare against no-trade and
  simple momentum baselines. Never select filters using the eventual
  prospective holdout, or repeatedly retune to make it pass.
- Full order-book sequence integrity would require websocket diff-depth
  buffering, snapshot resynchronization and chain-gap rejection.
  This V1 deliberately **does not** claim that capability.

## External source access and smoke-test result

On **2026-10-15**, GitHub's hosted Actions runner received HTTP **451**
from `https://fapi.binance.com/fapi/v1/time` before any market data
could be acquired. The single-probe research workflow correctly failed
without writing fake observations or retrying via an alternate host.
See the Actions run `38688171067`. To avoid turning every PR into a
geo/network-dependent check, that separate live-source workflow is now
**manual-only**; the full offline synthetic/SQL/browser CI remains
required. This is an external region/network-access restriction,
**not evidence that Binance is reachable from the VPS**. Access
and compliance must be independently checked before any operator-led
paper collection. Do not use alternate endpoints or proxy routes to
evade regional restrictions.

## Collector cadence correction (15 October 2026)

The original collector scheduled cycles 300 seconds apart based on loop
**start** time, while `observed_at_ms` was taken when each separate REST
capture completed. Real VPS observations were 299.904–299.937 seconds
apart. That is strictly less than the causal classifier's required
300,000 milliseconds and produced `NONCONTIGUOUS_OBSERVATIONS`
despite apparently normal five-minute collection.

The corrected sampler schedules against `MAX(observed_at_ms)` in the
committed SQLite research journal, across all six symbols, plus a
2-second guard. It repeats the deadline check after waking and honors
the stored timestamp on every restart. **The >=300-second classifier
threshold and paper strategy parameters are not changed.** The old
observations remain intact and can be used as raw data; we do not
rewrite timestamps or retroactively create paper signals.

The timing update requires rebuilding and recreating **only** the
isolated `mv-v7-microstructure-paper` container after source verification
and a cold backup of its journal. Never switch production V4 Compose
services or delete the evidence journal. Apply the tested exact commit
and verify the new image and the subsequent measured intervals.

## Real VPS post-upgrade timing verified (15 October 2026)

The operator supplied two subsequent post-upgrade samples per market;
all six intervals exceeded the frozen 300-second minimum:

- BTC 306813ms, ETH 306799ms, SOL 306780ms
- XRP 306495ms, DOGE 306493ms, BNB 306500ms

Collector `up` and no exchange orders or Telegram publication. Observed
first-failure abstentions were `STALE_TAKER_PERIOD` and
`FUNDING_WINDOW_UNMODELED`. These are market-data/eligibility issues,
**not** evidence of a profitable or unprofitable strategy. A high
abstention fraction would limit coverage even if the model were otherwise
good.

Use the new independent audit to quantify causes from already committed
journal evidence, with **no market network** and **no strategy changes**:

```bash
python -m app.microstructure.cli \
  --db /absolute/private/path/evidence.sqlite \
  diagnose --last-samples-per-symbol 288
```

`first_failure_classifier_totals` is an ordered, mutually exclusive
reason for each adjacent observation pair. `independent_blockers_overlapping_totals`
separately measures timing, taker-period advancement and upcoming-funding
eligibility; its counts may overlap and should **not** be added.
`preportfolio_candidates_not_actual_published_signals` is the frozen
classifier's hypothetical passing output before cooldown and portfolio
limits, **not** actual orders, Telegram publications, or observed trade
wins. The audit reads SQLite read-only, verifies every hash chain, and
does not backfill or alter historic decision logs.

Historical Binance exchange responses may publish completed taker
intervals with latency; reject repeated taker periods rather than reuse
them. Funding boundaries are intentionally kept out of paper outcomes
until funding is priced consistently. Do not relax rules to force signals.

## Bounded transient-source recovery (15 October 2026)

The continuous, isolated `prospective-collector` now tolerates at most
**two delayed retry attempts** after a transient public market-data batch
failure (timeout, transport interruption, a 5xx upstream response, or
invalid/stale normalized public snapshot). Each retry is at least
**300 seconds** after the failed attempt, never inside the same 5-minute
candle. The third consecutive failure **halts the process** and requires
operator review. A successful full batch resets the failure counter.

No partial six-market batch is written on a failed capture; the journal
is unchanged by skipped attempts and the report logs a structured
`PUBLIC_MARKET_PAPER_COLLECTION_GAP` event with zero committed
observations and zero trade/Telegram actions. After a long gap, the
frozen classifier rejects noncontiguous observations until two valid
fresh measurements arrive.

**No automatic retry for HTTP418/429 rate limits, HTTP451 legal/region
denials, other client 4xx, SQLite errors, hash-chain failures, or
unknown runtime exceptions.** Such conditions halt immediately, as
does repeated failure. No alternative API host, proxy bypass, forceful
restart policy or new market data sources. A single bounded
`--iterations 1` run also remains single-attempt.

Operator checks on the isolated VPS:

```bash
docker compose -f /var/tmp/mv-v7-microstructure/compose.microstructure-paper.yml \
 -f /srv/mv-v7-microstructure/compose.storage.yml \
 --profile isolated-research ps -a prospective-collector
docker compose -f /var/tmp/mv-v7-microstructure/compose.microstructure-paper.yml \
 -f /srv/mv-v7-microstructure/compose.storage.yml \
 --profile isolated-research logs --tail=40 prospective-collector
```

The Compose restart policy remains **`no`** and no consumer or order
publisher is connected. This is safety-bounded data collection, **not**
an always-on SLA; any halt must be observed and resolved manually.
Do not promote the experimental strategy based on successful recovery.

## Operational safety

The sampler never reads exchange/private keys, never imports
`app.telegram`, never calls authenticated futures trading routes,
never runs automatically in the existing production project, and has
no client release interface. The user remains in control of any
future opt-in research deployment. A functioning sampler does not imply
positive economic expectancy.
