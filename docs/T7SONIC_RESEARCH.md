# T7Sonic — research foundation and controlled development contract

**Status:** DRAFT ONLY. Not a production strategy. No trading signals, portfolio orders, execution quotes, stop losses, risk budgets or exchange activity are authorized. Created on its own `codex/t7sonic-research` branch from `main` while the existing V4 engine remains stopped by operator action on the VPS.

## Legacy-model retirement and independent runtime boundary

**Implemented and enforced in CI** on the T7Sonic research branch. The
separate standalone image at `services/t7sonic/Dockerfile.research` includes
**only** allowlisted `t7sonic_*.py` research modules and the T7Sonic research
contract; the image does not install the `mv_strategy` package and has no
V4 worker, V5/V6HBR decision/predictive engine, Telegram, API, database,
exchange order client or application Docker Compose service.

The source-level `t7sonic_isolation.py` gate checks all import graphs,
rejects legacy and third-party application imports, prohibits dynamic module
loading patterns, verifies the dedicated Dockerfile copies only those
T7Sonic resources, and verifies that PR paths do not include production
workers or the common strategy package. The GitHub workflow additionally
builds a real nonroot isolated container and confirms that none of the
old models, workers or DB ORM dependencies exist inside the image. It
runs with no network, a read-only root, dropped capabilities and no elevated
user. The source gate is a regression detector; only the OS isolation
restricts executable environment access.

**The old code remains in the MAIN repository for now** because it shares
the production application and stores historical audit-relevant behavior.
Physically deleting or overwriting production worker files from a research
branch could cause a dangerous future merge/cutover; it is unnecessary to
prevent T7Sonic model conflicts. The currently suspended V4 runtime was
paused separately by the VPS operator; no PR code restarts or changes its
container. The real T7Sonic production migration will separately retire
or replace live entry points after an explicitly authorized cutover and
independent test gates, preserving historical research and signal records.

T7Sonic can read old **archive formats**, not legacy prediction models.
The `48a460...` source-spec SHA256 in `t7sonic_history.py` identifies
the frozen checksum-pinned *historical OHLCV archive lineage*, not an
import of V5 or V6HBR trading strategy code. This compatibility allows
real-data replay without altering source history.

No old model is merged, reused, executed or included in the T7Sonic-only
research artifact. No claim is made that these tests validate predictive
accuracy, actual signal count or profitability.

## Problem to solve

V4 was primarily a 1H/4H EMA/ATR rule selector with BTC time-of-day and directional-risk vetoes. Previous isolated V4/V6HBR exploratory data for six coins, April–May 2026, showed 143/352 = **40.62%** rule-qualified candidates directionally correct at 60 minutes (10 bps mark hurdle, not filled trade net returns). A later seven-feature logistic fit exhibited May AUROC approximately **0.512**, poor score separation, and a worse Brier score than a late-April constant-probability model. These are not representative live performance metrics and should not be treated as verified exchange fills.

T7Sonic must recognize multiple market conditions, generate *additional distinct causal opportunity hypotheses*, and later independently discriminate tradable from unprofitable candidates. It must be allowed to watch both directions and multiple expert ideas without forcing a new signal or treating all market motion as tradable. We cannot promise 80% direction accuracy or guaranteed daily signal frequency. Output volume and quality must both be measured.

## Planned architecture

1. **Market perception:** closed 1m, 5m, 15m, 1h, 4h observations, audited upstream archive publisher/source, exact end times and sequence coverage. Future additions: verified trades, depth snapshot/delta sequencing, funding, open interest and spreads, only with proof of historical as-of availability.
2. **Market environment:** descriptive regime recognition across frames, with uncertainty and competing possible environments; do not let one uncertain higher timeframe veto every intraday case.
3. **Experts:** trend continuation; range reversion; completed-bar breakout; failed-breakout reversal; OHLCV participation proxy (not true buyer/seller aggressor order flow); volatility transitions.
4. **Arbitration and calibration:** separate long/short/abstain outcome models for each expert or a mixture-of-experts selector. Probabilities must be trained, calibrated and evaluated, never assigned from fixed heuristic scores.
5. **Risk/execution:** a completely separate trade feasibility layer incorporating quotes, spread, realistic book depth, funding, slippage, order latency, stop/target-first sequence, leverage, correlated exposure, drawdown and maximum loss budget.
6. **Production integration:** requires its own operator-approved design, end-to-end tests, rehearsal, rollback and release PR. This research PR may not publish signals or restart V4.

## What is implemented in PR #14 Phase 1

- `packages/contracts/t7sonic-research-v1.json` pins research-only/no-execution scope and lists candidate timeframes, expert families, research targets and operator-signoff boundaries.
- `t7sonic_perception.py` validates five contiguous OHLCV streams and as-of publication timing. Rejects missing/duplicate/stale/incomplete/future bars and malformed prices/volumes. Computes deterministic EMA8/EMA21 trend separation, ATR14 normalized momentum, completed-breakout/rejection, range position, recent relative volume and VWAP from finished candles. Reports source-input SHA256. Source data may not be assumed authentic until external archive verification is added.
- `t7sonic_experts.py` derives a descriptive market state and produces research WATCH hypotheses from six transparent, independent expert families. A shared report records contradictory directions rather than concealing disagreement. Every hypothesis declares no calibrated probability, entry price, stop, take profit or executable order.
- `t7sonic_cli.py` reads a bounded JSON snapshot without networking or writing to any service. It deliberately has no direct MV production import or integration. Its market-breadth summary states observed/30 and refuses to represent a six-coin subset as the market's whole breadth.
- `test_t7sonic_perception.py` tests timeframe availability, OHLCV geometry, no-future/stale/gap handling, market matching, expert discovery, schema restrictions and zero executable signals.
- Isolated GitHub workflow runs synthetic tests with no downloaded archive, historical ground truth, VPS or live exchange services.

**Be precise:** Phase 1 tests software integrity, not trading effectiveness. It is possible for six heuristic experts to discover more WATCH cases without identifying any profitable opportunity. The system has no trained decision or risk engine yet.

## Phase 2a delivered: pinned calendar-month history adapter

T7Sonic now contains a self-contained, offline-only reader for the
existing **V5 pinned monthly research archive format**. This is deliberately
not a dependency on the V6HBR strategy branch; no V6HBR rule or production
code is imported.

- Module: `services/api/app/research/t7sonic_history.py`.
- CLI: `services/api/app/research/t7sonic_history_cli.py`.
- Scope is currently **an explicit 1–6-symbol smoke subset** in **April–May
  2026 development only**, with decisions at **completed 5-minute UTC
  boundaries**. Validation and holdout months are forbidden.
- Reads already-acquired source ZIPs plus matching `.zip.manifest.json`
  sidecars at `root/archives/<symbol>/<1m|15m|1h|4h>/...`, pinning the
  original frozen research specification SHA256
  `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64`.
- Rechecks every required **complete calendar month**: the sidecar's source
  identity, publisher URL claim, spec identity, ZIP SHA256, single CSV member,
  12-column format, expected monthly count, exact contiguous UTC timestamps,
  exact exchange-format close time and OHLCV geometry. A locally self-consistent
  manifest is **not independent publisher authentication**; operator must
  verify initial acquisition against Binance's published `.CHECKSUM`.
- Builds **64 completed bars** per model-facing timeframe. The 5m bars are
  aggregated exclusively from the most recent **320 complete, pinned 1m
  candles**. Never fills, interpolates or approximates missing 1m history
  from an hourly/15m price.
- Cross-checks all native 15m/1h/4h candles fully covered by the minute
  window against exact minute-derived OHLCV. Inconsistencies **fail closed**.
  Publisher revisions and native-versus-minute historical discrepancies must
  be explicitly reviewed in versioned evidence; never silently corrected.
- The run output reports SHA256 of each ZIP and sidecar used, calendar row
  counts, source months, full-universe coverage limitations, and zero
  actionable signals. It is a **one-boundary WATCH snapshot**, not a
  chronological performance test or production-ready signal generator.
- The `plan` action reads file/sidecar *presence* only and reports missing
  source months; it does not download or verify any archives.
- **Important:** previous V6HBR six-market studies collected 15m/1h/4h
  Jan–May, **not necessarily the 1m months required here**. A missing 1m
  archive causes the T7Sonic runner to stop. Do not use a synthetic fallback.

CLI signatures:

```bash
python -m app.research.t7sonic_history_cli plan \
  --root /research --symbols BTCUSDT \
  --at 2026-04-20T12:00:00Z

python -m app.research.t7sonic_history_cli run \
  --root /research --symbols BTCUSDT \
  --at 2026-04-20T12:00:00Z
```

These are **module signatures only**, not instructions to run a checkout in
production. Use only an operator-approved network-disabled, nonmutating Docker
research container after staging the exact T7Sonic commit separately from
the V6HBR service and existing production release.

**Regression proof:** `test_t7sonic_history.py` creates complete synthetic
April ZIPs, validates full-month read and 5m rolling, then tests tampered
ZIPs, wrong manifest spec SHA, missing final source rows, native/1m OHLCV
mismatches, missing 1m, missing month, symlinks, holdout access prevention
and duplicate markets. These are repository-contained synthetic fixtures,
not market-data performance results.

### Next implementation gate

Preflight real VPS archive *availability* first, then independently
validate an authorized, small research-only 1m acquisition before a single
BTC historical development snapshot. Only after proving deterministic
historical source equivalence should we implement bounded chronological
candidate streaming and independently labeled outcomes. Risk and
calibration modeling remain unimplemented.

## Phase 2B delivered: one-month acquisition and one-day opportunity replay

