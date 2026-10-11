# V6HBR — Market-Aware Hybrid Research Architecture (v0.1)

**Status: research/design only.** This is a prospective architecture, **not** a model claiming 80% accuracy, approval to merge, authorization to resume V4, or authorization to publish signals/orders. Live V4 signal generation and automatic Telegram/report/AI workers were confirmed stopped by the VPS operator. Market collection, database, analytics, website and research remain running. Never start or recreate the V4 engine during research. Existing live code and production artifacts are immutable unless the operator explicitly authorizes a separately audited cutover.

## Why the previous approach failed

The April–May six-market directional study had 352 *historical rule-qualified candidate references* (not actual Telegram alerts or futures fills): 143 correct, 115 wrong, 94 neutral at a 60-minute closing ±10-bps classification. Restrictive fixed after-the-fact masks gave only 40–48% correctness; the top 47.67% long-only mask discarded 51 correct references. An early-April trained, late-April intercept-calibrated seven-feature logistic "correct probability" model scored 191 May references at 37.70% correctness, AUROC 0.51237, no predicted probabilities ≥0.60, and Brier 0.235975 vs **better** late-April-only smoothed constant 0.235255. The model has no demonstrated *discrimination*. More filters cannot create missing predictive information.

## Mission and hard constraints

Build a *hierarchical, multi-horizon, context-aware, multi-strategy, inspectable* model that approaches decisions an experienced discretionary futures trader would make without claiming to replicate human intuition or "see every move."

- Aspirational acceptance: **≥80% correct over all emitted, objectively matured 60-minute directional forecasts**, with neutral counted as noncorrect. This is **not guaranteed**. Set minimum daily/weekly signal coverage and positive execution-adjusted expected R **before** independent validation. Accuracy alone is not trading profitability; high hit rates can coexist with negative expected return.
- **No signal starvation:** candidate generation must be independently measured vs V4/V5, by symbol/session/regime. More candidate *opportunities*, not mandatory trades. If no independently tested positive expected value setup occurs, the correct decision is no-trade. Do not mask no-trade as an 80%-accurate result.
- No future bar, future book update, post-signal liquidation, later news, revised source, settlement, outcome, future market breadth, or next open may influence the original decision. Keep timestamp + exchange available_at + source digest per input.
- Never train against already-inspected validation labels and claim success. Apr–May is now development/debug; June–July fixed independent validation remains unused; Aug–Sep is sealed one-time holdout after final frozen choice.
- No exchange keys, trade placement, leverage automation, live strategy patch, unbounded external AI spend, main merge, or Telegram sending within the research branch. Keep 2 CPU / 8 GB VPS in mind; CPU- and storage-budget full tick/order-book ingestion, test bounded workloads.

## Senior discretionary trader analogy → measurable machine questions

| Trader's observation | Quantitative, auditable representation | Time horizon |
| --- | --- | --- |
| "Is the market trending, ranging, or chaotic?" | trend strength/persistence, volatility percentile, realized variance, trend-vs-range regime, structural highs/lows, change-point indicators | 4h/1h/15m |
| "Are Bitcoin and the major coins supporting this move?" | BTC/ETH signed returns, leader/laggard peer-relative return, signed breadth (% of 30 with positive returns), common shock risk, dispersion, pair correlation; matched **as-of** boundaries only | 1h/15m |
| "Where might stops/liquidity be clustered?" | prior session high/low, recent local swing highs/lows, tested support/resistance, liquidity sweep-and-reclaim; **inferred zones not observable stop orders** | 1h/15m/5m |
| "Are aggressors pushing through or being absorbed?" | signed aggressor trade-volume delta from published aggregate trades; level-1/5/10 book imbalance; quote replenishment vs depletion; microprice; *only if proper venue feed and reconstructed book are available* | 1–60s/1m/5m |
| "Is the move exhausted / already extended?" | return/ATR, momentum acceleration/deceleration, volume anomaly, realized-volatility break, failed breakouts, cumulative delta divergence | 1m/5m/15m |
| "What is positioning/crowding?" | funding/premium, open interest *changes when actually available*, liquidation prints (sampled/incomplete), basis; source availability and historical retention disclosed | 5m/1h/4h |
| "What are the competing scenarios?" | per-setup: continuation/breakout/reversal thesis, explicit invalidation, possible path via limit/stop/timeout, expected outcome distribution | 5m/15m/1h |
| "Are trade costs and correlations acceptable?" | actual venue bid/ask/depth, min fills, slippage/latency, fees, funding, exposure overlap and risk budget | last fresh quote |

