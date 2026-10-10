# V5 Balanced — research-only candidate (10 October 2026)

**Status:** draft, not promoted to production and not proof of an improvement in accuracy or P&L. The original V5 Balanced cohort passed 18 isolated VPS unit tests on 10 October 2026; October 7–9 retrospective runs produced preliminary results. The candidate-audit extension on this separate branch still requires isolated validation.

This work branches from the earlier `codex/mv-v5-15m-entry-candidate` draft. It adds a third independently evaluated cohort to its full-watchlist historical comparison. No live engine, Telegram service, signal contract, database migration, or production deployment configuration has been changed.

## Experimental cohorts

1. **V4 retrospective baseline:** completed 1H V4 setups, 4H confirmation and V4 portfolio safety as simulated in the existing draft.
2. **V5 hybrid draft:** keeps V4-qualifying entries and adds completed 15m rescue triggers *only* when the 1H context is aligned but V4 rejects a pullback/breakout trigger. This is the existing, unapproved draft candidate.
3. **V5 Balanced:** uses exactly the same hybrid candidates, but accepts existing `established` entries unchanged. An `emerging` entry is only eligible when its **own symbol's** latest completed 15m candle at the proposed publication boundary meets all of:
   - directional EMA20 relative to EMA50;
   - directional change in EMA20 versus the immediately previous completed 15m candle;
   - close on the directional side of EMA20.

The 15m check cannot read a later candle, substitute BTC data for the coin's own 15m series, or bypass the candidate's already-recorded BTC veto, pricing and portfolio constraints. Missing, partial or unwarmed 15m data rejects only the emerging candidate. All three cohorts are simulated on separate state clones, including the directional concentration / exposure and circuit-breaker rules, to prevent one cohort changing another's published count.

**Research hypothesis:** fewer adverse-first emerging entries without an unreasonable reduction in qualifying opportunities. This is not an established benefit.

## Running the comparison (isolated environment only)

Run tests in a checkout of the research branch with its normal project dependencies:

```bash
cd services/api
python -m pytest tests/test_v5_compare.py tests/test_strategy_v5.py -q
```

From an *isolated research checkout with an independently configured read-only database connection and sufficient pinned historical data*, run:

```bash
cd services/api
python -m app.research.v5_compare \
  --ist-date 2026-10-07 \
  --ist-date 2026-10-08 \
  --ist-date 2026-10-09 \
  --ist-date 2026-10-10 > /path/outside-repository/v5-balanced-oct07-10.json
```

**Do not run this historical-download workload inside the production API/engine container.** Do not provide production database write credentials or Telegram bot credentials to the experiment. Configure the research database on a distinct host or isolated PostgreSQL snapshot if possible, and cap resource usage.

The script prints three JSON cohorts under `combined.v4`, `combined.v5_candidate`, `combined.v5_balanced`. Within each day's report, look at `summary.published`, `summary.mature_4h`, `summary.full_available`, `summary.preliminary_reasons`, `summary.half_r_ordering`, and the balanced `filter_reasons`. The top-level summary's resolved returns are the **fixed four-hour** reference outcome. The separate `full_available` block follows the same simulated entry to the **session end plus four hours**, not indefinitely; any still-open signal remains unresolved. `full_available_outcome_cutoff_exclusive_ms` records that boundary. Do not include an open signal's favorable excursion or mark-to-market R in realized outcome totals.

**Limitations:**

- This is a retrospective *frequency/early-adverse-move diagnostic*, **not** the requested complete multi-year historical V4/V5 backtest. The current draft uses first completed 1m open as a reference entry, a fixed four-hour comparison window, reference R outcomes, and modeled rather than actual exchange fills. Reported reference R is not net account P&L; trading fees, Lighter differences, funding and slippage are not fully represented.
- The current chosen watchlist may not be the same as the actual 7–8 October production watchlist; historical data coverage/warm-up and selection bias need to be reported. A retrospective count cannot be presented as the exact number of signals that would have reached Telegram.
- The near-term October 7–10 market events have already been examined by the project team. They are **development evidence**, not an unseen final evaluation. Multiple chronological regimes and a genuinely untouched holdout plus forward data must be evaluated before choosing V5.
- This research script does not establish that any filter is more profitable. A lower signal count or better +0.5R ordering on a tiny sample does not prove higher accuracy.
- If the missing observation progress and Decimal precision fixes remain unimplemented, the production V4 safety and arithmetic concerns from the October 10 audit remain open independently of this research experiment.

## Candidate-level decision audit (stacked research extension)

The separate research branch `codex/mv-v5-candidate-decision-audit` extends the V5 Balanced experiment with **visibility only**, not different entry rules or position sizing. Daily JSON now includes:

- `reports[0].v4.candidate_audit`, `v5_candidate.candidate_audit`, and `v5_balanced.candidate_audit`: every formed candidate, including rejected candidates, with the proposed publication time, source, lane, ranking inputs, preliminary reason, final portfolio reason, and selected flag. Rows without an eligible setup are still summarized in context/setup-reason counts and are **not** fabricated as candidates.
- `blocked_by_published`: the earlier selected signals that satisfy the actual rolling-window concentration, hourly-cluster concentration, active-directional-exposure, or same-direction session-dedupe predicate. It does not speculate about circuit-breaker blockers or forecast what a later signal will do.
- `independent_reference_full_available`: when a usable plan and reference bars exist, an *independent hypothetical path* for an entry even if the portfolio rejected it. **Never add rejected entries to portfolio R, win rates, or booked results.** This is an opportunity-cost diagnostic only; it does not model the other trades the rejected signal would have displaced.
- `reports[0].v4_base_preservation.v5_candidate` and `.v5_balanced`: matches each V4-published source setup to its V5 base counterpart and reports whether it was preserved, displaced, or unexpectedly missing. For displaced entries, the exact blockers and entry-only hypothetical outcomes are included.

The October 9 working hypothesis is that 19:15 IST UNI/LDO rescue SHORTs occupied the rolling-hour two-SHORT capacity when 19:30 IST AAVE/HBAR original V4 SHORT candidates arrived. Inspect the **individual** audit rows before calling that cause established. This report is intended to settle that question without changing policy or optimizing thresholds on an observed three-day sample.

To compare portfolios fairly, choose and register alternative capacity/reservation policies **before** running unseen dates, and replay all policies in chronological order across sessions with realistic entry fill/cost assumptions and persistent active-position state. A later V4 setup cannot retroactively be given precedence over an already-published rescue signal using future information.

## Promotion gates

- API and independent numerical tests passing, including precision and safety-progress bugs on an isolated candidate.
- Exact replay parity for historical events with source-time/data integrity, both LONG and SHORT directions, complete market opportunity enumeration and documented historical data gaps.
- Multi-year 30-coin evaluation with fees, funding, slippage, adverse intrabar order assumptions, drawdowns, correlated exposure, realistic entry delays and no lookahead.
- Pre-registered candidate comparison against a frozen V4 baseline on a genuinely unseen holdout and a sufficiently long forward observation.
- Fully rehearsed production-compatible cutover, preservation of V4 history and active safety state, report/outbox migration and rollback.

If the candidate fails these gates, keep V4 unchanged (and treat its new signals as observation-only while the unverified-edge status remains).