**Status: code + synthetic integrity testing only. Real market-data results
require the operator's isolated VPS archive. V4 must stay suspended.**

### Source-only acquisition tool

`services/t7sonic/archive_fetch.py` is a separate standard-library-only
operator utility. It is deliberately **NOT copied into the T7Sonic model
container**, nor is it callable by the trading expert pipeline.

- `plan` lists one required frozen 2026 Jan–May USD-M futures 1m archive.
  No files are downloaded or replaced.
- `fetch --confirm-single-fetch` explicitly downloads **one** full
  `<SYMBOL>-1m-<YYYY-MM>.zip` and its publisher `.CHECKSUM`, checks
  downloaded bytes against the published SHA256, validates all **calendar
  minute** rows, close times and OHLCV, enforces a 48 MiB compressed ceiling
  and a 2 GiB free-space reserve, and writes a matching pinned V5-format
  sidecar. A second fetch cannot replace an existing ZIP; exclusive filesystem
  links prevent the last-write-wins race. If interrupted between two links
  a partial pair fails closed and must be repaired manually.
- `verify` rehashes a previously acquired local ZIP and validates its
  complete candle geometry and sidecar without network access.
- Only explicitly selected frozen markets and Jan–May 2026 months are
  accepted. The research root must be an existing real absolute `/var/tmp`
  or `/tmp` location. **No automated bulk fetching or trading workers**.
- The checksum URL is publisher-controlled: if it changes later, the pinned
  archived version must be reviewed rather than silently overwritten.
  Actual source correctness requires this publisher-authenticated acquisition,
  not merely a self-consistent local sidecar.

### Offline opportunity replay

`t7sonic_replay.py` and `t7sonic_replay_cli.py` run in the dedicated
legacy-free image, without network access or any write permissions.

- `plan` inventories required 1m/15m/1h/4h source-month ZIP/manifest
  pairs for a **single UTC day**, not checksums; missing months are listed.
- `run` first verifies the needed complete pinned month archives exactly
  once. Each 5m boundary selects only fully closed price bars, with 1m/15m/
  1h/4h inputs synchronized to their most recent completed candle.
- The adapter now keeps **480 prior verified 1m bars** in internal
  reconciliation memory, so a full most recently completed 4h candle can
  be independently checked even late in a 4h interval; only the final 320
  1m bars create 64 derived 5m bars, and the model itself sees only 64
  completed 1m bars.
- Emits descriptive WATCH hypotheses from six expert families. Reports
  repeated bar-by-bar observations separately from **new activation
  episodes** (an expert+symbol+direction reappearing after a gap). Reports
  both directions and opposing hypotheses without declaring them trades.
- This pilot requires an explicit 1–6-market subset and a single day from
  **2026-04-01 through 2026-05-30**, with a bounded 1–288 completed 5m
  decision count. June–September validation/holdout is not accessed.
- The opportunity stream includes deterministic SHA256, source-month hashes,
  expert/direction/market counts, output limitations, and permanent
  `actionable_signals=0` / `outcomes_labeled=false`.
- A WATCH activation episode does **not** establish a separate executable
  trade, high-confidence entry, favorable outcome, or profits. These
  cannot be measured before the separate cost/label/replay work.

Command signatures (do not run from a production checkout):

```bash
# Download-free acquisition inventory:
python services/t7sonic/archive_fetch.py plan \
  --root /var/tmp/mv-v5-history-archives \
  --symbol BTCUSDT --month 2026-04

# Source pair presence for a single pilot day:
python -m app.research.t7sonic_replay_cli plan \
  --root /research --symbols BTCUSDT \
  --day 2026-04-20 --max-boundaries 12
```

After CI and the VPS preflight evidence, a **separate operator-reviewed
acquisition command** can acquire exactly the missing 1m month. No generic
permission to activate V4 or deploy any research code is implied.

## Phase 2B first full-day BTC replay — operator evidence

The 2026-10-11 user-supplied VPS output authenticates all BTCUSDT
April 2026 1m/15m/1h/4h data against Binance publisher SHA256 and the
frozen sidecars. The isolated T7Sonic runtime at
`666a0da2de36517e17c2270b5562b31c2fcdca2d` completed its first
full-day **288 completed five-minute boundaries** for **2026-04-20 UTC**.

Observed research-only measurements:
- 288 decisions, 62 boundaries with any WATCH hypothesis
- 92 WATCH observations (50 LONG, 42 SHORT)
- 80 expert-key new activations: breakout 16, failed-breakout
  reversal 14, participation 14, range reversion 2, trend
  continuation 5, volatility transition 29
- 0 contradictory-direction symbol-boundaries; 0 actionable signals
- `candidate_stream_sha256=16136d13ff78180009cb408b696d1727a566f9bc279ca858cd150a60065cb5c6`
- Full report from VPS:
  `/var/tmp/t7sonic-btc-full-day-CCDRyZbb.json`;
  full report SHA256:
  `eb94eb41d734698024255305a6fed553c0cd5d1ee1e69e79dbca216a5f56a39b`
- V4 running=false, restart=no at replay completion

**These are NOT 80 independent trades.** Multiple experts can flag
the same symbol and direction on one boundary; separate activations can
be clustered and highly correlated. This is a one-day development
opportunity *coverage* experiment; no model training, valid accuracy,
risk model, order fills, fees, slippage, funding, drawdown or trading
profitability was measured. The broader initial strategy goal of three
actionable signals daily is not established by 80 WATCH activations.

## Phase 2C — frozen decisions and retrospective directional mark labels

A separate, non-publishing analytical module computes:

- Distinct **directional WATCH episodes**: a same-symbol + same-side
  observation persisting across consecutive 5m decisions; multiple
  expert triggers are grouped and attributed, not double-counted.
  Episodes separated by a gap are still potentially correlated and are
  **not** independent trading opportunities.
- Precommitted **15/30/60/120 minute mark-proxy labels**: entry proxy
  uses the first future 1m candle open after decision time; signed
  horizon mark movement greater than **+10 basis points** is
  classified favorable, less than **-10 basis points** adverse,
  all remaining observations neutral (neutral is not counted correct).
  Intrahorizon MFE and MAE are measured but their order is not
  determined from within a 1m candle.
- The existing pre-outcome SHA256 candidate stream is finalized **before**
  any future 1m label source is read. Complete source-month sidecars,
  ZIP SHA256, candle integrity, and *all* required future 1m minutes
  are mandatory. Missing outcome data and missing next-month archives
  fail closed; no optimistic censoring.
- `t7sonic_outcomes.py` and `t7sonic_outcomes_cli.py` are included
  only within the isolated research image (still no legacy models).
  Details are returned only when `--include-episode-records` is
  specified; by default the output is a bounded aggregate plus
  sample and separate source/decision/label SHA256 evidence.

**IMPORTANT:** Candle *open* is not a guaranteed execution price,
and Binance kline OHLCV does not provide executable bid/ask depth.
These are descriptive historical directional labels **not** net
after-cost trade returns, strategy accuracy estimates, stop/target-first
outcomes, or evidence of profitable signals. Historical April/May
is development data, not a fresh sealed holdout. Forward labels must
never become input features.

The first operator-controlled real-data outcome run must use a
separate explicitly pinned T7Sonic research Git checkout and rebuilt
nonroot image, mounting only a byte-identical certified research
archive copy read-only, with V4 suspension checked before and after.
No source in production Compose may be mutated.

## Phase 2C operator result and Phase 2D expert attribution

On 2026-10-11, the operator ran the standalone SHA
`ee0898fd18d47348a1774eb0aebc484919e5d5e3` on certified BTCUSDT
1m/15m/1h/4h **2026-04-20** market data at all 288 completed 5m
boundaries. The pre-label candidate digest
`16136d13ff78180009cb408b696d1727a566f9bc279ca858cd150a60065cb5c6`
**MATCHED** the prior pilot.

- Raw expert WATCH observations: 92.
- Expert new activations: 80.
- Grouped same-direction contiguous WATCH episodes: **50** (24 LONG,
  26 SHORT), with 25 symbol/side boundaries showing multiple expert votes.
  This is **not** 50 independent trades; horizon overlap remains.
- 15m (+10bps favorable / -10bps adverse / neutral): **16 / 12 / 22**.
- 30m: **22 / 15 / 13**.
- **Primary 60m:** **18 / 19 / 13**, i.e. only **36%** favorable
  when neutrals are not counted as correct.
- 120m: **22 / 26 / 2**.
- Post-label digest:
  `e1316002aa257dab698456728df7958d952ddd2c71f4cf2d3205b198655196d8`.
- VPS report
  `/var/tmp/t7sonic-outcomes-qbvS8uMC.json`,
  SHA256
  `3bbf59f19ffe0954626bccd76056eef48d58b565e716acd4fc5dd44e1e33f078`.
- V4 remained off and restart disabled; no actual signals or orders.

**Interpretation:** The current six early heuristic WATCH experts discover
activity, but the primary 60-minute price proxy is *not* a convincing
directional filter. These are one-day, overlapping, uncosted historical
label counts and NOT reliable strategy prediction accuracy, trading
performance or statistical significance. Do not raise signal volume
quotas, tune a model to this single day or enable live T7Sonic trading.

A separate **Phase 2D attribution diagnostic** adds
`t7sonic_diagnostics.py` and `t7sonic_diagnostics_cli.py` to the
research-only image:

- Source integrity and the entire causal WATCH replay run *first*.
- The user must pin **both** the pre-outcome decision digest and
  the post-outcome label digest. Any mismatch causes a hard error.
