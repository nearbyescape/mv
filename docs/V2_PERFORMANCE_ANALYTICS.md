# MV V2 Performance Analytics

## Purpose

Release 0.12.0 adds an observational analytics subsystem for `MV-TREND-DUAL-v2`.
It measures what happens after the engine publishes a signal and what the market
does after a `NO_SETUP` decision. It does not participate in signal creation,
ranking, suppression, quote validation, Telegram delivery or operator slots.

The live V2 financial contract is unchanged.

## Isolation

The subsystem has its own:

- PostgreSQL tables: `signal_outcomes` and `decision_opportunities`;
- worker process: `app.analytics.worker`;
- database singleton/lease: `outcome-analytics`;
- API namespace: `/v1/analytics/*`;
- web navigation page: **Performance**.

The signal worker does not import the analytics package. If analytics is stopped,
rate-limited or unavailable, the live signal engine continues normally.

## Published-signal reference outcomes

A `signal_outcomes` row is created only from an immutable published V2
`SignalPlan`. It copies:

- signal ID, symbol and direction;
- setup family and trend regime;
- publication time;
- entry, stop, target and exact published reward/risk;
- frozen ATR and risk distance.

These are reference-plan measurements. They are not exchange fills, positions,
realized P&L or account returns.

### Observation start

The minute containing publication may include price movement that occurred before
the signal existed. Analytics therefore starts with the first full Binance USD-M
1-minute candle whose open is at or after publication. No pre-publication portion
of a minute is used.

Only completed 1-minute candles are processed.

### R excursions

For each completed observation minute, analytics updates:

- maximum favorable excursion (MFE) in R;
- maximum adverse excursion (MAE) in R;
- first observed +0.5R;
- first observed +1.0R;
- first observed +1.5R;
- first observed +2.0R;
- first observed -0.5R;
- first observed -1.0R.

The stored timestamps identify the completed minute containing the threshold
touch. Intraminute tick ordering is not claimed.

### Terminal classification

Reference outcome states are:

- `open`;
- `target`;
- `stop`;
- `ambiguous`;
- `source_revised`.

If both stop and target are touched inside the same completed 1-minute candle,
the order is unknowable from OHLCV. The row is labeled `ambiguous` and its
conservative reference result is stored as -1R. It is never silently counted as
a win.

A source revision terminates an outcome that is still open. If the reference
outcome was already terminal, its result remains immutable and the
`source_revised` flag is added.

## Exchange request bounds

The analytics worker groups unresolved outcomes by symbol. It requests minute
history once per symbol/cycle from the oldest needed cursor, rather than once per
signal. Request fan-out is therefore bounded by the selected market universe,
not by the number of unresolved historical signals.

Fetch errors are recorded only on analytics rows and never propagated into the
signal engine.

## Six-hour NO_SETUP diagnostics

For every V2 `NO_SETUP` decision whose completed source close and ATR are
available, `decision_opportunities` measures the following six completed 1-hour
candles.

It records:

- maximum price rise from source close divided by frozen source ATR;
- maximum price fall from source close divided by frozen source ATR;
- the blocking reason;
- optional directional context;
- whether the six-hour window is complete.

This is deliberately not converted into a hypothetical trade or P&L. There was
no published entry, quote or frozen execution plan for a rejected setup.

The Performance page aggregates these windows by rejection reason to identify
rules that may be excluding large subsequent moves.

## Performance views

The dedicated **Performance** page contains:

1. overall V2 reference outcome statistics;
2. Pullback LONG;
3. Pullback SHORT;
4. Breakout LONG;
5. Breakout SHORT;
6. per-symbol reference statistics;
7. decision blocker counts;
8. six-hour missed-move diagnostics;
9. recent outcome rows and CSV export.

Nothing from this subsystem is shown on the main Overview dashboard.

## Conservative statistics

Resolved reference expectancy and profit factor use:

- target: exact published target R;
- stop: -1R;
- ambiguous same-minute target/stop: -1R;
- open and source-revised outcomes: excluded from resolved expectancy.

`+1R before stop` and `+2R before stop` require the favorable threshold's
completed-minute timestamp to be strictly earlier than the -1R timestamp. A
same-minute touch of both does not count as favorable-first.

These are descriptive reference statistics before actual trading fees, fill
slippage, position sizing and operator execution.

## Review milestones

The interface marks the next evidence milestone at 25, 50, 100, 200 and 300
published V2 signals. These milestones do not automatically modify strategy
rules. Any later strategy change requires a separate versioned decision and
validation process.
