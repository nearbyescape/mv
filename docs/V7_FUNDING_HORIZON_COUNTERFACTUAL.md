# V7 funding-window research: read-only, exploratory, NOT a release

## Real evidence and question

The operator's journal audit on 2026-10-15 reported 84 observations
(14 per market) and 78 adjacent pairs. Of the 78 pairs, 72 occurred
within the original strict 120-minute funding-crossing restriction
(92.3%). The frozen classifier produced **zero qualifying paper ideas**.
This early sample was concentrated near settlement, so its coverage
fraction must not be extrapolated to other sessions or days.

**Research question:** Would 15-, 30-, or 60-minute maximum holding
horizons avoid the overly broad two-hour funding exclusion *while still
satisfying every other frozen flow/OI/liquidity/cost rule*?

## Implementation

- `classify(previous,current)` remains a **120-minute** strategy.
- `classify_research_horizon(..., horizon_ms)` accepts only pre-existing
  15/30/60/120-minute horizons and uses the *same* price, OI, taker,
  depth, spread, session, cost and reference entry/exit conditions.
  Only the funding exclusion window is varied. Never modify timestamp
  fields in source records to simulate funding: use the actual recorded
  `next_funding_ms` to enforce each tested horizon.
- A parity check proves that the 120m research classification is exactly
  the original frozen result for every historical adjacent pair.
- `funding-study` recomputes conditional pre-portfolio candidate counts
  and first-failure reasons from the hash-verified historical journal.
  It does **not** write paper candidates, compute fills, send client
  notifications, or alter the running collector.

## Run on the VPS safely

Use the tested **research worktree only**, not production code or
the active collector checkout:

```bash
PYTHONPATH=/absolute/research/worktree/services/api python3 -m \
 app.microstructure.cli \
 --db /srv/mv-v7-microstructure/data/evidence.sqlite \
 funding-study --last-samples-per-symbol 288
```

The input DB must remain read-only. A paper idea only represents a
**conditional** candidate before cooldown/overlap restrictions.

## Essential limitations

- Zero or few candidates in a few hours are not statistical evidence of
  strategy profitability or failure across a normal day.
- These are point-in-time REST depth *snapshots*, not a reconstructed,
  exchange-sequenced order book. No live executable fills.
- A shorter 15m evaluation horizon is not a promise that the target or
  stop can actually execute within 15m. It changes only the funding
  guard for this exploratory replay; the frozen gross 1.8R target and
  0.75% stop remain unchanged.
- No backfilled unseen trades or generated historical winners are
  claimed. An entirely different paper release candidate would need
  pre-specified execution, expiry, fee, funding and slippage treatment.
- Multiple horizons compared on the same early data are *exploratory*
  and not an independent out-of-sample test. Any proposed variant
  must be frozen prospectively and evaluated on new, unseen sessions.
- Source code includes no live-trading or Telegram client integration.


## Observed 90-pair sample and next diagnostic (October 15, 2026)

The verified VPS run of the four-horizon study yielded **90 adjacent
pairs**. With 15m or 30m funding exclusion, **67/90** first failed
`OPEN_INTEREST_NOT_CONFIRMED`; 12 were invalid older observation
intervals and 11 had repeated taker periods. Zero pre-portfolio
candidates qualified for ANY tested horizon.

**Do not lower the original >=0.20% five-minute OI threshold based
only on this finding.** To establish whether removing it would even
permit aligned taker-flow/book opportunities, use the additional
research-only stage funnel:

```bash
PYTHONPATH=/absolute/research/worktree/services/api python3 -m \
 app.microstructure.cli \
 --db /srv/mv-v7-microstructure/data/evidence.sqlite \
 filter-funnel --last-samples-per-symbol 288
```

It reports the original first-failure decision, all cumulative stage
passes, OI percent-change quantiles in pairs that passed prerequisite
gates, same quantiles by market, aligned directional taker/depth
counts, and a **clearly labeled** number that would pass the
remaining gates *if OI were ignored*. This last figure is a
diagnostic of filter coverage **not a proposed strategy, expected
signal frequency, trading opportunity or evidence of profitability**.
The audit asserts exactly the same first-failure decisions as the
frozen classifier for every pair, reads only the verified hash chains,
and cannot alter the running journal.

Multiple comparisons over the same small, time-clustered market sample
are exploratory and may mislead. Any future policy changes require
independent unseen forward observations and executable pricing.