- Counts are reported per expert at the moment an episode first appears,
  per expert appearing later, LONG/SHORT side, one-vs-multiple experts
  at onset, and two descriptive UTC half-day windows, at all four horizons.
- Every cohort reports favorable, adverse, neutral, signed mark movement
  and MFE/MAE means. All nonoverlapping grouping partitions are verified
  to reconcile to the 50-episode totals.
- An episode may be attributed to multiple experts: summed expert
  cohort counts do *not* represent unique observations or market trades.
- Results must remain **descriptive**. The first useful conclusion is
  which expert families deserve testing on **multiple full market days
  and coins**, with explicit time-overlap and date-grouped uncertainty.
  No post hoc selection using April 20 may be presented as a validated
  improvement.

No change to V4/production, no trained model, no online order execution,
no Telegram signals, no backtest fill pricing and no new trading strategy.

## Historical data requirement

An actual prospective-grade model requires a much larger dataset than six markets and two months. Build a versioned 30-market source lineage with 1m/5m/15m/1h/4h as-of snapshots, plus complete publisher sidecars and no invented gaps. Assess existing historical data availability per feed before committing to a feature; order-book/open-interest archives cannot be backfilled using future snapshots. Synthetic fixtures are exclusively for correctness tests, never for performance claims.

The older April–May directional outcomes have already been examined many times. Any analyses of them are *development only*. Preserve predeclared chronological training, purged validation, cross-market/date-grouped uncertainty and an untouched final test period. Once a holdout is used to choose features it is no longer a holdout.

## Opportunity count vs actual trading signals

Record these separately by coin, day, regime, specialist, direction and session:

- Potential raw setups and completed-candle WATCH hypotheses.
- Risk-feasible trades whose entry quote and stop/target can be executed with cost assumptions.
- Scored, calibrated model-selected actionable signals.
- Later correct, wrong, neutral, canceled, censored, executed and profitable outcomes.
- Additional winning opportunities missed by rejection and correlated simultaneous losses.

**Initial aspirational product volume**: a median of at least three actionable signals per active day across 30 markets, once fully validated, without mandatory forced trades and without weakening hard safety limits. This is a product target, NOT a declared result.

**Aspirational correctness**: 80% of all observed predictions including neutral as not-correct at the predeclared 60m hurdle, with credible uncertainty, adequate independent days/markets, and positive after-cost portfolio expectation. Use an observed 60m neutral category; don't silently discard it or compare hit rates only on selected profitable trades.

## Remaining work and acceptance gates

### Phase 2: real as-of data integration

Use a source-audited archive adapter for each timeframe. Construct synchronized multi-symbol snapshots in a **network-disabled research runner**, with timestamp-boundary integrity, checkpoints and reproducible source hashes. Add source availability audits for trades/depth/funding/OI. Do not touch production collector until the separate production architecture is reviewed.

### Phase 3: breadth and genuine opportunity labels

Replay all opportunities, *not merely V4-qualified trades*, across eligible timestamps and strategy families. Create immutable candidate identities and complete first-touch stop/target or after-cost return outcomes, with 1m tie handling and never any future feature. Evaluate hypothetical signal counts/days and joint market-state correlations. Compare against VWAP/reversion/breakout and momentum baselines.

### Phase 4: model ranking and calibration

Start with simple regularized and gradient-boosted tree models; investigate sequence models only after baselines. Consider separate policy heads or regime-conditioned mixtures. Predict success, wrong-way excursion, target-first vs stop-first and post-cost expected R. Fit and calibrate strictly before the evaluation period. Compare to prevalence-only, always-long/short and random ranking benchmarks.

### Phase 5: independent cross-sectional and walk-forward tests

Freeze features and hyperparameters before independent validation. Ensure day/symbol/group-corrected uncertainty, exposure caps, forecast calibration, market-regime slices, drawdown and realistic fill simulation. Do not repeatedly tune on the final sealed holdout.

### Phase 6: explicit production release

Operator reviews final results, release controls, distinct DB/worker permissions, dry-run rollback and V4 suspension. Only then consider an isolated **new** production PR. Never merge or deploy this research branch simply because its software tests pass.

## Hard boundaries

- No automatic trades or fake guaranteed outcomes.
- No forced signals to satisfy a product daily quota.
- No large LLM acting as the unverified numeric price oracle.
- No relabeling past losers as wins via selective censoring.
- No cross-market future leaks, hindsight order-book reconstructions or synthetic missing price data.
- No restart of the stopped MV V4 workers, telegram, AI or daily report.

## Phase 2E BTC 14-day development observations (operator-provided evidence)

An isolated, nonpublishing T7Sonic image at pinned research revision
`0f327593c79eb4783c0008dbb623ddd895be305b` analyzed BTCUSDT
UTC 2026-04-12 through 2026-04-25, 288 completed five-minute boundaries
per day, with pinned historical source archives. The report directory is
`/var/tmp/t7sonic-phase2e-L7gWHdIG`. The original SHA256SUMS file is
externally pinned by operator-reported SHA256
`50654b21b6241f57fba149329ae4315ec988ed5abb667b3918b4efe4b365ef8d`.
Apr 20 recreated original decision and label digests without changes.

The 14-day 60-minute directional price-proxy results:
- 854 grouped directional WATCH episodes, not independent trades.
- 297 favorable, 321 adverse, 236 neutral (10bps strict threshold);
  favorable rate 34.78%, 297/618=48.06% of nonneutral outcomes.
- Only 3 days had more favorable than adverse episodes; one was tied.
- Expert-at-onset counts overlap across coactivations:
  failed-breakout reversal 95/224 favorable, 68 adverse (14 days);
  range reversion 18/32 favorable, 9 adverse (7 days);
  breakout 58/196 favorable, 87 adverse (14 days);
  participation 63/220 favorable, 85 adverse (14 days);
  trend continuation 48/154 favorable, 66 adverse (11 days);
  volatility transition 123/369 favorable, 146 adverse (14 days).
- Multiple experts at onset: 80/256 favorable; single expert:
  217/598 favorable. No consensus improvement demonstrated.
- Long directional episodes 171/468 favorable; short 126/386.
- No exchange fills or after-cost returns; no statistical claims of
  independence, generalization or deployable directional skill.

These 14 days were already inspected in development. Do not tune experts,
pick a winning specialist, count these as profitable trades, or present
them as held-out evidence. Production V4 stayed suspended, restart=no.

## Phase 2F — frozen evidence audit and matched-direction baselines

The separate `t7sonic_multiday.py` research-only CLI consumes the
already-saved 14 report files and summary, not the market archive itself.
It verifies every report byte against the `SHA256SUMS` ledger and pins
that ledger to the externally preserved digest above. It recomputes
individual episode label-stream SHA256 and horizon classifications,
reconciles day totals, and requires the Apr 20 original decision and
label digests to match. For all 854 expert-selected episode onsets,
it constructs **matched** always-long and always-short directional
price-proxy baselines using the *same future mark moves*. These are
NOT unconditional always-long or always-short trading strategies,
executions, or zero-cost trading models.

The CLI reports per-day, per-expert-at-onset, consensus and direction
cohorts and a leave-one-day-out favorable-rate sensitivity range
(**not** a confidence interval). It DOES NOT change any WATCH decisions,
fit a trading model, choose thresholds, or enable production.

Run the pin-verified reader only in the isolated, no-network research
image with the evidence directory mounted read-only; follow the separate
operator-run invocation. Its development-only output is evidence for
planning multi-symbol replication, cost modeling and independent
validation—not authorization to publish or trade.

## Phase 2G — per-expert matched-baseline diagnosis, certified VPS evidence

The operator ran exactly pinned research commit
`602dccb6d51a319efa1088e31a41bab52ac16d20` in the isolated image
against the immutable Apr 12–25 BTCUSDT 14-day ledger documented above.
Frozen SHA-256 evidence verified and V4 remained stopped with restart=no.

Operator-reported read-only diagnostic:
- Report `/var/tmp/t7sonic-phase2g-report-28okReyr.json`
- Report SHA256 `c0fecab6557e647671e77ed98e1a7502bab18b1b6c140434a2760a69e15beafb`
- Actual directional WATCH favorable 297/854 (34.78%).
- Matched always-long on the same 854 expert-selected onsets: 313/854
  (36.65%); matched always-short: 305/854 (35.71%).
- Failed-breakout reversal onset cohort: 95/224 favorable (42.41%);
  matched-long 82/224 (36.61%); matched-short 81/224 (36.16%);
  favorable episode differences +13 and +14 respectively.
  Across its 14 active BTC dates: >long 10, <long 4, ties 0;
  >short 8, <short 4, ties 2.
- Breakout 58/196 favorable vs matched-long 81/196, short 64/196.
- Participation 63/220 vs long 80/220, short 68/220.
- Range reversion 18/32 vs long 18/32, short 9/32; just 7 active days.
- Trend continuation 48/154 vs long 51/154, short 63/154.
- Volatility transition 123/369 vs long 135/369, short 134/369.

The above are favorable outcome counts from a **fixed 60-minute 10bps
price-proxy test**, not trade profits, risk-adjusted returns, fill
simulations or robust out-of-sample model scores. Expert cohorts overlap.
The 14 BTC days and all expert comparisons have now been repeatedly
inspected: choosing an expert because it looked better here is
**post-selection**, not evidence of independent generalization.
No strategy/weight/threshold changes are authorized by Phase 2G.

### Phase 2H — safe cross-market source readiness before repeating research

