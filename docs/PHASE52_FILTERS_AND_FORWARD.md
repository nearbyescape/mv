# Independent entry filters and forward shadow validation

**Archived observation record.** The owner subsequently canceled paper observation for the live release. Both journals are preserved, the v2 run is `stopped-by-owner`, its worker is stopped, and paper defaults off and is absent from the website. The reproduction commands below describe the earlier research milestone and are not launch instructions.

Implemented locally on 4 October 2026, milestone v0.5.0. These additions do not change live `EMA-PULLBACK-ATR-v1` signals or place exchange orders. Historical tests and newly observed shadow results have separate journals and website views.

## Registered research

`packages/contracts/filter-study-v1.json` fixes three policies before replay: original baseline; direction-aligned EMA50 slope at least **0.05 current ATR per completed 1H bar**; absolute EMA20–EMA50 separation at least **0.5 current ATR**. Each filter is applied independently after a qualifying baseline setup. Equality passes. Slope uses the adjacent previous completed 1H EMA50 with the same seeded history origin. Neither filter changes the original 2 ATR rounded stop, 2R target, EMA50 exit, exact 4H confirmation, entry expiry, drift guard or capital model.

Thresholds were informed by earlier diagnostics. All 2024–2025 periods had already been viewed. Registration before this replay prevents silent threshold searching within this run; it does not create an untouched historical holdout. There is no combined filter, exit-policy winner selection or automatic live promotion.

The same pinned dataset, actual historical funding, independent seeded indicators, three costs and three periods produced **27 experiments and 2,935 overlapping trade records**. All nine original control groups and every original trade/evidence matched exactly. A second complete run reproduced every report/export byte. Baseline-cost trade counts across the three periods are 489 original, 203 slope and 286 separation. Policy and cost records overlap; their total is not an independent sample size.

### Net return at baseline costs

| Previously viewed period | Original | Slope | Separation |
| --- | ---: | ---: | ---: |
| 2024 | −27.68% | −23.25% | −33.57% |
| Jan–Jun 2025 | −17.91% | −1.91% | −2.02% |
| Jul–Dec 2025 | +1.76% | −3.72% | −2.77% |

### Net return at higher costs

| Previously viewed period | Original | Slope | Separation |
| --- | ---: | ---: | ---: |
| 2024 | −41.97% | −30.56% | −42.64% |
| Jan–Jun 2025 | −29.66% | −6.37% | −9.58% |
| Jul–Dec 2025 | −7.03% | −7.66% | −7.89% |

Neither filter establishes a reliable improvement. Slope reduces drawdown in all three baseline-cost periods but reduces final return and has negative mean R in 2024 and late 2025. Separation worsens the 2024 loss/drawdown, although its late-2025 drawdown is smaller. The early-2025 filtered mean R is positive while net capital return is negative: equal-weight trade R and cash-dependent position P&L are different measures. Two chosen surviving coins, retrospective price filters, fractional quantities, modeled execution and short bootstrap samples remain material research limits. No parameter was retuned after these results.

Report ID: `243e7c39c4b2e483fa5f2e64009bbd1b6cff6bf2ff29cc5ff514eb2889e103bb`.

Research code hash: `627e78ca9ba1a0d2ddf7b7e1168e49cc036a9658e0f6283301fc999fcd7c14a7`.

Dataset hash: `9f66bc05f0b772985044f3444c2fca57468947233f4b459d4c78066d559f2af2`.

Original baseline and exit-study reports are preserved. The previous exit-study source tree is archived under its original code hash, just as the baseline source was preserved. The independent verifiers accept current sources or checksum-verified archived sources. Historical artifacts are never rewritten to disguise later code changes.

## Forward model

`packages/contracts/forward-paper-v2.json` freezes BTCUSDT/ETHUSDT and all three entry policies. Each policy has two independent 5,000 USDT sleeves. Costs are 5 bps fees per side, 2 bps full spread, 2 bps adverse slippage per side and 1-second modeled publication availability. These are research assumptions, not actual account commissions or fills. No leverage, liquidation, quantity/notional filters or order-book liquidity model is claimed.

Registration starts flat at the next future UTC minute. No prior setup is entered. The first possible decision is a future UTC hourly boundary. Source snapshots come from the live collector's retained SMA-seeded EMA/Wilder ATR history, with different origins from the historical replay. Exact completed confirmation and lineage/metadata guards apply before a decision.

This is a **forward shadow replay as new completed public minutes arrive**. Entry references use an eligible minute's open plus fixed modeled spread/slippage; they are not quotes executable when that completed minute is received. Plan execution, observed receipt time and evidence source are explicitly labeled. Stop-first ambiguity, adverse gaps, conservative target gaps, EMA50 exits, funding timing and censored excursions follow the tested replay model. Held operator slots in the live signal journal are separate from these modeled positions.