**Live capture is NOT retrospective historical coverage:** the inherited production collector fetches 15m BTC only and 1h/4h for other symbols. The separate historical V6HBR archive covers Jan–May 15m/1h/4h for six symbols and lacks complete historical order-book queues. For a genuine hybrid, acquire extra *as-of* historical trade tape/1m candles and prospectively log depth/order flow in an independent, consented research collector; *never fabricate order-book history from OHLCV*. Binance public monthly USD-M futures klines/aggTrades and price/mark/premium references are documented. Binance's /futures/data/openInterestHist limits history to the latest month: do not expect it to backfill April/May 2026 from Oct 2026.

## Research architecture

1. **Read-only acquisition and provenance.** Versioned source manifests; canonical timestamps, UTC exchange publication vs local arrival, snapshot hashes. Full 30 market coverage explicitly counted; missing/stale data fail *global context readiness*, not replaced by zero features. Verify synchronized higher timeframes as-of event. Use network access only for bounded isolated acquisition. Keep the live collector untouched.
2. **Market-context encoder / breadth state.** Derive the 30-market synchronized 15m/1h/4h snapshot at every decision boundary; trend vote, volatility regime, leader/breadth, market shock vs idiosyncratic move and context lineage. Store features with eligible publish timestamp. A partial-six-market result may be marked **SMOKE_ONLY**, never a healthy all-market regime.
3. **Opportunity-generating experts**, each with independent discovery, not exclusion of every previous V4 signal: (a) trend pullback/continuation, (b) breakout + acceptance/retest, (c) sweep/reclaim reversal, (d) range mean reversion at range edges, (e) momentum expansion and failed breakout. Each must be compared against a null/opportunity baseline; none is predeclared profitable. No stale/noisy intrabar trigger is allowed to look into the future.
4. **Contextual expert router.** Interpret market regime and **allow multiple lanes** per market; do not globally reject opposing set-ups just because BTC's sign differs. Return per-candidate market-state, scenario, invalidation, evidence age, conflict notes; an untrusted AI verbal explanation cannot change hard risk rules or invent source data.
5. **Probability/path evaluator.** Predict probability of signed 60m move exceeding modeled costs **and** first adverse/favorable ATR excursion and signed expected R. Use simple regularized logistic/gradient boosting first, compare to constant prevalence, directional baseline and unfiltered candidates. Try multi-timeframe sequence models (e.g. Kronos embeddings or small temporal models) only after matched-sample incremental gain. Model probability is NOT forecast accuracy. Calibrate by regime/side only when statistical sample sizes justify it.
6. **Decision and risk arbitration.** Rank by estimated after-cost expected value, probability of hitting stop before a favorable excursion, execution price slippage, and correlation-aware capacity. Use a monotone risk budget and hard safety vetoes (no quote, stale feed, unavailable contract, extreme spread, unbounded loss). Abstention counts are visible. Avoid converting model scores into arbitrary "80% confidence" thresholds.
7. **Event-driven evaluation:** update higher-timeframe context at 1h/4h close, scan all watched markets on bounded 5m (or 1m when supported) completed bars; activate research-only microstructure checks for shortlisted setups. Do not spin expensive LLM inference at 100ms per asset. Respect 2 CPU/8 GB RAM with measured p95 per cycle and an explicit abort on backlog.
8. **Measured learning loop.** Save every candidate, discarded candidate, model action/reason, timestamp/source hash, and outcomes separately. Never retrain from post-cutoff future observations or change thresholds on the same held-out period.

### Coherent opportunity vs signal-count contract

Measure at every level: market × timeframe × session × regime → *triggered opportunity count* → *eligible cost-aware candidate count* → *final published signal count* → *matured mark accuracy* → *fillable trade rate* → *after-fees funding net R*. Publish daily signal frequency and missed-good-opportunity rate beside hit rate. **No default numerical signal quota** is presently justified; compare candidate coverage with frozen V4/V5 and declare acceptable frequency *before* testing held-out periods.