Next test predeclared BTC-adjacent heterogeneous markets
`ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT` on identical Apr 12–25
UTC development dates, with every symbol's independent source lineage.
Start with **presence-only**, network-free inventory of 2026-04
1m/15m/1h/4h ZIP and matching .manifest.json pairs; do not infer that
a present pair is authentic. Full-month publisher-checksum verification
and timeframe reconciliation are mandatory before outcome replay.
Any missing 1m archive requires a separate operator-reviewed bounded
acquisition, with checksum validation and no overwrite.

For every admitted symbol/day, run exactly the same unmodified
T7Sonic WATCH hypothesis and 15/30/60/120-minute price-proxy labels,
deduplicate coactivated experts, and compare specialist directions with
matched always-long and always-short baselines **on the same specialist
onsets**. Preserve complete original output digest chains. No
automatic expert selection from these already-inspected development dates.

Before independent validation, explicitly freeze the candidate rule
hypotheses, universe, thresholds, training/calibration split and
quality gates. Evaluation must assess day/market-grouped uncertainty,
price path/excursion, liquidity, fees, slippage, stop/target-first
ordering and realistic quote execution. None of this research
authorizes production deployment or Telegram publishing.

## Phase 2H — six-market April archive source certification

Operator VPS evidence reported after executing the checksum-authenticated
research-only source-preparation workflow at pinned code SHA
`384d08906a8cf9b0ed3e471ee126af680b90fc71`.

The April 2026 USD-M perpetual archive has the exact predeclared six
development markets BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT,
BNBUSDT; 1m/15m/1h/4h for each. Nineteen archive/manifest pairs were
copied byte-for-byte from `/var/tmp/mv-v5-history-archives`, five new
1m archives (ETH/SOL/XRP/DOGE/BNB) were explicitly downloaded with
full-month 43,200-row geometry and Binance published .CHECKSUM matches.
All 24 archive ZIPs independently matched the publisher .CHECKSUM
at audit time. Six-market research-only historical snapshot as of
2026-04-20 12:00 UTC completed strict 1m-vs-15m/1h/4h OHLCV
reconciliation for every symbol.

Evidence locations and operator-reported SHA256:
- Source archive root `/var/tmp/t7sonic-6market-MbjsaBD3`
- Immutable file SHA256SUMS ledger SHA256
  `d185fe400948978b037751d4ee91bb4d288fa2bcb62a89b47c6b57fe41c48ab1`
- Historical nontrading pilot report
  `/var/tmp/t7sonic-6market-pilot-DzEPkFFF.json`,
  SHA256 `43bbf1dc389cfcec29083e6baa7fd71c656c28031ae50abb6d015605eb1e3aa7`
- Production legacy engine remained stopped with restart=no;
  no orders or Telegram messages were emitted.

These are operator-provided local VPS run observations, not a claim that
GitHub CI independently fetched market archives. Publisher authentication
confirms archive bytes matched publicly distributed checksums at check
time, not that these archives describe executable bid/ask fills.

### Phase 2I — one-day six-market outcome integrity pilot

At the Apr 20 2026 UTC development date, run original unmodified
`t7sonic_outcomes_cli` independently for each of the six symbols, with
288 boundaries and full episode records, in a read-only, networkless
research Docker image. This single-symbol-at-a-time design preserves
the original BTC digest, allows per-market expert attribution,
and prevents cross-market breadth effects from changing the
originally validated one-market baseline.

The original BTC decision SHA256 must remain
`16136d13ff78180009cb408b696d1727a566f9bc279ca858cd150a60065cb5c6`;
the label SHA256 must remain
`e1316002aa257dab698456728df7958d952ddd2c71f4cf2d3205b198655196d8`.
Any discrepancy fails closed. Additional per-symbol output hashes must
be preserved without changing the expert definitions or retrospective
label threshold. Never interpret the day as independent holdout
evidence or strategy certification.

Only after this pilot passes should the April 12–25 replication across
the five new symbols be run; retain BTC original sealed report ledger.
All results remain descriptive inspected development research.

## Phase 2I — six independent Apr 20 market pilot, certified on VPS

Operator reported successful six-market isolated retrospective WATCH replays
on the authenticated April 2026 source collection, pinned engine revision
`384d08906a8cf9b0ed3e471ee126af680b90fc71`. Every symbol was
replayed independently (288 five-minute UTC boundaries) without a live
market-breadth arbitration change. All six individual episode-label SHA256
streams verified; BTC decision and label streams reproduced original
frozen SHA256 values exactly, and its 50 episodes matched 18 favorable,
19 adverse, 13 neutral at the 60-minute strict 10bps proxy.

Operator evidence:
- Directory: `/var/tmp/t7sonic-phase2i-rdy4r1OV`
- Evidence `SHA256SUMS` SHA256:
  `bf221b117095daec1540ec1f42e90bfb4aecaaaede32aa06fb6844efe5051ef5`
- BTC: 50 episodes, 18 favorable, 19 adverse, 13 neutral;
  matched-long 22 favorable and matched-short 15.
- ETH: 61 episodes, 23 favorable, 29 adverse, 9 neutral;
  matched-long 28 favorable and matched-short 24.
- SOL: 53 episodes, 19 favorable, 29 adverse, 5 neutral;
  matched-long 30 favorable and matched-short 18.
- XRP: 52 episodes, 21 favorable, 24 adverse, 7 neutral;
  matched-long 30 favorable and matched-short 15.
- DOGE: 51 episodes, 16 favorable, 26 adverse, 9 neutral;
  matched-long 26 favorable and matched-short 16.
- BNB: 47 episodes, 17 favorable, 16 adverse, 14 neutral;
  matched-long 20 favorable and matched-short 13.
- Total 314 episodes, 114 favorable/143 adverse/57 neutral;
  same-onset matched-long 156 favorable, matched-short 101.
- Failed-breakout-reversal expert-at-onset across six symbols:
  82 cohort observations, 39 favorable/21 adverse/22 neutral;
  expert coactivation and common-day correlation remain.
- V4 production engine remained stopped and restart=no;
  no trade orders or Telegram messages.

This one day and the BTC 14-day development sample have already been
inspected. These are NOT six independent live market trials, an
unseen holdout, a win-rate estimate or trading performance.

### Phase 2J — five additional markets, Apr 12–25 developmental replication

Use the same pinned engine SHA and immutable source ZIP/sidecar
collection from Phase 2H. Re-run the *same one-symbol-at-a-time*
`t7sonic_outcomes_cli` across 14 April UTC dates for each of
ETH/SOL/XRP/DOGE/BNB (70 runs) without changing any rule or labels.
For the identical April 20 market/symbol, require the complete JSON
bytes to match the 2I anchor. Preserve the original BTC 14-day files
byte-for-byte, check source, Phase 2I, and BTC archive ledger digests,
and publish newly hashed reporting files to an isolated research directory.

Descriptive reporting should show each market separately, matched
long/short favorable rates on the exact same episode onsets, individual
expert-at-onset counts and direction-versus-matched-baseline deltas,
including sign consistency across market days. More favorable episodes
on a market-day do not imply an independent or cost-adjusted edge:
the crypto markets and overlapping future horizons are correlated.

Do not tune the six experts from the same 14 inspected development dates,
promote the historically best expert, or enable signal publishing/production
in response to this research. A predeclared later window with strict
chronological separation is essential before validating a proposed
new candidate after realistic execution/friction modeling.

## Phase 2J — six-market 14-day development replication (VPS certified)

The operator successfully completed exactly 70 new single-market/day
historical replays for ETH/SOL/XRP/DOGE/BNB using unchanged source revision
`384d08906a8cf9b0ed3e471ee126af680b90fc71`.
The original 14 BTC reports were copied byte-for-byte and verified.
Every new market's April 20 report reproduced the prior 2I pilot bytewise.
All 84 daily label streams, horizon rollups and research-only scope passed.
No orders, Telegram messages or production execution were authorized;
V4 engine remained stopped and restart=no.

Pinned evidence reported by operator:
- Directory `/var/tmp/t7sonic-phase2j-Cq0QNHNE`
- `SHA256SUMS` SHA256
  `89a520175f442e674799140c0c29bebc0135f945236b19c63374d1cd821e5a07`
- 84 full per-symbol/day reports, one descriptive summary and SHA256SUMS.

Primary 60m strict +10bps favorable outcome counts among 4,991
**directional WATCH episodes, not trades**: favorable 1,787 (35.80%);
adverse 1,994; neutral 1,210. Same-onset always-LONG
1,930/4,991 (38.67%), always-SHORT 1,851/4,991 (37.09%):
T7Sonic directions underperformed both at aggregate level.
BTC 297/854 favorable vs long 313 and short 305;
ETH 291/807 vs long 315 and short 317;
SOL 295/823 vs long 322 and short 324;
XRP 305/857 vs long 337 and short 315;
DOGE 308/794 vs long 308 and short 325;
BNB 291/856 vs long 335 and short 265.

The investigated failed-breakout reversal expert at episode onset:
539/1,279 favorable (42.14%), matched LONG 507/1,279
(39.64%; favorable episode delta +32, +2.50 percentage points),
matched SHORT 445/1,279 (34.79%; delta +94).
Per-market favorable delta vs LONG/SHORT respectively:
BTC +13/+14, ETH +10/+12, SOL +6/+11, XRP +3/+26,
DOGE +14/+21, BNB -14/+10. All-market expert cohorts overlap
other experts; of 84 market-days only 21 had a positive favorable
delta versus BOTH constant-direction baselines for the
failed-breakout reversal expert. Co-movement within and across days,
overlapping forward horizons, market selection and post hoc expert
identification preclude treating 1,279 episodes as independent trials.

Other expert-at-onset delta vs matched LONG/SHORT:
breakout -72/-64 (1,036 episodes); participation -69/-67
(1,242); range reversion -3/+17 (202); trend continuation
-56/-64 (1,062); volatility transition -63/-76 (2,111).
Those cohorts overlap; they do not sum to independent episode counts.