The public funding-history response supplies settled funding rate and associated mark. The previously published next-funding schedule is retained; a due settlement cannot be silently replaced by zero or skipped when a newer schedule appears. Missing settlement or fresh decision context waits within the observation grace, then freezes. API schemas were checked against [Binance market-data documentation](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).

A separate SQLite database commits each symbol-minute, all three policy states and their next cursors together. Exact Decimal/dataclass JSON checkpoints use a strict class whitelist, not pickle. Run, observation and checkpoint hashes are checked. The local file lock prevents a second observer. A crash cannot commit only one policy; recovery within the two-minute grace resumes exactly once. Observations outside the future window, duplicated/reordered minutes, divergent cursors, changed seeded origins, code/contracts or price filters freeze. Frozen samples retain unresolved positions and never fabricate an outage fill or closing price.

Revision checks compare the most recent observed minute against overlapping REST data; decision snapshots from the most recent 24 hourly decisions and all active/pending entry evidence are also checked. This is bounded monitoring, not indefinite revalidation of every old observation or all historical funding corrections. Distributed leases, PostgreSQL, larger-scale performance, backups, account execution and sample administration remain later work.

## What actually happened

The first v1 sample began **4 October 04:37 UTC**, observed six symbol-minutes, then froze at approximately 04:41 UTC after a real REST revision. For BTC's 04:39 minute, the early response had close `84778.00` and volume `4.502`; a later response had close `84778.10` and volume `4.725`. ETH volume also changed. Those initial observations arrived roughly two seconds after the stated minute close. No paper position opened. The original journal `services/api/forward-paper.db`, source archive and frozen sample remain preserved; the website lists the earlier sample separately.

Version 2 adds a **15-second exchange-clock settling delay** before observing a completed minute. This is data acquisition stabilization, not a change to trading thresholds or a guarantee that later revisions cannot occur. The two-minute observation grace and permanent correction freeze still apply. A fresh sample was explicitly registered after this operational fix; prior observations are excluded rather than reset or merged into its results.

Last enrolled, subsequently stopped sample ID: `0a409beda8d75fdf94c4bdd35179af2902ff123e5cf6a56b808b35a9aba870b1`. Its future window begins **4 October 2026 04:44 UTC** and ends **2 January 2027 05:00 UTC** (rounded to the final whole UTC hour). It is stored in `services/api/forward-paper-v2.db`. The first local checks observed completed minutes for both symbols with six flat sleeves, zero closed trades and 5,000 USDT each. A real observer restart preserved this sample and its cursors. Longer observation results are not yet available; the website reports current measured state rather than assuming continued service uptime.

Assessment requires at least 90 continuous calendar days and 100 closed trades **per policy**. Failure to reach either remains inconclusive. A frozen run fails continuity. Future returns, sufficiently many trades, live funding charges/position exits, uninterrupted observation and robust profitability have not been verified. No automatic winner or promotion follows even if the sample gate is reached.

## Reproduce and operate

From `services/api`, with original reports and pinned data retained:

```powershell
..\..\.venv\Scripts\python -m app.research filter-study
..\..\.venv\Scripts\python -m app.paper.worker
```

The observer requires a current verified filter report, live collector and fresh metadata for registration. It then freezes the implementation identity. Run API, collector, live signal worker, shadow observer and website as separate local processes. Keep the observer running; suspending the computer or exceeding the observation grace invalidates continuity. `--once` is a diagnostic scan, not an unattended observer. Restart uses the existing journal; it does not enroll over a frozen run. Keep both paper databases and ignored artifacts. There is no public hosting or production authentication.

From the repository root with the API/website running:

```powershell
.venv\Scripts\python tools/verify-filter-study.py
.venv\Scripts\python tools/verify-forward-paper.py
node tools/capture-filter-paper.mjs
```

The historical verifier independently checks all 2,935 trades using Fraction arithmetic, including both filter thresholds, original risk/rules, grid/fills, fees, actual funding, P&L, group sums, control parity and export/API integrity. Forward verification independently checks the actual enrollment, hashes, contiguous observed-minute chronology, settling/grace times, rational OHLC/cash reconciliation and API state. Controlled tests exercise target/stop/trend behavior, signed funding, pending/open checkpoint recovery, rollback, missing funding, observation gaps and code changes; these do not prove actual future market trades.

Research → **Entry filters** shows selectors, all 27 results, exact exports and limitations. **Forward paper** shows measured observer state, prior frozen samples, six sleeves, positions, closed trades and last-hourly equity. Light/dark/mobile actual views, native report downloads, every export hash, keyboard-accessible scroll regions and automated accessibility were checked. Product data comes from protected backend reports/journals; test fixtures never substitute for missing results.