Separate short-lived 5–15m setups from 60–120m continuation signals. An intrabar order-book forecast is not a 60-minute directional win unless explicitly tested. A 5m reversal lane should not inherit 1h continuation labels blindly.

### Quantitative scoring and acceptance

1. Baseline: V4/V5 source-qualified candidate stream all included; raw six-market April–May correctness 143/352 = 40.62%. Unresolved at cutoff are censored; neutral counts as noncorrect.
2. Chronological samples: event maturation before model split, cross-symbol same-timestamp joint embargo, purged overlapping outcomes, day-blocked resampling; no cross-market same-minute leakage. Non-overlapping training/calibration/validation dates.
3. Report probability calibration, AUROC/AUPRC and profit-weighted skill against **late-period prevalence-only**, plus all-candidate accuracy, accuracy at *precommitted* minimum coverage, average net R and tail drawdown. Correct trades rejected and no-setup near-misses are explicit.
4. Fixed 30-market scope needs validated official data for *every required instrument/timeframe*; missing listing/contract intervals are documented coverage failures, not quietly removed.
5. Before June–July validation, **freeze** feature definitions, data freshness contract, candidate families, candidate-selection and pre-registered comparisons. Validation dates remain unexamined until then. Holdout Aug–Sep **one-shot** only. Final paper live forward trial with documented spreads/depth/funding and meaningful volume before any live promotion.
6. **No deployment unless** independent evidence shows at least a robust positive after-cost expectancy, acceptable drawdown/exposure/latency, meaningful daily signal coverage and credible 80%-target results. If the target cannot be reached without starving signals, report the failure and renegotiate scientific feasibility; never report invented 80%.

## Source availability research (checked Oct 11, 2026)

- Binance USD-M futures official: https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly (reconstruct depth by buffering stream + REST snapshot, strict sequence/re-sync).
- Binance official public downloadable historical data: https://github.com/binance/binance-public-data/ (futures klines and aggTrades; monthly SHA checksums; do not assume complete historic L2).
- Binance REST futures endpoints: https://developers.binance.info/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data (open-interest historical latest month).
- Cont, Kukanov, Stoikov, *The Price Impact of Order Book Events* (2014): https://arxiv.org/abs/1011.6402 ; short-horizon order-flow imbalance and liquidity depth.
- Kolm, Turiel, Westray, *Deep order flow imbalance* (2023): https://onlinelibrary.wiley.com/doi/10.1111/mafi.12413 ; microstructure prediction horizon caveats (equities evidence, not our crypto returns).
- Zhang, Zohren, Roberts, *DeepLOB* (2018): https://arxiv.org/abs/1808.03668 ; no direct transferable crypto trading accuracy claim.
- Shi et al, *Kronos* (2025): https://arxiv.org/abs/2508.02739 ; OHLCV foundation-model representations, benchmark gains not identical to live fills or model fit.
- Larry Harris, *Trading and Exchanges: Market Microstructure for Practitioners* (OUP 2002): https://academic.oup.com/book/52292
- Marcos López de Prado, *Advances in Financial Machine Learning* (Wiley 2018): event-driven labeling, triple barriers, overlapping sample weights, purging.
- Bailey & López de Prado, *Deflated Sharpe Ratio* (2014): https://doi.org/10.3905/jpm.2014.40.5.094 ; caution overfit among many tried policies.

## Deliverable order (separate research PR commits, never live)

- **R0** frozen architecture + causal snapshot contract and synthetic tests.
- **R1** historical feature provenance audit and complete 30-market 15m/1h/4h historical coverage (currently six markets).
- **R2** offline 1m and aggTrade source research and optional prospective order-book tape recorder; storage/CPU limits and independent checksums.
- **R3** candidate multi-family research generator with invariant candidate accounting; compare to V4/V5 and absence baselines.
- **R4** regime encoder and probabilistic event/path model using only as-of fields, proper chronological CV and baseline comparisons.
- **R5** after-cost execution model, cross-sectional and time-series validation, frozen June–July and one-shot August–September holdout; paper run.
- **R6** only after passed gates and explicit operator signoff: design *new* versioned V6HBR production service and deliberate cutover. V4 suspended until then; never silently reactivate.
