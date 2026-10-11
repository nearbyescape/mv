# T7Sonic — research foundation and controlled development contract

**Status:** DRAFT ONLY. Not a production strategy. No trading signals, portfolio orders, execution quotes, stop losses, risk budgets or exchange activity are authorized. Created on its own `codex/t7sonic-research` branch from `main` while the existing V4 engine remains stopped by operator action on the VPS.

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
