# V7Sonic: OI-rejected shadow setups and prospective book-point outcomes

**Research classification:** offline / read-only / unvalidated. Not a
production trading strategy and not a live-signal release.

## Why this study exists

After the 2026-10-15 102-pair read-only filter audit:

- 79 pairs passed all earlier guards under a 15-minute funding horizon.
- 0/79 passed the original **+0.20% open-interest increase** requirement.
- Median OI change was **+0.0054433%** and p90 **+0.0747719%**.
- Of those 79, only **12** aligned on taker flow and visible book
  (6 LONG and 6 SHORT) and passed every other existing gate.

Thus relaxing the funding horizon alone is insufficient and deleting
the OI check would yield **at most 12 pre-portfolio hypothetical setups**
in this short, clustered sample. No evidence yet proves positive returns.

## What this analysis does

The `oi-shadow-outcomes` offline command verifies all journal hash
chains and reconstructs the same original decision-time gates for
15m/30m/60m/120m windows. It selects a shadow reference **only if the
single failing rule is the OI threshold**. It does not relax timing,
recent taker period, depth, session, spread, funding level or boundary,
direction agreement, liquidity or modeled cost.

Only after selection, it retrieves the earliest *actually recorded*
book quote at or within 10 minutes after the requested outcome horizon
and reports a **future-book-touch mark** using the same reference
spread, 8bps per side modeled fees/slippage, and fixed 0.75% reference
risk distance. It never invents a future candle/fill. It censors
marks when the observed quote crosses the previously known upcoming
funding boundary. If no qualifying quote exists, it reports missing
future data, NOT an assumed zero or successful trade.

No trade is executed; no stop/target path, actual fills, bid/ask
sequence, funding execution, or exchange order is verified. Overlapping
setups and multiple horizons are not independent samples.

## Run safely

Use a **separate pinned research worktree**, not the running collector
checkout:

```bash
PYTHONPATH=/absolute/research/worktree/services/api python3 \
  -m app.microstructure.cli \
  --db /srv/mv-v7-microstructure/data/evidence.sqlite \
  oi-shadow-outcomes --last-samples-per-symbol 288
```

The command only opens the journal with read-only SQLite semantics.
Any counts/point marks are preliminary, descriptive and
**not historical realized trade returns, win rates, or proof of edge**.

The running paper policy is unchanged. Any future policy proposal
would need pre-registered rules, a fresh forward holdout across multiple
funding cycles and market regimes, sufficient disjoint trade outcomes,
actual fill/stop/target modeling, fees, slippage and uncertainty
quantification. **Do not promote this shadow audit into Telegram.**
