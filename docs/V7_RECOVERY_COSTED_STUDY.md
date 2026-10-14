# V7Sonic strategy recovery — versioned historical evaluation

**Status: development / paper research only. This is not a replacement live
trading engine. V4 and Telegram must remain stopped.**

## Problem and measured baseline

On 14 October 2026 the original and the first 15m challenger were both
recertified against 48 decisions across two four-boundary research runs:
**0 valid candidates**. The original had 38 no-expert decisions and 10
after-cost economic rejections. The first challenger reproduced the same
0/48 result, despite its software tests passing. PR #18 records this
negative result and is not deployable.

## Independent V1 strategy

This version makes a **new** hourly EMA20/EMA50 trend + 15-minute
EMA20/EMA50 controlled re-entry reference. It does not import or run the
legacy V7 expert discovery function. It is long/short symmetric; uses
only completed, chronologically prior candles for its decision, checks
a completed directional confirmation and historical volume, and avoids
sudden off-trend price extension.

At a model-selected decision boundary, entry is *simulated at the next
15-minute candle's opening price*, with a bounded opening-gap gate.
The stop is the more conservative of historical 15-minute swing structure,
1.25x 15m ATR and 0.75x 1h ATR, limited to 3x 1h ATR. Target is 2.25R;
the minimum modeled net reward at target remains 1.25R. The assumed
execution budget is **4bps taker fee plus 4bps slippage on each side**,
not zero. No broker price/size, market order fill or funding is verified.

At most four modeled ideas can overlap (no same-symbol duplicates), with
three-hour same-market cooldown. Illustrative 0.5% loss budget per idea.
Max reference holding time is 20 completed 15-minute bars and the
position is closed on the 23:00 IST session boundary. Stop-first
resolution is mandatory when the same 15m bar touches both stop and TP.
At a gap through stop, fill worse at bar opening rather than at the
nominal stop. References near the end of available data are censored,
not falsely scored as timed exits.

**These are HYPOTHETICAL historical references, not subscriber signals.
They may be optimistic because quote availability and intra-15-minute
entry execution are not directly observable.**

## Evaluation data and provenance

Exactly six Binance USD-M futures markets:
BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT.

Exactly six complete archive months: April–September 2026.
Exactly 36 published 15m monthly ZIP and .zip.CHECKSUM pairs from
`https://data.binance.vision/data/futures/um/monthly/klines`.

- Public download command is OFF by default and requires operator opt-in.
- Archives are checked against their .CHECKSUM and the full calendar row
  count, close time, price geometry, and consecutive candle timestamps.
- A publisher-hosted checksum only verifies the stored bytes match the
  publisher-provided checksum. It does not independently prove a live
  market event, timestamp, execution or exchange order.
- Every strategy rule and archive month range is frozen in code and a
  SHA256 policy identifier before opening the six-month source.
- Apr–May = historical development; Jun–Jul = inspected research;
  Aug–Sep = later exploratory comparison, **not independent holdout**.
- Data and September market outcomes may have been inspected in other
  MV projects. Do not describe any of these months as out-of-sample.
- Final acceptance needs a new, truly prospective period after this
  code freeze and adequate genuinely independent sample size.

The model output contains market-level rejection codes, selected paper
references, monthly group summaries, mean costed R, stop-first
ambiguities, wins/losses and seeded, calendar-day-resampled 95% intervals.
Trades at the end of an archive without complete follow-up are
RIGHT-CENSORED and excluded from economic means.

## One guarded VPS evaluation

Once a clean SHA-pinned checkout of this branch exists, run:

```bash
cd /var/tmp/your-clean-v7-recovery-worktree
V7_STUDY_SHA=<exact-reviewed-40-hex-head> \
  V7_PUBLIC_ARCHIVE_DOWNLOAD_APPROVED=YES \
  bash deploy/v7-recovery-study-vps.sh
```

The single bounded script checks retired V4 and Telegram containers are
stopped, builds a separate Docker image, runs safety and strategy tests
offline, downloads **only public archive data** into a new research-only
directory, and executes the evaluator with `--network none`.
It does not mount production PostgreSQL, private exchange credentials,
Telegram bot tokens, or original forward-paper evidence. It creates a
new JSON report and refuses to overwrite one already on disk.

The output report stays at:
`/var/tmp/v7-recovery-reports/recovery-<12-char-SHA>.json`.

To run pure no-network preflight without downloading data:

```bash
python -m app.research.v7_recovery_acquire --data-root /tmp/research-example
```

## Acceptance is not a software test

1. Complete six-market, six-month data integrity.
2. No runtime gap, future-bar entry information in qualification, or
   forbidden production side effect.
3. Realistically *costed* economic research: >=100 closed modeled ideas
   over >=30 distinct calendar days, positive mean costed R, lower bound
   of day-clustered bootstrap 95% confidence interval >0.
4. Positive results must replicate on a **later, independently sealed
   and previously unseen prospective window** with verified ordering,
   actual quote/spread, event-time and controlled latency.
5. Private Telegram failure injection, separate authorization signing,
   watchdog, duplicate/ambiguous delivery testing, migration/rollback
   review and explicit human release acceptance remain mandatory.

**Even if (1)-(3) pass, production remains blocked.** If the model
returns too few signals or negative expectancy, declare failure; never
change its parameters on the same sample then call those results
independent. A measured edge, not a large signal count, is the objective.
