# V7Sonic signal-only recovery: code change and release contract

**Status: PAPER RESEARCH ONLY. NO LIVE PUBLISHING OR TRADE EXECUTION.**

## What this branch actually changes

- Adds a separate `V7SONIC_REGIME_15M_RESEARCH_CHALLENGER_V1` policy. It does not change the original V7 candidate algorithm or its historical results.
- Uses completed 1m/5m/15m/1h/4h candles, the existing verified quote contract, and a symmetric 15m/1h re-entry hypothesis. Four-hour strong opposition vetoes; ordinary mixed 4h observations do not automatically suppress every setup.
- Sizes **reference stop distance**, not position quantity, from 15m ATR and completed 5m structure. Stops too wide, poor bid/ask conditions and unfavorable after-cost R remain hard rejections.
- Models an alternative 50/50 exit (1.25R, 2.75R), 4 bps per-side taker fees and 4 bps per-side slippage. It retains the **1.25 net R hurdle** instead of suppressing trading costs or turning weak reference setups into signals.
- Keeps a completely separate policy identity. It cannot enter the original paper ledger, send Telegram, start services, write production data, or place orders.
- Includes an offline certified-source comparison: all four five-minute cycles and 24 decisions per run are reaudited before the baseline and challenger are evaluated from the same ORIGINAL bytes.
- Regression tests cover valid LONG geometry, candidate non-publication, short geometry, stale and malformed market evidence, and duplicate/invalid locks.

The eight completed V7 cycles on 14 October and their 48 market decisions remain **development data**, not independent validation. Any comparison from them is explanatory, **not** a forward estimate of expected returns.

## Why previous work was blocked

The original V7 six-expert strategy produced 38 no-expert decisions and 10 after-cost-reward rejections across these 48 observations. The original 0.9 x five-minute ATR minimum stop and 1R/2.5R 50/50 target structure exposed the signal to considerable fee/slippage costs when volatility was low. The challenger investigates a longer stop/target horizon with separate exposure sizing. Widening stops alone does not improve expected P&L; it can worsen losses. **No accuracy improvement is claimed.**

## Architecture correction: public Telegram ideas are not account trading

MV currently sends informational ideas to a subscriber Telegram channel; **the software is not placing exchange orders on subscribers' accounts**. An authenticated Binance account balance **cannot** attest every subscriber's exposure. Do not make a connected exchange account a prerequisite for publishing purely informational signals.

A production *signal-only* authorization path would instead require:

1. Verified fresh/complete original market source and bounded decision latency.
2. Frozen policy release ID, threshold/cost assumptions and independently accepted prospective evaluation.
3. Trusted release signer and separate reviewed publication approval with exact channel/destination/decision digest and short expiry.
4. Global signal-idea exposure constraints (e.g. no duplicate symbol, maximum four overlapping active ideas) stated as an informational reference portfolio, **never** falsely claimed to be each subscriber's actual portfolio.
5. Fail-closed dispatch: durable claim before Telegram POST; unknown receipt is reconciled manually and never auto-retried; operator pause, monitoring, gap escalation, real private-channel fault tests and rollback.
6. Visible disclaimer: levels/0.5%-risk are illustrative; users must size positions using their own accounts, leverage, spreads, fees, funding and tolerances.

If actual broker order routing is later added, authenticated account/positions/orders/margin and exchange-trading permissions become separately mandatory. The signal-only path must **not** reuse a manual `OPERATOR_RECONCILED_UNATTESTED` snapshot as if it were exchange-certified.

**Important:** This document corrects the design requirement. This branch DOES NOT implement, authorize or deploy the production certificate issuer, order routing or client publisher.

## Decision to promote challenger

Require a separate genuinely prospective, timestamped, cost/slippage-adjusted observation cohort (with all no-setup and missing-source boundaries retained), clustered uncertainty, adverse excursions, entry executability, trade-idea overlap, and frozen acceptance criteria. Do not optimize on the observed 48 decisions then call their outcomes out-of-sample.

No changes to `/opt/mv-signal/app`, V4 services, Telegram sender, live PostgreSQL, legacy positions or any API credentials are part of this branch.
