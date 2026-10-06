# MV-TREND-DUAL-v4

Release candidate: **0.14.0**  
Strategy ID: **MV-TREND-DUAL-v4**  
Risk policy: **RISK-ATR14-SCALED-TP-v4**

V4 preserves V3 setup selection, anti-chase limits, two-ATR initial stop and
TP1/TP2/TP3 reference geometry. It adds a fail-closed market-safety governor
after the V3 setup qualifies and before publication. V3 history remains
immutable and separately queryable. MV still places no exchange orders.

## Publication pipeline

A candidate must pass, in order:

1. V3 completed 1H setup and exact completed 4H confirmation.
2. Existing BTC 1H/4H contradiction veto for altcoins.
3. Completed BTC 15-minute timing veto.
4. V3 source/live anti-chase and same-symbol same-direction IST-session guard.
5. Directional deterioration circuit breaker.
6. Same-direction source-close concentration cap.
7. Existing active-slot, quote freshness, spread, price-filter and live-entry checks.

No signal is a valid output. A safety rejection never creates a replacement
trade in the opposite direction.

## BTC 15-minute timing veto

BTC 15-minute candles are collected only for BTCUSDT and only completed candles
are persisted. The latest completed 15-minute candle immediately preceding the
1H source-close boundary and its previous 15-minute snapshot are used.

For LONG publication:

- BTC close > EMA20 > EMA50.
- EMA20 is non-declining versus the previous completed 15-minute snapshot.

For SHORT publication the comparisons are reversed. Missing, stale or
insufficient BTC 15-minute evidence fails closed and the decision remains
pending within its normal five-minute entry window. A valid but conflicting
snapshot rejects the candidate as `BTC_15M_TIMING_CONFLICT`.

The 15-minute layer is a veto only. It cannot originate a signal or change the
1H/4H signal direction.

## Safety analytics freshness

The directional circuit breaker depends on persisted completed-1m outcome
milestones. Publication therefore fails closed when the `outcome-analytics`
worker heartbeat is missing or older than **45 seconds**. The decision remains
pending inside its normal entry window and may proceed only after the safety
analytics worker becomes current again. The web feed reports this condition as
a degraded **Market Safety Mode** rather than presenting the system as normal.

## Directional concentration

At most **two V4 signals in the same direction** may be published for one exact
1H source close. Candidates are processed deterministically by:

1. lower preceding-six-hour directional run in ATR,
2. lower source extension from EMA20 in ATR,
3. established regime before emerging,
4. symbol as the final stable tie-break.

Later same-direction candidates are rejected as
`MARKET_DIRECTION_CONCENTRATION_LIMIT`. LONG and SHORT limits are independent.

## Directional circuit breaker

V4 reference outcomes continue to be measured from completed Binance 1-minute
candles. For the circuit breaker only, a signal is considered deteriorated when
it reaches **-0.5R before +0.5R**.

If two V4 signals whose publications formed a 120-minute cluster deteriorate in
the same direction, that direction is paused for **120 minutes from the later
-0.5R event**. The pause remains active for the full 120 minutes even after an
older signal leaves the rolling publication window. If +0.5R and -0.5R first
appear in the same completed 1-minute candle, ordering is unknowable and the
safety governor treats that candle conservatively as adverse-first. The
opposite direction remains eligible.

New candidates in the paused direction are rejected as
`DIRECTIONAL_CIRCUIT_BREAKER`. Already published plans remain immutable, but
their `entry_actionable` state becomes false while the corresponding
direction is paused.

This use of outcome milestones is deliberately narrow: the signal engine reads
only persisted timing milestones required for the safety circuit breaker. The
analytics worker still cannot create or alter signal decisions or plans.

## Retrospective validation gate

Before V4 is eligible for production, the candidate includes a read-only
retrospective command:

`python -m app.research.v4_retrospective --ist-date YYYY-MM-DD`

The command opens the production database transaction read-only, re-evaluates
historical V2 publications through the V4 setup and entry constraints, fetches
only public historical BTCUSDT 15-minute candles for the timing veto, and
simulates same-session dedupe, deterministic concentration ranking and the
directional circuit breaker. It writes no MV tables and cannot publish signals.

For 6 October 2026 the intended gate is to compare the actual 20 V2
publications with the exact set V4 would have allowed. The result is diagnostic
evidence for the safety patch; it is not a backtest, profitability estimate or
proof that future reversals will be avoided.

## Client surfaces

The signal feed exposes the current market-safety state. When a directional
circuit breaker is active, the web signal workspace displays **Market Safety
Mode** and identifies the paused direction. Ordinary vetoes and concentration
rejections remain visible in the evaluation log using their explicit reason
codes.

## Unchanged V3 risk management

- Initial stop: 2 frozen ATR.
- TP1: +1R, 30%.
- TP2: +1.5R, 30%.
- TP3: +2R, 40%.
- After TP1, remaining reference stop moves to entry.
- After TP2, remaining reference stop moves to TP1.
- Tick rounding remains conservative.
- Reference plans only; no exchange execution or fill claims.

V4 is a targeted safety revision motivated by observed correlated signal
clustering. It is not evidence of profitability or a guarantee against future
market reversals.