These are already-inspected development observations. No inference
that a specialist is profitable, deployed, or statistically verified
is permissible. Do not revise any expert rules or selection
from the above without a separately frozen development plan
and genuinely new chronological validation.

### Phase 2K — inspect temporal/horizon robustness without tuning

A separate read-only, network-disabled diagnostic of the preserved
84 Phase 2J reports should verify the externally pinned ledger and
every record's label-stream SHA256, including original BTC April 20
causal and label digests. The predeclared *descriptive-only* checks:
failed-reversal paired favorable episode deltas vs same-onset LONG
and SHORT at 15/30/60/120min; per-UTC-calendar-day blocks pooling all
six coins jointly; leave-one-calendar-day-out and leave-one-market-out
rate sensitivity. Same day across correlated cryptocurrencies is
ONE correlated calendar block, not six independent replications.
Ranges from excluding one day/market are **not confidence intervals**
and cannot establish statistical significance or a trading edge.

No revised thresholds, model training, simulated exchange execution,
Telegram publication, use of June+ held-out archives, or production
changes are authorized. The expected outcome is a diagnostic and
a go/no-go research recommendation, not a new trade engine.

## Phase 2K — completed retrospective stability audit (operator-certified)

The operator ran a pinned, nonprivileged, networkless Phase 2K analysis
of the 84 previously inspected market/day T7Sonic reports. The original
Phase 2J 85-file ledger was verified before the read-only analysis.
No production, Telegram, order or model changes were performed.

Evidence:
- Readable report: `/var/tmp/t7sonic-phase2k-result-agSFl6Et.txt`
  SHA256 `335cbb2f89978d9b1135111430e0e00371683b8ae83ec6ee6d0c3ee04818929b`
- Machine-readable report:
  `/var/tmp/t7sonic-phase2k-result-agSFl6Et.json`
  SHA256 `17c1af36ded16da9870d3831db4d7decb9e455cdd7554641d1c4f9f8bc9c3411`
- Scope: 1,279 failed-breakout-reversal expert-at-onset observations
  over six markets and the same 14 UTC development dates Apr 12–25.
- Predeclared 15-minute outcomes: expert 384 vs matched LONG 384
  (difference 0) and SHORT 364 (+20).
- 30-minute: expert 489 vs LONG 474 (+15) and SHORT 395 (+94).
- 60-minute *primary*: expert 539 vs LONG 507 (+32 = +2.502
  percentage points), SHORT 445 (+94 = +7.349 pp).
- 120-minute: expert 593 vs LONG 568 (+25) and SHORT 499 (+94).
- At the primary 60-minute horizon, cross-market UTC-day-block
  differences vs matched LONG: 7 days >0, 6 <0 and 1 tie.
- Leave-one-UTC-day-out, pooling all six correlated markets jointly:
  +1.419 to +3.863 pp against LONG; +6.266 to +9.013 pp
  against SHORT. These are NOT confidence intervals.
- Leave-one-market-out paired rate differences:
  +1.626 to +4.373 pp versus LONG (six exclusions);
  BNB was the one market with negative standalone
  failed-reversal difference vs LONG (-14 favorable episodes).
- Six-expert aggregate was worse than both matched constant-direction
  controls at 60 minutes.

This development-period *post-selection* signal is not statistically
independent, not cost-adjusted, and not proof of skill or profitability.
Fifteen-minute directional value versus LONG is zero; the 60-minute
advantage is small, and fewer than half of correlated UTC-day blocks
showed a positive difference versus LONG. No selection weights, expert
rules, exit horizon, or trade execution rules were changed.

### Phase 2L — freeze a prospective validation contract before new data access

**Candidate under test:** only the frozen `failed_breakout_reversal`
expert at onset, from strategy implementation commit
`384d08906a8cf9b0ed3e471ee126af680b90fc71`.
The other five expert rules remain unchanged and the complete
six-expert engine is NOT considered a candidate for deployment.
No new threshold or gating based on observed April data is permitted.
The experiment's goal is to test a hypothesis, not maximize signal counts.

**Universe:** predeclared BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT,
BNBUSDT USD-M perpetual contracts, each replayed independently using
the identical one-market causal decision logic as Phase 2J.
Include BNB: excluding a weak market after seeing results is prohibited.
The 14 Apr 12–25 days and the entire April/May 2026 period are
development only; none can be reused as unseen validation.

**Proposed first untouched chronological validation window:**
2026-06-12 through 2026-08-25 UTC inclusive, for all six markets.
This is a prospective *evaluation plan*, not a claim that these dates
are genuinely untouched in every external project. Before reading
labels, independently audit whether this span or its outcomes were
used by any prior model research; if already consulted, choose a
later untouched contiguous period and record that change **before**
opening its source data. Reserve a subsequent later contiguous test
interval for a final untouched audit, with no inspection or fitting
during primary validation. Require fully authenticated historical
ZIP and sidecar provenance, 1m OHLCV continuity, exact
15m/1h/4h reconciliation, context warmup across month boundaries,
full 120m future labeling with no selective truncation, and pinned
strategy bytecode/source hash. The existing T7Sonic historical replay
is hard bounded to April–May and MUST NOT be unlocked in place:
a separate, audited research-only validation loader and tests
must be created before any June+ replay.

**Primary fixed metric:** paired difference in favorable outcome
share at exactly 60 minutes using strict +10bps versus neutral and
strict -10bps versus neutral, relative to both matched always-LONG
and always-SHORT on *exactly the same expert onset timestamps*.
Count every onset including neutral, do not relabel a first-future-1m
candle open as an achievable fill, do not select a better horizon.
The 15/30/120m horizons, market and day breakdowns are **secondary**
diagnostics, not grounds to change the locked primary metric.

**Sensitivity and uncertainty, fully predeclared:**
group all six markets into each UTC calendar-day block, never treat
the six coins as independent, and report day-aggregated numerator
and denominator per matched side. Compute a chronological 7-day
moving-block bootstrap over *whole six-market UTC day blocks*,
with fixed 10,000 resamples, fixed deterministic seed 20261011,
and two-sided 95% percentile bounds for each paired delta, alongside
the observed paired result. A bootstrap CI here is an approximation,
not proof of economic value. Include raw daily and per-market effects;
leave-one-day-out and leave-one-market-out only as sensitivity analyses,
never as significance tests.

**Predeclared directional-research gate:** pass only if both
matched-direction paired differences are positive, both approximate
95% block-bootstrap lower bounds are above zero, at least two of
three chronological monthly groups have a positive difference
against BOTH matched directions, and at least four of the six
markets have a positive difference versus BOTH controls.
If any predeclared comparison is absent, ambiguous, or materially
incomplete, the gate fails rather than censoring unfavorable cases.
Passing is only eligibility for further realistic execution analysis,
NOT authorization to trade, publish, or claim profitability.
Do not relax a failed gate or rerun alternative thresholds on the same
validation data.

**Separate economic/execution gate:** historical 1m candles and
same-onset constant-side baselines cannot validate bid/ask,
liquidity, fill latency, depth, spread, taker/maker fees, funding,
or stop/target first touch. Before any production decision, require
a predeclared entry/exit/invalidation policy with actual or
conservatively justified executable quotes and conservative intrabar
ambiguity handling. Report after-cost R/expectancy and adverse
excursion/drawdowns, simultaneous positions and portfolio limits,
including no-trade cases. If authentic execution evidence is
insufficient, economic certification fails; do not fabricate
historical order books or retrofit best-case fills.

**Prospective operation gate:** only after independent chronological
directional and after-cost gates are met, separately run a
paper-only forward period with the original legacy engine still
stopped, no orders and no Telegram signal publication without explicit
authorization. Production migration requires a distinct reviewed
deployment PR and operator approval; this research PR cannot grant it.

## Phase 2M — VPS frozen-plan execution verified by operator

The operator ran the no-market-data validation planning CLI on their
VPS at exact source revision
`52dc5eb75360802ada4e429f93823d6d04db79d0`.
The tool's fixed plan passed its schema guard: six markets,
75 UTC calendar days, 450 market-days, exactly 72 proposed monthly
archive/sidecar pairs for June–August. The legacy production engine
remained stopped and its restart policy was `no`.

Operator-reported evidence:
- `/var/tmp/t7sonic-phase2m-plan-j4vu0vzr.json`
- JSON report SHA256
  `c60e0f8ee11bf44136c4e3db7f620ff2dfc008d0837c1bd9f9d4a33feb63a392`
- Frozen plan internal SHA256
  `99d964840b8d2c49d3c99ee03204e9ffa632e2b5606809d477fdfe3e1dfb6f29`
- Runtime status
  `BLOCKED_UNTIL_CONTAMINATION_AUDIT_AND_SEPARATE_LOADER`.

This proves only that a deterministic frozen specification was
produced. No June–August market record was accessed or independently
certified as a valid holdout.

### Phase 2N — holdout contamination survey, metadata first

Before developing/running a new historical validation reader, collect
*metadata only* from existing VPS research workspaces and GitHub
code history: file names, project names, experiment date-range
descriptions, and prior model/test use. Do not inspect June–August
candles, labels, reports or research outcomes during this audit.
If previous validation/hyperparameter selection, market outcome
review, or strategy development used any part of June 12–August 25,
that span cannot serve as an untouched confirmation set.

