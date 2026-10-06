# MV Strategy V2 — direct production signal engine

## Status

Release 0.11.0 introduces `MV-TREND-DUAL-v2` as the candidate live financial
strategy. It is a deterministic signal engine, not a shadow or paper strategy.
The existing V1 implementation and its historical research artifacts remain
unchanged for reproducibility. Deployment is a separate controlled cutover and
must occur only after the 0.11.0 regression suite passes.

Implementation does **not** establish profitability or improved accuracy. V1's
historical results remain the evidence available before V2 deployment.

## Why V2 exists

V1 can only originate a short after a completed 1H candle has first closed at or
above its EMA20 and the next completed 1H candle closes back below EMA20. During
a continuous selloff price can remain below EMA20 for many hours, so V1 can
correctly identify a bearish trend while never producing a short trigger.

V2 keeps a quality-controlled pullback continuation and adds a separate
structural momentum breakout. Long and short logic are mirrored.

## Indicators and source discipline

V2 keeps the existing source/indicator pipeline:

- completed Binance USD-M perpetual 1H source candles;
- exact completed 4H confirmation selected from the 1H close boundary;
- EMA20, EMA50, SMA200 and Wilder ATR14;
- 34-digit Decimal arithmetic;
- 500 completed bars required on each timeframe;
- retained source hashes, indicator lineage and checkpoint validation;
- no unfinished-candle entry decisions.

The breakout structure uses the immediately preceding 12 completed 1H
snapshots. Those snapshots become immutable signal evidence and participate in
post-publication source-revision checks.

## Trend regimes

Every setup first needs a directional 1H regime and a matching completed 4H
regime.

### Established

Long:

- 1H EMA20 > EMA50 > SMA200;
- completed 4H EMA20 > EMA50 > SMA200;
- completed 4H close > EMA20.

Short mirrors the inequalities.

### Emerging

Long:

- 1H EMA20 > EMA50;
- 1H EMA50 is rising versus the previous completed 1H EMA50;
- 1H close is above SMA200;
- completed 4H EMA20 > EMA50;
- completed 4H close > EMA20.

Short mirrors the conditions. The purpose is to avoid waiting for the slow
SMA200 ordering after a directional transition while still requiring price,
slope and 4H confirmation.

Published evidence contains only the checks required by the selected regime.

## Setup A — pullback continuation

After a qualified trend regime, V2 may publish a pullback continuation when all
of the following pass:

- previous close reaches the EMA20 pullback side;
- previous EMA20 depth is no more than 0.75 ATR;
- current close reclaims/loses EMA20 by at least 0.10 ATR;
- source candle body is at least 0.20 ATR;
- source candle body agrees with direction;
- directional close location is at least 60% of the candle range;
- source close is beyond EMA20 but no more than 1.25 ATR from it.

At publication the live reference entry may drift no more than 0.50 ATR from
source close and no more than 1.50 ATR from EMA20 in the signal direction.

## Setup B — momentum breakout

A momentum breakout does **not** require the previous candle to cross back over
EMA20. This is the direct fix for sustained bull/bear moves that V1 can miss.

Long requires the completed source close to exceed the highest high of the
previous 12 completed 1H candles by at least 0.05 ATR. Short requires a close
below the corresponding 12-bar lowest low by at least 0.05 ATR.

It also requires:

- directional candle body at least 0.35 ATR;
- directional close location at least 70% of candle range;
- source close no more than 1.75 ATR from EMA20.

At publication the reference entry may drift no more than 0.75 ATR from source
close and no more than 2.00 ATR from EMA20 in the signal direction.

When one completed candle satisfies both setup families, momentum breakout has
deterministic precedence so only one signal is created.

## BTC contradiction veto for altcoins

BTCUSDT itself has no cross-market veto.

For every other selected symbol V2 reads BTC's same completed 1H source and
exact completed 4H confirmation. It rejects:

- an alt long when BTC 1H and 4H are both strongly bearish;
- an alt short when BTC 1H and 4H are both strongly bullish.

Mixed or neutral BTC does not block an alt setup. BTC snapshots are persisted in
the alt signal's evidence, included in the pre/post-quote fingerprint and
monitored for source revision.

## Quote and execution-quality guards

V2 keeps the existing five-second quote freshness requirement and five-minute
entry window. It additionally rejects a publication when current bid/ask spread
exceeds 10 basis points of midpoint.

The quote must still have positive bid/ask quantities, valid exchange tick
alignment, correct symbol, nonfuture timing and the correct EMA20 side.

## Frozen reference risk

Release 0.11.0 deliberately keeps the existing plan geometry:

- initial stop: 2 × frozen source ATR14, rounded outward to exchange tick;
- target: 2R from the rounded reference risk;
- no partial exits;
- no trailing stop;
- no automatic order execution.

This is a signal/reference-plan application. Operator `held` state does not
prove an exchange fill. Breakeven, partial-profit or trailing management cannot
be implemented truthfully without a reliable fill/position lifecycle.

## Session and operational behavior

V2 preserves the registered 09:00 AM–11:00 PM IST signal session. Market
collection and source-integrity monitoring continue around the clock. An
off-session completed source is terminally skipped and is not replayed later.

The existing web notification, AI commentary and Telegram workers consume the
same immutable published-plan/event model. Telegram labels whether the signal
is a pullback continuation or momentum breakout.

## V1 to V2 cutover semantics

V2 has a distinct strategy ID and decision identity. On its first production
start:

1. each selected symbol waits for live/warmed/current 1H and exact 4H heads;
2. V2 creates a cursor at the current completed 1H head;
3. V2 records a startup `BASELINE` decision;
4. no already-completed V1/V2 history becomes a new entry;
5. the first possible V2 opportunity is a later completed eligible 1H candle.

Old V1 plans, events and journal history remain readable.

Slot publication checks every strategy for the same symbol. A retained V1 held
or reserved slot therefore blocks a V2 publication for that coin.

The V2 worker selects only V2 pending decisions, so stale V1 pending rows cannot
be consumed by the new engine.

## Integrity and failure behavior

Publication remains two-phase:

1. exact source/setup/metadata/BTC context is persisted and hashed;
2. public quote is fetched outside the transaction;
3. source, setup, BTC regime and metadata are re-read;
4. any change causes retry rather than publication;
5. final plan/evidence/slot/event commit is atomic.

Published V2 evidence includes source, previous, 12 structure snapshots,
completed 4H confirmation, BTC regime where applicable, quote, guards, setup
type and trend regime. Source revisions withdraw reserved opportunities without
rewriting the original plan.

## Explicit limits

V2 was created in response to known V1 structural blind spots. Its implementation
must not be described as proof of improved profitability, win rate or future
returns. Direct production use is a user operational choice, not research
validation. Historical V1 BTC/ETH research remains negative/fragile and does not
validate V2 or the 29-coin universe.

No exchange order is placed by MV.
