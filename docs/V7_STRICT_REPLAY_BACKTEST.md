# V7Sonic — strict reproducible profitability backtest readiness

**Status:** deterministic replay implemented, historical profitability
certification *not yet achieved*. Source policy, fees, OI +20bps gate,
funding exclusion, book imbalance, taker volume, cooldown and the
four-paper-idea portfolio cap are untouched.

## Why not simply run months of OHLCV candles?

V7 depends on **contemporaneous top-20 limit order-book prices and
quantities**, spread, book impact, instantaneous open interest,
completed Binance taker buy/sell periods, funding schedule and premium
mark. Binance's public archive contains aggregated futures bookDepth
percentage bands and five-minute metrics. They do **not** contain
the exact same top-20 snapshots as a synchronized 5-endpoint REST
observation. Binance USD-M REST open-interest statistics also have a
limited recent history. Replacing the missing inputs with candles,
future-computed proxy indicators or misaligned metrics would create
a *different strategy*, not validate V7.

References:
- https://github.com/binance/binance-public-data
- https://github.com/binance/binance-public-data/issues/431
- https://github.com/binance/binance-public-data/issues/491
- https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics

## Exact original-policy journal replay

```bash
PYTHONPATH=/path/to/verified/research/worktree/services/api python3 \
 -m app.microstructure.cli \
 --db /srv/mv-v7-microstructure/data/evidence.sqlite \
 backtest --max-observations 75000
```

- Opens the existing journal **read only** and holds a single SQLite
  snapshot transaction while the collector continues writing.
- Verifies all six evidence SHA256 chains and canonical raw payloads.
- Orders historical observations by real persisted receive timestamps
  and **re-runs the frozen original classifier and original paper
  portfolio rule** in an ephemeral SQLite journal.
- Verifies the replayed original idea ledger and every 15/30/60/120m
  horizon observation exactly match the stored original.
- Reports first-failure counts, observation dates and book-touch
  reference marks after modeled fees/slippage.
- Fails closed if old reports, portfolio cap/cooldown, journal,
  evidence chain or outcome marks disagree.
- Never downloads anything, fabricates book prices, trades, modifies
  the research journal, or sends subscriber Telegram messages.
- The original model has had **zero** qualifying paper candidates
  in all VPS output observed as of 15 October 2026 (144 samples at
  last verified checkpoint); do not pre-label future results zero.

## Interpretation

`NOT_ESTIMABLE_ZERO_PAPER_IDEAS`: no qualifying trades, so sample
accuracy, expectancy, win rate, profit factor, drawdown and Sharpe
are **undefined**, not 0%. The strategy is not certified or approved
for subscriber signals.

`INCONCLUSIVE_REFERENCE_MARKS_NOT_EXECUTED_TRADES`: even when valid
paper ideas and future quotes exist, a 5-minute REST book-price point
cannot prove the path of stop/target triggers in between snapshots or
realistic order fills. Hence its mean reference net R is **not a
realized trading return** and cannot support profitability certification.

For a true historical execution backtest, procure matching,
chronologically available top-20 L2 snapshots (ideally sequence-verified
updates), contemporaneous instantaneous open interest, complete taker
volume, mark/funding history, and sufficiently granular trade/quote data
to sequence stops vs targets. Check timestamps, timestamp conventions,
snapshot availability and exchange data quality; do not silently
backfill these missing features with hindsight. Define frozen fee tiers,
trade sizes, slippage and funding payments; replay symbol overlap,
cooldowns and real trade lifecycle; split chronologically independent
development and held-out periods, report uncertainty, missing data
and drawdowns. Do not promote V7Sonic to production based on this
read-only replay alone.

## Future formal gates

The strict replay is a **necessary integrity check** but *not* a
sufficient evidence gate for profitability. The current certification
fields require real fill/stop/target/funding evidence and an independent
holdout; neither is currently available. Do not reinterpret a passing
CI test as passing trading profitability validation.