An absence of date-labelled files alone is **not** evidence of
clean holdout: filenames can omit dates, data can exist on old
workstations, and external projects/research may have previously
revealed outcomes. Manual disclosure covering V4/V5/V6HBR, other
JalTerminal and MV branches, local PCs, VPS backups, online
visualizations and external sources remains required.
Mark missing/ambiguous exposure evidence as `UNRESOLVED`;
never auto-certify clean data from a filesystem scan.

Production, Telegram, order execution, and June–August data access
remain disabled until a separate research-only validation reader
and no-lookahead/integrity tests pass and operator attestation is
documented.

## Phase 2N — VPS filename-only evidence, completion status UNRESOLVED

Operator executed the sealed Phase 2M planning checkpoint and a
metadata-only Phase 2N survey on October 11, 2026. No June–August
candle data or historical outcome labels were read. V4 remained
stopped and restart=no.

Operator-reported Phase 2N evidence:
- Report `/var/tmp/t7sonic-phase2n-audit-U3N7WVN8.json`
- SHA256 `45f22b4d58377429bf3be57db63880d99d0f6bd09aa2b53d3b49a775a0c3602c`
- Limited to preselected research-directory names under `/var/tmp`
  and `/tmp`; 6,511 directory entries visited; 30 matching paths.
- Eighteen entries were June 2026 source-archive/manifest/lock
  filenames under `/var/tmp/mv-v5-history-archives`: four BTC
  intervals (1m/15m/1h/4h) and two ETH intervals (1h/4h), each
  represented by ZIP, manifest, and lock path.
- Twelve were V5 acquisition batch-ledger/lock filenames referencing
  June (four BTC and two ETH ledger paths plus six locks).
- No July or August filenames were matched in this limited scope.
- All observed paths indicate some prior June source acquisition
  or management but do not prove V5 strategy evaluation, use of
  June labels in model design or contamination of T7Sonic rule choice.

**Gate remains BLOCKED/UNRESOLVED.** No claim that the planned
June 12–August 25 span is untouched follows from this survey.
Next audit should collect acquisition provenance fields and file
timestamps (without opening ZIP or strategy outcome outputs), check
other likely workspaces by filename only, and request explicit
human attestation on whether any earlier V4/V5/V6HBR/JalTerminal
model or human research reviewed that span's price outcomes.
If any substantive prior evaluation is confirmed or evidence
remains incomplete, do not label the proposed span an untouched
independent confirmation. Record a revised chronological window
and separate final sealed test before gathering new source labels.

## Phase 2O — acquired June data, but prior strategy use remains unknown

The operator performed the Phase 2O provenance survey without opening
source candles or outcome reports. Frozen Phase 2N input hash and
production-stop assertions passed.

Operator evidence:
- `/var/tmp/t7sonic-phase2o-hlhExdwI.json`
- Report SHA256
  `daa04d49e179130110cd82a307cd0a1b7939e5ba38d29efe142577a7d91183ce`
- June 2026 Binance source ZIP filesystem modification times:
  BTC 1h `2026-10-10T09:30:13Z`; BTC 4h
  `2026-10-10T09:35:42Z`; BTC 15m
  `2026-10-10T09:39:31Z`; BTC 1m
  `2026-10-10T09:48:10Z`; ETH 1h
  `2026-10-10T13:34:27Z`; ETH 4h
  `2026-10-10T13:34:39Z`.
- Metadata sidecars declared `2026-06` and full monthly
  row counts of 43,200 (1m), 2,880 (15m), 720 (1h), 180
  (4h). The fields `publisher_checksum_retrieved_at` and
  `checksum_policy` were absent/none for these older files.
- Additional filename-only survey: `/opt/mv-signal` 3,976
  entries, no matched June–August path printed. An
  `/opt/jalterminal-app` directory was not present at
  this specific time/location. This is not a survey of all
  old Git commits, deleted files, local workstations, other
  backups or off-server workspaces.
- Original production engine remained stopped with restart=no.

**Interpretation:** the October 10 modification times support recent
archive acquisition/management on this VPS. They do NOT prove that
June–August historical market outcomes were evaluated, and do NOT
establish that those outcomes were never used elsewhere. In
particular, October 10 is before the October 11 frozen candidate
plan, but filesystem mtimes alone are not a reliable source of
original acquisition or prior-use history. The independence gate
remains `UNRESOLVED`; no market outcome analysis is authorized.

### Phase 2P — separately gated synthetic validation source adapter

Add a separate `t7sonic_validation_loader.py` on the isolated research
branch, leaving April–May historical and expert code untouched.
Its accepted dates are strictly the proposed June 12–August 25,
2026 interval; it uses the six frozen markets and the Phase 2M
plan checksum. An unaudited call is rejected before opening any
archive. Name-only source presence checks are available without
reading market data. The authenticated source-window routine requires
a separately declared approval record stating a completed independent
exposure review, a later reserved final holdout interval, frozen
strategy SHA, the exact plan SHA, auditor and evidence reference.
These approval fields are procedural checks, **not independent
proof** of zero prior exposure: independent human/source audit
still governs authorization.

Synthetic fixture tests generate internally consistent full-calendar
June ZIP and sidecars (not Binance data) to exercise month integrity,
checksum mismatch refusal, 1m/15m/1h/4h reconciliation,
causal five-frame snapshot cutoffs, fixed universe/date bounds,
and default denial of unaudited access. The original live
production tree and Telegram are not imported or modified.
This adapter intentionally does NOT generate episode outcome
labels, change decision rules, publish trade signals or grant
permission to access a real June–August holdout. It also does
not replace an independent comparison with the upstream
publisher .CHECKSUM before opening real archived sources.

## Phase 2P — external validation source readiness, archive names only

The operator executed the separate Phase 2P presence-only preflight
at pinned research commit
`a461f8c99a4a3d3d188a026853df00a91df48e17`,
without reading exchange historical market values or outcomes.
The frozen six-market and three-month list implies 72 monthly
ZIP-plus-sidecar source pairs (6 symbols x 4 timeframes x 3 months).

Operator-reported evidence:
- `/var/tmp/t7sonic-phase2p-UzIZqgs7.json`
- SHA256 `2953267eac102786d49ccf6d0b6f33125961f947f17c8ade1379f773310b41f9`
- June 2026: six of 24 pairs present (BTC 1m/15m/1h/4h;
  ETH 1h/4h), 18 missing.
- July 2026: zero of 24 pairs present, 24 missing.
- August 2026: zero of 24 pairs present, 24 missing.
- Overall: 6 present, 66 missing; neither present nor
  absent denotes content integrity, publisher authentication,
  independent holdout suitability or directional performance.
- Frozen original production service remained stopped,
  restart=no; no trades or Telegram messages were emitted.

The source-readiness result is a *storage inventory*, not
a go-ahead to acquire or evaluate the missing 66 pairs.
The provenance and prior-use audit for June 12–August 25
remains unresolved. Before fetching real source data or
assessing directional outcomes, obtain a credible independent
prior-exposure review or select a genuinely future/sealed
validation period.

### Synthetic seam regression: July and August month transitions

The separate validation loader receives additional synthetic
fixture testing for June/July and July/August at the first
UTC calendar-day cutoffs, where the 1m/15m/1h/4h completed
warmup can require the previous source month. The tests
also check date-scoped source expectations on July 15,
full calendar July fixture integrity, as-of timestamp
cutoffs, and absence of future bars. Test data are artificial;
they must not be interpreted as Binance-market or independent
validation evidence. This does not unlock the holdout or
enable the original April-May replay on June-August.

## Phase 2Q — conservative forward-only evaluation path (synthetic planning)

Because no human attestation establishes that June–August 2026
was never used by previous V4/V5/V6HBR/JalTerminal research,
**that retrospective proposed validation remains blocked**.
The operator authorized continuing development; this does NOT
constitute a declaration that the old period was clean.
No download or evaluation of 66 missing June–August archive pairs.

A separate immutable forward-only research precommit protocol has
been added as `t7sonic_forward_protocol.py`, preserving the
original expert-selection source SHA
`384d08906a8cf9b0ed3e471ee126af680b90fc71`.
Predeclared prospective observation interval:
**2026-10-15 00:00 UTC inclusive to 2026-12-29
00:00 UTC exclusive** (75 days, six markets, fixed 5m cutoffs).
This interval is a PROPOSAL for a forward paper-research trial,
not an operating signal service or retroactive substitute for
a separately reserved final audit period.

The new code is a **synthetic-only protocol validator**:
it accepts an all-six-market list of as-of WATCH hypotheses
(including explicit no-WATCH cases), rejects missing/duplicated
markets, actionable price/stop/target fields, wrong expert source
digests, early/late receipt claims and missing/noncontiguous
5m boundaries. Each full six-market packet has a canonical
SHA256 linked to the previous packet. All future labels,
trades, Telegram publications and production deployments
remain absent. Existing market-history modules and heuristic
expert rules were not changed.

**Essential security/data-validity limitation:** caller-supplied
receipt times and hash links alone do NOT prove any event was
recorded in real time. The code explicitly reports that
trusted timestamps are NOT implemented. No live collector,
network exchange connector, persistent append-only receipt
service, immutable outside-VPS witness or auditable capture of
pre-outcome data has been deployed. A later separately reviewed
component is required to obtain trusted real-time Binance
source timestamps, preserve finalized as-of candles and
raw response digests, record all six markets at each boundary,
prevent backfilling and skip/censoring, and seal decisions
before the 15/30/60/120-minute future prices are observed.
Do not count a synthetic packet as a real observed signal.

**Approval gate:** production V4 remains stopped (restart=no);
PR #14 does not include live collection, Telegram, orders or
legacy worker modifications. The October window must not be
represented as an operational trial until a trusted receiver,
source-authentication and archive retention policy are
reviewed/tested, and user explicitly authorizes paper-only
observation. Outcome labels, costs and risk are separate
subsequent non-actionable stages.

