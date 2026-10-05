# Phase 5.1: diagnostics and exit comparisons

Implemented and exercised locally on 4 October 2026. This delivers the first improvement step: trade diagnostics and controlled exit comparisons. **Neither alternative establishes a robust trading edge; no policy is promoted to live signals.** Entry filters, ATR-stop studies, production sizing and forward paper tracking remain later work.

## Registered experiment

`packages/contracts/exit-study-v1.json` registers three policies, three original cost scenarios and three original periods: 27 experiments. Registration occurred after viewing the original overall baseline, before viewing the new variants/cohorts. All 2024–2025 periods are previously viewed; this study is exploratory, not a fresh holdout. No new market period was opened for selection.

| Policy | Versioned research strategy | Active exits |
| --- | --- | --- |
| Baseline | `EMA-PULLBACK-ATR-v1` | Stop, target, EMA50 |
| Stop / target | `EMA-PULLBACK-ATR-EXITS-ST-v1` | Stop and target; EMA50 disabled |
| Stop / EMA50 | `EMA-PULLBACK-ATR-EXITS-SE-v1` | Stop and EMA50; target disabled |

Policies share completed 1H entries, seeded indicators, exact 4H alignment, delay/quote/expiry/drift checks, reference geometry, rounding, fractional capital caps, costs and actual funding. Disabled targets remain explicitly inactive reference levels, never exits. Variants carry distinct strategy/risk identities and decision IDs. The live contract and live evaluator/risk builder are unchanged.

Original report/latest pointer and source identity are preserved. Before code changes, exact strategy/research sources were copied to `artifacts/baseline-source/<original-code-hash>/` with a matching checksum manifest. Study publication requires exact parity of all nine baseline groups and every original trade/evidence record. This passed. Atomic study reports have a separate `artifacts/exit-studies/` namespace.

## Actual results

Each cell is net return after modeled execution/fees and actual funding. Every experiment starts independently with 10,000 USDT split across BTC/ETH; rows cannot be added or compounded.

| Previously viewed period | Scenario | Baseline | Stop / target | Stop / EMA50 |
| --- | --- | ---: | ---: | ---: |
| 2024 | Baseline costs | −27.68% | −14.77% | −28.28% |
| 2024 | Higher costs | −41.97% | −21.90% | −40.47% |
| 2024 | Delayed entry | −29.27% | −11.88% | −29.43% |
| Jan–Jun 2025 | Baseline costs | −17.91% | −12.13% | −16.60% |
| Jan–Jun 2025 | Higher costs | −29.66% | −22.03% | −26.17% |
| Jan–Jun 2025 | Delayed entry | −18.07% | −10.14% | −16.57% |
| Jul–Dec 2025 | Baseline costs | +1.76% | +4.70% | +4.21% |
| Jul–Dec 2025 | Higher costs | −7.03% | −1.75% | −3.74% |
| Jul–Dec 2025 | Delayed entry | +0.10% | +3.54% | +1.16% |

Stop/target reduces earlier losses but still loses money. Jan–Jun baseline-cost drawdown rises from 20.60% to 26.21% when EMA50 exits are disabled. Final-period baseline-cost drawdowns are 10.38% / 12.45% / 14.61% respectively. Higher costs turn every final-period policy negative.

Final stop/target mean net R is −0.0563 despite +4.70% cash return. Stop/EMA50 mean R is +0.0471, becoming negative with higher costs. Equal-weight R and capital-weighted cash outcomes differ; both remain visible. Changed holding times change later entry availability and cash sizes. These are whole-policy comparisons, not paired exit substitutions on identical trades.

There are 3,722 overlapping records, including the original 1,469 controls, not independent samples. Full metrics, uncertainty, per-symbol results, decision hashes and ledgers are preserved. No winner was selected.

## Diagnostic cohorts

Backend Decimal summaries partition each selected policy/period/cost cohort by coin, direction, exit reason and three completed entry-time features:

| Feature | Registered half-open thresholds |
| --- | --- |
| ATR14 / source close | Below 1%; 1% to below 2%; at least 2% |
| Absolute EMA20−EMA50 / ATR14 | Below 0.5; 0.5 to below 1; at least 1 ATR |
| Direction-aligned source−previous EMA50 / source ATR | Below 0; 0 to below 0.05; at least 0.05 ATR per 1H bar |

Short slope reverses the long sign. Threshold equality belongs to the higher bucket. Classification uses preserved completed source/previous evidence, without future prices. Each dimension's counts and monetary totals reconcile. Tables show counts, net P&L, expectancy in R, win rate, fees and observed MAE/MFE normalized by actual fill-to-stop risk. Cohorts are descriptive, not validated entry filters or significance tests. Exit-reason grouping conditions on a future outcome and cannot prove causality.

Excursions omit unknown exit-minute extremes. Baseline records show 176 observed favorable moves of at least 1R, including 59 eventual losers (33 / 19 / 7 by period). These are censored lower-bound counts, not proof an alternative order could capture that profit. Break-even/trailing exits require their own causal study.

Direction losses change across periods: 2024 shorts lost about 2,458.52 USDT versus 309.20 for longs; Jan–Jun 2025 longs lost 1,526.51 versus 264.83 for shorts. One direction cannot be declared universally superior from these observations.

## Use and reproduce

Open **Research → Trade diagnostics & exits**. Select a viewed period/cost scenario, compare policies, choose diagnostic grouping, inspect all 27 experiments or download evidence. The original Historical results view remains intact. Missing/offline/baseline-mismatch states never invent results. Responsive light/dark cards and keyboard-scrollable tables were exercised.

Protected read-only APIs: `/v1/research/study` and `/v1/research/study/export?file=...`. The loopback server-side proxy is `/api/research/study`. Export names/paths/hashes are checked. No endpoint starts jobs or changes live signals.

From `services/api`, using the pinned original dataset/report:

```powershell
..\..\.venv\Scripts\python -m app.research exit-study
```

From the root with API/website running:

```powershell
.venv\Scripts\python tools/verify-exit-study.py
.venv\Scripts\python tools/verify-backtest.py
node tools/capture-exit-study.mjs
```

A repeated full study reproduced every report/export byte. Independent Fraction checks passed for all 3,722 trades: source/alignment, risk/fills/fees, signed actual funding and net P&L. Independent cohort/count/expectancy/observed-1R checks, original control parity and protected API/export integrity passed. The actual browser downloaded the report and all five intact exports without mocks; light/dark/mobile scans detected no WCAG A/AA violations or app console/runtime errors. Browser fixtures test isolated transport only.

- Study ID: `53156bdc0dc9962c54d59b080bcb104d748f5057c9ffb0c6c590921073831e40`
- Dataset SHA-256: `9f66bc05f0b772985044f3444c2fca57468947233f4b459d4c78066d559f2af2`
- Study code SHA-256: `07851fe92d27ab3ef73f03646567be2e3a199bc639091b178615b462e11ed813`
- Original baseline: `0f0a77a2ec4747d1b6a228208fbd11704d30a67052777c4f7500f1f59b16cfdb`

Keep ignored raw data, source snapshots and reports to reproduce exact identities. All [Phase 5 execution/data limitations](PHASE5_BACKTESTING.md) still apply. Fresh holdout, robust profitability, forward fills, production reliability, Telegram and AI remain unverified.

Next: register a small entry-filter study before viewing its results, test slope and EMA separation individually, retain every trial and later evaluate on separately registered data plus forward paper observations. Stop/confirmation changes and risk sizing need independent tests. Live v1 remains unchanged until a separately reviewed replacement is justified.
