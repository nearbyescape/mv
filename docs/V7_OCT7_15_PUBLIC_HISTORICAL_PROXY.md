# October 7–15, 2026 IST: strict V7 coverage and separate historical proxy

The operator's certified live research journal only starts at
**2026-10-15 05:56:29 UTC**, with 162 total observations at the last
replayed snapshot; therefore the original top-20 book V7 classifier
**cannot be backtested for 7–14 October using that journal**.
Earlier historical data must not be invented.

## Public-data facts

Binance provides five-minute USD-M futures open-interest statistics
(`/futures/data/openInterestHist`, one-month lookback), taker volume
statistics (`/futures/data/takerlongshortRatio`) and 5m perpetual
klines. Historical settled funding is `/fapi/v1/fundingRate`.
These are public endpoints and do not require an API key.

This **does not reconstruct original V7**: top-20 visible order-book
levels, spread, market-impact and REST snapshot consistency are
missing. Binance's published `bookDepth` archive offers aggregated
price-distance bands, not true top-20 L2 snapshots, and a public
issue reports incomplete **BTCUSDT Oct 7 and Oct 9 archives**.
Issue: https://github.com/binance/binance-public-data/issues/512

## Historical-pagination hardening

On the October 15 VPS attempt, Binance historical acquisition stopped
before creating a results report with `Historical pagination did not advance`.
The original collector used `last_timestamp + 1` as the next query
`startTime`. Public 5-minute aggregated statistics may interpret
`startTime` on period boundaries and repeat a completed bucket rather
than advancing. This is not a trade failure or evidence of profitability.

The revised downloader uses **nonoverlapping maximum 24-hour UTC
query slices**: at most 288 distinct 5-minute bucket timestamps and
a request cap of 500 per OI/taker window or 1,500 per kline window.
It never relies on a page cursor, never backfills absent periods,
rejects conflicting duplicate timestamps, and raises a diagnostic
`HISTORY_OUTSIDE_REQUESTED_SEGMENT` including symbol, source family,
requested UTC bounds and provider response range if a provider
returns exclusively out-of-window data. Missing points remain
missing; the final report includes per-day coverage diagnostics.

The earlier failed run produced **no profitability result**.
The source/collector checkout on the VPS must remain untouched;
install the pinned research update in a separate detached worktree.

## Explicitly different, partial-rule historical test

Run in a separate detached Git worktree, with NO production compose,
exchange credentials, client Telegram or live journal writes:

```bash
PYTHONPATH=/path/to/pinned/worktree/services/api \
  python3 -m app.microstructure.oct_history_proxy \
  --allow-public-history --confirm-proxy-not-v7 \
  --output-dir /srv/mv-v7-historical-proxy/oct7-15-2026
```

What is frozen for this proxy:

- Six V7 markets: BTC, ETH, SOL, XRP, DOGE, BNB USDT futures.
- Request local-day boundaries 7 Oct 00:00 IST through 15 Oct
  23:59:59 IST, but **truncate at current UTC five-minute boundary**
  so there is no future data. UTC start is 6 Oct 18:30.
- Fixed-source public Binance endpoints only. HTTP 418/429/451
  immediately stop; no alternate hosts or proxies.
- Store SHA256-manifested raw public JSON observations for replay.
  Validate pagination, timestamps and cache integrity. Fail closed
  if a required source returns no data; never impute missing metrics.
- As-of, one-bar-aged 5m OI and taker period end timestamps to reduce
  look-ahead risks. Actual publication latency cannot be verified;
  enter on the **following** 5m bar OPEN for further conservatism.
- Keep original +0.20%..+5% OI change, 1.25 LONG / 0.80 SHORT
  taker volume thresholds, IST 09:00–23:00 session, 3-hour same
  symbol cooldown, max 4 reference slots over 120m, 0.75% stop
  and 1.8R target, modeled 8bps per side fees/slippage.
- No unavailable L2 book imbalance or execution impact gate; this
  is an **incomplete, more permissive strategy than V7**.
  The original 120m pre-funding exclusion also cannot be
  reconstructed exactly; instead charge historical realized
  funding rates to positions crossing archived events.
- Simulate 24 consecutive 5m bars after entry; stop/target touched
  in same candle is a STOP, including price gaps through a stop;
  otherwise exit at 120m; missing futures are right-censored.
- Outcomes are approximations from trade-price candles, not
  proven executable fills. Report descriptive net-R, positive
  net fraction, profit factor, max drawdown and daily/symbol
  breakdown at modeled 0.5% risk. No automatic deployment.

## Interpret the results carefully

A profitable or unprofitable **proxy** does not prove the original
V7's profitability because the book filters and funding guard
are not reproduced. The 7–15 Oct window contains only ~8.5
completed days as of 15 Oct afternoon in IST, not a robust
independent holdout. Multiple overlapping trades are not
independent observations. A no-trade result means that profitability
is undefined, not zero.

An exact V7 historical backtest requires timestamp-correct
archived top-20 L2 books, instantaneous OI and reliable taker
publication timestamps plus mark price, funding schedule and
sequenced trade/stop/target fills. This version NEVER generates
fabricated inputs to satisfy that requirement.

Source docs:
https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics
https://github.com/binance/binance-public-data