## Phase 2Q — VPS verified frozen forward protocol (operator evidence)

The operator ran the pinned isolated research Docker image from
`c9c2d6acde4c2f501ddbe3f573895b47f2c9c44a` with
network=none, read-only filesystem, cap-drop all, non-root uid 10001,
and verified its zero-trading synthetic forward planning output.
The MV production engine remained stopped, restart=no.

- Report `/var/tmp/t7sonic-phase2q-plan-PKNhg0II.json`
- Report SHA256
  `1f3db26b5e6d0711ee933263a87ede32754b5c80b684973e70a84df8e955afb8`
- Frozen protocol SHA256
  `9bed9f51446fb5a76ff9fe64b507028bf09594c09887bd6c1c4bc0335cb237ee`
- Six existing markets, 2026-10-15T00:00Z inclusive to
  2026-12-29T00:00Z exclusive.
- Trusted live recorder was explicitly **NOT DEPLOYED**.
  No trades, Telegram messages or signed timestamp receipts.

### Phase 2R — synthetic, explicit data-outage accounting

The isolated research-only module
`t7sonic_forward_coverage.py` introduces a third five-minute
cycle class: **DATA MISSING / NOT EVALUATED**. Never treat missing
market data, delayed source completion or a late collector as a
valid no-WATCH candidate. An affected cycle must carry an explicit
one-of-enumerated failure reason. Every affected market is marked
`DATA_MISSING`, and all other markets for that 5m cycle are marked
`NOT_EVALUATED_DUE_TO_PARTIAL_SOURCE_FAILURE`, even when their
inputs may otherwise have arrived.

Complete WATCH batches and synthetic gap batches share one
strictly contiguous SHA256 chain, with all six markets included.
The checker verifies status, source revision, deadline *claim*,
original failed-reversal expert/direction consistency,
ordered nonduplicated market coverage, no trading permissions,
and non-censoring of outage cycles. A digest-only external
timestamp request record is available but is marked
`UNSUBMITTED_EXTERNAL_TIMESTAMP_REQUEST`; it does not send
network traffic or certify an actual timestamp. The protocol's
real collector, time synchronization, external witness,
append-only durable journal, source provenance and future-outcome
sealing are **still unimplemented**.

The test suite is synthetic only. Passing these gates demonstrates
the planned format and gap-inclusion invariants, not real time,
immutability, authenticity, fair evaluation or profitability.
The proposed 2026-10-15 forward start is not yet an operating
trial; if the collection service cannot be certified in advance,
the predeclared observation window must be restated from a
later truly prospective date **before any real results are viewed**.
Do not backfill days with historical prices and call them forward
records. The previous June–August holdout remains unapproved
due to unresolved prior-outcome exposure.

## Phase 2R — VPS offline gap protocol certified by operator

The operator executed the frozen research commit
`bf91f0f0bfd3f6e84a7cbf819c2e3b707aec259d` in a
restricted standalone Docker image (network=none, read-only,
non-root, capabilities removed). Three synthetic five-minute
cycles comprising WATCH, GAP, WATCH verified with contiguous
SHA256 links; complete cycles=2, explicit missing-source cycles=1,
coverage=0.666667. The data gap was NOT counted as an ordinary
no-WATCH event. External timestamp evidence was explicitly
NOT IMPLEMENTED. The legacy MV production engine remained
stopped (restart=no); no trades or Telegram messages were
emitted. This is proof of offline logic only, NOT a real
prospective market observation.

### Phase 2S — offline append-only journal and restart safety

The separate file `services/t7sonic/forward_journal.py` is a
minimal OS-backed offline **synthetic-only** journaling prototype.
It intentionally resides *outside* the sealed research inference
image, and does not import exchange/network/trading workers.
It opens only a caller-supplied absolute pathname under a private
0700 directory, enforces file owner/mode 0600 and single-link
non-symlink regular files, obtains an exclusive nonblocking
Linux flock, and scans *every* canonical JSONL record on reopen.

Each append validates the exact next five-minute boundary and
prior SHA256; separates complete/watch from missing-data/gap
events; requires all six markets; writes one bounded-size
canonical JSON line via O_APPEND and fsyncs the file. A
partial/torn final line, altered record, duplicated timestamp
or omitted boundary fails CLOSED and is **not auto-repaired**.
A second concurrent writer fails locking. A new journal file
is fsynced together with the containing directory.
Offline synthetic tests exercise those invariants, including
restart and one cycle after a gap. The existing independent
market-history, expert, live production, Telegram and
payment/order paths have NOT been changed.

**Limitations / next certification:** the journal does not
collect Binance candles, does not verify whether caller-supplied
receipt times are real, does not provide independent signed
time witnesses, does not protect against an administrator
rewriting the entire history including hashes, and does not
reserve a remote durable replication destination. Its status
is explicitly offline/synthetic, never an independently
authenticated paper-research history. No scheduled observer,
deployment, exchange connectivity, trading or Telegram message
publication was activated. Before any forward trial, separately
review source authenticity, trustworthy time stamps, external
witness receipts, disk crash/restart drills, non-censoring
of collector outages and an independent retention location.
The proposed October 15 start must move forward if these
gates are not met before any real outcomes are observed.

## Phase 2S — VPS regression confirmation after umask correction

The operator ran exact pinned research commit
`cd1ea0dec0702e02275e5446f0696f05b6918cfe`
on the VPS with shell `umask 077`.
All **98/98** synthetic research tests passed in 6.207 seconds,
including offline journal restart, corruption detection,
locking and refusal of insecure parent permissions.
The corrected test fixture explicitly chmods the deliberately
unsafe directory to 0755; relying on
`mkdir(mode=0755)` was invalid under `umask 077`.
Original production engine remained stopped (restart=no).
No orders or Telegram signals were sent. No live market data,
independent time witnessing or genuine paper trial occurred.

### Phase 2T — offline, pre-network source intake verification

New standalone, **not deployed** helper
`services/t7sonic/forward_acquisition.py` defines an
exact prospective source request contract for public Binance
USD-M futures `GET https://fapi.binance.com/fapi/v1/klines`:
fixed six symbols, fixed 5m as-of boundary between 2026-10-15
and 2026-12-29 UTC, 1m/15m/1h/4h data only, pinned
startTime, endTime (last completed candle's inclusive
millisecond), and limit. The input requirements are precisely
480 consecutive 1m rows plus 64 rows for each higher frame,
and each row must have the 12-entry kline schema with exact
open and close-time geometry, finite positive OHLCV and
no duplicate, missing or future/uncompleted bars.

The helper accepts **injected raw response bytes**, explicit
status code and claimed reception time; it DOES NOT perform
HTTP requests. It rejects non-200 status, redirects, stale
claimed responses and malformed/oversized bodies. It hashes
raw response bytes and request metadata, verifies native
15m/1h/4h candles against the corresponding completed 1m
aggregate, and constructs the exact existing causal 5-frame
T7Sonic perception snapshot from the 480-minute warmup.
No future outcome labels or fee/trade execution calculations
are available. Its tests use only synthetic, internally
consistent twelve-column kline-shaped fixtures and tampered
negative cases. The original April–May retrospective engine
and expert rules are unchanged.

**Crucial trust boundary:** Binance's public klines REST
response is not independently cryptographically signed.
TLS, raw-body SHA256 and a caller-provided receipt time,
even if validated locally, do not prove remote source
authenticity or real-time pre-outcome capture. TLS pinning,
auditable HTTP exchange, independently verifiable timestamp
witness, remote append-only evidence storage, complete
six-symbol simultaneous observation, outage cutoff and
crash recovery certification remain distinct prerequisites.
The current Phase 2T helper offers no network connection,
daemon, deployment permission, Telegram or order execution.
The October 15 proposed start is still NOT an active trial.

## Phase 2T — operator-confirmed offline source contract

On the VPS, the operator tested research revision
`b285af6dfd0fb81bea0a3c130b4706e67fdc98bf`.
All **105** synthetic tests passed. The frozen BTC request plans
were 480 x 1m and 64 x each 15m, 1h and 4h completed candles.
Source request planning performed zero HTTP requests and opened
zero exchange-market records.

The operator-reported evidence JSON:
`/var/tmp/t7sonic-phase2t-plan-RgQD7j9I.json`,
SHA256 `2bf3fb2b0cff9add0c8cf559e587f77079d13b1e57e1f0dd2ecb8deed010a784`.
The MV trading engine remained stopped and restart=no;
no orders, trades or Telegram signals.

### Phase 2U — optional HTTPS origin restriction (still NOT deployed)

A separate `services/t7sonic/forward_https.py` provides
a **disabled-by-default** optional single-request adapter for
the approved public Binance USD-M `/fapi/v1/klines` path,
without installing or deploying an observer. It accepts only
the exact immutable Phase 2T request plans. Its optional
network method uses system-CA/hostname-verifying HTTPS,
explicit no-proxy handling, no redirects, bounded body reads
and bounded timeout, and rejects non-200 status and anything
other than JSON media type. A synthetic response injection
interface tests all failure cases without network access.

Every HTTP response must pass the original 12-position OHLCV
geometry and completed-bar validation before any downstream use.
The module records deterministic request/raw-body digests
but deliberately marks all receipt times as *local machine
clock claims without independent attestation*. Its TLS
certificate verification proves only authentication to the
configured HTTPS origin under the OS trust store; it is not
a Binance data signature or proof of genuine pre-outcome
timing. Local logs are not tamper-proof.

