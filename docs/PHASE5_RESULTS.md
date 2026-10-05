# Phase 5: first historical results

Observed locally on 4 October 2026. **The fixed baseline does not establish a robust trading edge.** Development and validation lose money; the final period's small gain disappears under higher costs. Keep the application research-only. No strategy parameters were selected or modified after seeing these results.

BTCUSDT/ETHUSDT, EMA20/EMA50/SMA200/ATR14, 1H entries with exact 4H confirmation. Each row starts separately with 10,000 USDT divided equally between the two symbols. Returns include modeled fills, both-side fees and actual funding; drawdown uses hourly marked equity. See [method, source audit and limitations](PHASE5_BACKTESTING.md).

| Period | Scenario | Net return | Trades | Max drawdown | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: |
| 2024 development | Baseline | −27.68% | 243 | 30.20% | 0.703 |
| 2024 development | Higher cost | −41.97% | 248 | 42.27% | 0.574 |
| 2024 development | Delayed entry | −29.27% | 239 | 30.81% | 0.679 |
| Jan–Jun 2025 validation | Baseline | −17.91% | 145 | 20.60% | 0.712 |
| Jan–Jun 2025 validation | Higher cost | −29.66% | 148 | 31.04% | 0.570 |
| Jan–Jun 2025 validation | Delayed entry | −18.07% | 146 | 19.82% | 0.711 |
| Jul–Dec 2025 final evaluation | Baseline | +1.76% | 101 | 10.38% | 1.046 |
| Jul–Dec 2025 final evaluation | Higher cost | −7.03% | 101 | 14.80% | 0.837 |
| Jul–Dec 2025 final evaluation | Delayed entry | +0.10% | 98 | 11.38% | 1.003 |

Baseline scenarios contain 489 closed simulated trades across the three periods. All nine experiments contain 1,469 trade records, including overlapping scenarios; those records are not 1,469 independent observations. Partition returns cannot be added or compounded into one continuous account.

## Final-period detail

Baseline ending equity was 10,175.81048740413907930242010561118 USDT. Gross P&L after modeled spread/slippage was approximately +683.57 USDT; fees were 506.18 and signed funding −1.57, leaving +175.81 net. Win rate was 27.72% (28 wins, 73 losses). Mean trade R was **−0.00749**, despite positive total return: R averages give each trade equal weight, while cash results reflect different capital/risk sizes. BTC's sleeve returned +1.58%; ETH's +1.94%.

The six-month exploratory block-bootstrap interval for mean monthly return was approximately −2.52% to +1.61%. It does not establish positive expectancy. The matching cash benchmark returned 0%; the costed passive long-perpetual benchmark returned −2.88%. Outperforming that negative passive result alone is insufficient evidence of an investable strategy.

## Provenance and checks

The run pins 162 published-checksum archives, 2,370,240 audited minute rows and 4,386 actual funding events. Twenty native higher-timeframe discrepancies are preserved; canonical completed 1H/4H OHLCV is aggregated from the validated minute source. Both indicator origins are 1 October 2023 00:00 UTC. Dated October 2026 price filters approximate historical exchange rules. This source-policy amendment occurred before performance output and is disclosed in the specification and exports.

- Report ID: `0f0a77a2ec4747d1b6a228208fbd11704d30a67052777c4f7500f1f59b16cfdb`
- Dataset SHA-256: `9f66bc05f0b772985044f3444c2fca57468947233f4b459d4c78066d559f2af2`
- Strategy/research code SHA-256: `faa2ae5d9f497c38411b307862f91fd8d56378b4feccd9a1fb2c3b65f5f6211d`
- Report canonical SHA-256: `ae13ea60c2bd0d0a24ffa75f74be5296074380ebce9285df5c7d47c124e9640e`

A repeated complete replay produced identical report/export bytes. Independent rational checks passed for every trade's rules, risk rounding, modeled entry/exit, fees, actual signed funding and net P&L. The actual local API/proxy/Research page and report download matched the backend. These checks verify the implemented model and preserved data; they do not establish real fills, forward profitability or production reliability.

Results and full evidence are available in the website's **Research** tab and under `artifacts/backtests/<report-id>/`. See [verification](VERIFICATION.md) for software checks. Phase 6 is continuous paper lifecycle tracking; the broader research plan's ablations, regime analysis and walk-forward comparisons remain future work.