The adapter is not a scheduled service; no collector is
deployed, no witness receipts, clock-drift guard, off-server
append-only replication, or complete all-six-market boundary
recording is configured. Publication, orders, live trading,
and existing production runtime changes remain prohibited.
A paper-only forward evaluation must NOT start simply because
these offline transport tests pass. If October 15 arrives
before those additional safeguards are certified, the
proposed start must move to a later genuinely prospective
window, without retrospective backfilling.

## Phase 2U — VPS exact-revision offline verification

The operator ran the research-only source checkout at pinned
`2511fbc501661af3586615e7dbf8e5eb683420ea`.
All **115** research tests passed in 6.431s. The frozen
HTTPS source plan was accepted, but an attempt to call the
optional HTTPS getter without explicit approval raised
`PermissionError`, as designed.

The operator's Phase 2U JSON evidence:
`/var/tmp/t7sonic-phase2u-UGoIryVo.json`,
SHA256 `37ad26a42eba7d7499b650a48baaea3c6724b765ac6b124cd956ae8f084f6598`.
The MV engine remained stopped with restart=no; no
Binance network calls, independent timestamps,
trades, orders or Telegram messages occurred.

### Phase 2V — all-market evidence bundle for independent timestamp handoff

`services/t7sonic/forward_witness.py` creates an
**UNSUBMITTED** SHA256 imprint encompassing the exact
pre-outcome complete-six-market WATCH batch and 24 explicit
four-timeframe source receipts (1m/15m/1h/4h per market).
For real no-WATCH cycles the full 24 source receipts remain
required. For an explicit DATA-GAP batch the witness request
contains zero valid source receipts, and the status remains
MISSING_DATA, not NO-WATCH. All packets must have a valid
contiguous previous SHA and five-minute boundary. Frame
receipts must match the original symbol, boundary, request
URL, raw-body digest and unverified local receipt claim,
and must not claim exchange signing or independent
timestamp proof.

The module emits a deterministic content SHA256 suitable
for submission to an independently controlled external
timestamp authority in a later stage. It does **not**
contact a service, issue a genuine RFC3161 timestamp
token, validate TSA certificate chains, guarantee TSA
independence, upload source bytes to off-VPS storage or
implement a real collector. Its verifier explicitly refuses
any falsely marked timestamp/replication/trading claims.
All tests are synthetic and offline; successful source
digest assembly is NOT independent evidence of a
pre-outcome decision timestamp.

The forward start of 2026-10-15 remains provisional.
Do not automatically deploy any observer, count unsigned
offline packets as forward observations or backfill a
previously missed decision-time window.

## Phase 2V — VPS witness-contract verification

The operator ran exact source revision
`6a1186a262c034b877b333bb1f97b7497b3cf019`
on the VPS. All **121** offline/synthetic tests passed
(in 6.848s); the explicit 6-symbol x 4-source-frame
witness manifest requirement of **24 source receipts**
passed. No external timestamp was verified.
No live market data was acquired, and the production
engine remained stopped with restart=no; no trades
or Telegram messages were sent.

Preserved operator evidence:
`/var/tmp/t7sonic-phase2v-7bS4T7a0.json`
SHA256 `125ed8e09d51cbf897873755546c5eba7dcac19424e7b643e172287c262a2d28`.

### Phase 2W — RFC3161 signed timestamp checking (OFFLINE ONLY)

`services/t7sonic/forward_rfc3161.py` introduces a
separately housed OpenSSL-based **offline verifier** for
RFC3161 TSA responses and a nonce-bound request generator.
It verifies the exact precommit witness SHA256 imprint,
the submitted query's nonce and certificate-request flag,
an explicitly pinned SHA256 of the TSA trust-anchor PEM,
the signed TSA certificate chain, the approved policy OID,
and the TSA-signed generation time against the frozen
60-second observation deadline. A nonce mismatch, untrusted
CA, wrong policy, tampered token, forged witness-manifest
digest, or token genuinely signed OUTSIDE the deadline
fails closed.

Tests create an **ephemeral, self-signed synthetic TSA**
during unit-test execution, never ship its signing key.
A locally signed test response from October 11 is
cryptographically verifiable but explicitly rejected because
it precedes the frozen October 15 start. The synthetic
test demonstrates independent requirements for valid
signature *and* acceptable timestamp; it is not a positive
in-window independent TSA certification.

**Important outstanding gates:** No real outside TSA
or chain of trust has been selected/attested by an independent
operator; no RFC3161 request has been sent to one; no actual
external response has been accepted. The offline verifier's
trust-anchor and policy values must be independently chosen,
pinned and audited before actual collection, or a locally
controlled mock TSA could yield cryptographic signatures
without independent evidence. No off-VPS immutable raw
kline/decision-evidence retention, clock-drift verification,
24-source real-time batch synchronization, forward daemon
or crash-gap certification is deployed. OpenSSL verification
of an outside-signed timestamp alone also does not authenticate
Binance's unsigned REST payload or prove strategy profitability.
No live source collection, trading, Telegram publication,
production restart or PR merge is authorized.

The 2026-10-15 scheduled forward start remains
**provisional**; a later genuinely prospective, predeclared
window is mandatory if operational integrity controls are
not externally approved before it starts.

## Phase 2W — exact-revision VPS certification, offline only

The operator completed the VPS check at
`a67e6e1789511990f26567746bce8b849b9a2c12`
under `umask 077`, using installed
`OpenSSL 3.0.13 30 Jan 2024`.
The complete synthetic/offline test suite passed:
**126 tests**, 6.837 seconds, `OK`.

Evidence `/var/tmp/t7sonic-phase2w-dxcvX79W.json`,
SHA256
`f4c87aca29e161c0366beb14e5658be0952e3c39e6256b96cac0ac0c5d7b1e0e`.

Mock signer tests did NOT select an independent outside TSA;
the VPS remained network-denied by default and the original
MV production engine was stopped with restart=no.
There was no real signed outside timestamp, live market
collection, paper study, order or Telegram publication.

### Phase 2X — offline provider-neutral timestamp HTTP handoff

An additional `services/t7sonic/forward_tsa_handoff.py`
provides an RFC3161-over-HTTPS *request plan* based on the
full-six-market Phase2V witness manifest and Phase2W
nonce-bearing SHA256 query. RFC3161 HTTP uses
`application/timestamp-query` for the POST body
and `application/timestamp-reply` for the DER response;
see RFC3161 section 3.4 and RFC editor erratum 1879.

The offline contract rejects ambiguous URLs, non-HTTPS,
credentials, fragments, local/IP destinations, unknown
policy OIDs, absent preapproved CA fingerprints,
queries mismatching the witness imprint, redirects,
non-200 or malformed/oversized response envelopes.
The response-envelope inspector NEVER elevates an
HTTP success to a verified independent signed timestamp.

The planned transport intentionally provides **no actual
HTTP client** and no default TSA selection, no real CA
pin and no certificate attestation. The proposed provider
host/policy/root must be independently identified and
documented, and signed responses independently checked
by Phase2W. Network egress DNS/IP restrictions, off-server
append-only raw response retention, outage coverage and
complete simultaneous live sampling remain unimplemented.
The October 15 prospective start remains provisional,
and expired observation boundaries must never be backfilled
from later price outcomes or unsigned local journals.
No research PR code is merged into production.

## Phase 2X — VPS synthetic handoff evidence, preserved

Operator executed exact research commit
`962d06892a8f84bdcce4902bcad4e6c33ed09b9f`
on the VPS under `umask 077`. The whole offline
test suite passed **133/133** (7.451 seconds), and the
synthetic unsigned RFC3161 request and hypothetical
provider-neutral HTTPS POST manifest passed with 24
expected frame receipt entries. There was **no real TSA
request**, no validated external certificate/policy,
no paper collector and no trading approval.
Original MV engine remained stopped (restart=no).

Source evidence:
`/var/tmp/t7sonic-phase2x-ax5SGtlY.json`,
SHA256:
`a5a9b776d05e95d282d4be96a348bd5e49009e5ec0a70c1472f2ec06ea633ff4`.

### Phase 2Y — offline portable raw-evidence bundle

Add `services/t7sonic/forward_retention.py` as a separate,
non-deployed, standard-library-only portable evidence bundler.
For every full-six-market WATCH (including a valid no-WATCH
decision), it requires all **24** actual raw source-response
byte strings to match the SHA256 digests recorded in the
existing, unsigned Phase 2V witness manifest. It also
binds the complete model decision packet and the unsigned
witness manifest in one deterministic ZIP_STORED archive
(`decision.json`, `unsigned-witness.json`, 24 typed
`source/SYMBOL/FRAME.bin` files). For a proper DATA GAP,
the archive contains only the packet plus the gap witness
manifest, never invented raw data or NO_WATCH classifications.

The offline verifier checks the expected member ordering,
no omitted/extra/duplicate entries, no compression or
encrypted-member acceptance, canonical JSON bytes,
SHA-256 of each raw byte response and consistency of
witness/decision digests and deadline-bounded claimed
receipt records. It never extracts files. Test fixtures
use tiny artificial raw bytes, not actual Binance candles.
The offline bundle itself is capped at a bounded size.
The ZIP is deterministic for identical inputs, suitable
for future off-server content-addressed delivery after
a separately approved witness/retention design.

**Critical:** building or verifying a ZIP locally does
NOT prove the exchange origin, a trusted timestamp,
off-VPS replication or that an earlier chain pointer
really exists in a complete journal. This tool does
not upload evidence, operate a live source, contact a
real TSA, enforce remote append-only immutability,
or enable trading, Telegram or production restart.
The proposed October 15 start remains conditional
and must move forward if real prospective controls
are not certified before observation begins.
