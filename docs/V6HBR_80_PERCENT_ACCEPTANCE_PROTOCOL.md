# MV V6HBR — 80% accuracy research acceptance protocol

**Status:** Research only. Not a live model specification, promise of achievable
accuracy, authorization to trade, or approval to retire any installed model.
Prepared after inspection of BTC and ETH April–May 2026 candidate outcomes.
All changes must remain in the isolated draft V6HBR research branch.

## Frozen measured outcome

For each **originally rule-qualified** V4 hourly or V5 15-minute rescue
candidate, the forecast is its published long/short direction, published at
the end of a completed source candle. The 60-minute evaluation starts at the
**next 15-minute bar open** and ends at the last of four complete 15-minute
reference bars. Price move must exceed **+10 bps signed in forecast direction**
to count as correct. A signed move below -10 bps is wrong; everything within
±10 bps is neutral. A censored label is reported but never assumed correct.

Accuracy must use:

    correct / (correct + wrong + neutral)

and report the number censored alongside the denominator. Never substitute
"correct / (correct + wrong)" as the promotion metric. Report 15, 30, 60 and
120 minutes separately; the primary preregistered target is **60 minutes**.
The 10 bps hurdle is illustrative, not real Lighter trading costs or fills.

**User-requested aspirational research target:** at least 80% correct by this
definition on unseen data. The target may be unattainable at acceptable signal
coverage or positive post-cost profitability. No method can guarantee it.

## Prevent trivial high accuracy

A passing *numerical screen* requires all of:

- >=100 actually observed, noncensored reference predictions;
- >=20 distinct UTC trading days;
- >=60 distinct publication timestamps (simultaneous symbols count once here);
- >=10 distinct markets plus individual market counts and full universe scope reported;
- retaining >=20% of the originally rule-qualified candidate stream;
- >=80% correct including all neutral predictions in the denominator;
- marginal Wilson 95% lower bound for correct fraction >=80% **only as a
  secondary optimistic diagnostic**, not a valid independence-adjusted claim.

These are initial research screening floors, **not statistical certification**.
BTC/ETH signal correlation, autocorrelation, same-day exposures and selection
must also be quantified with day-block and cross-market-boundary resampling.
No claims of strong confidence from single-signal Wilson intervals. Report
per-symbol, lane, setup, direction, month and time-of-day wrong-way / no-setup
counts even when a selective policy has no emitted signals.

## Frozen exploratory hypotheses from development

The five immutable *shadow comparison* masks are:

1. ALL_ORIGINAL_CANDIDATES;
2. REJECT_15_IST_HOUR_ONLY;
3. ESTABLISHED_TREND_ONLY;
4. REJECT_15_IST_AND_REQUIRE_ESTABLISHED;
5. LONG_DIRECTION_ONLY.

All masks operate exclusively on properties known at candidate publication.
They are not active trading policies and must not change original candidate
formation. Count right/wrong/neutral outcomes **for rejected candidates too**.
Removing more losing signals is not beneficial if it removes more profitable
opportunities or leaves untradeable signal volume.

The 15:00 and short-bias hypotheses are post-hoc: after inspecting April–May
two-market evidence, 12 candidates at 15:00 included nine wrong/three neutral
over eight distinct days and no correct, and two correlated coins failed
simultaneously at several publication boundaries. **Development uplift is
not independent evidence**. A short-only filter or hour veto must not be
activated based on these findings.

## Validation and untouched holdout boundaries

- **Development:** Jan–Feb indicator warmup, Mar–May development (currently
  directional candidate observations from Apr–May BTC and ETH).
- **Independent validation:** June 1–July 31, 2026. Freeze candidate rules,
  masks, outcome definitions and acceptance criteria before reading those
  labels; acquire official monthly ZIP plus publisher checksums and verify
  canonical 15m/1h/4h series with the already fixed contract.
- **Sealed holdout:** August 1–September 30, 2026. Do not read outcomes,
  change policy after looking at them or repeatedly test new strategies on
  sealed holdout. **One** final signoff evaluation only after selection is
  frozen, and all data lineage and denominator integrity checks are complete.
- Missing/incomplete symbols, exchange listings, candle ranges, or publisher
  checksum drift are explicit blockers, not grounds to silently omit
  unfavorable markets or synthesize bars.

BTC/ETH-only June–July comparisons are provisional smoke checks and cannot
be presented as evidence for all 30 frozen symbols.

## Beyond reference directional correctness

A positive directional forecast at 60 minutes does **not** establish
a fillable, profitable futures trade. Independently test executable limits,
slippage, maker/taker fees, latency, real funding schedules, ATR stop/TP
path and order-book liquidity, min/max position rules, crowding/correlation,
exposure caps, loss clustering, drawdown and per-session signal frequency.
Actual fills on the intended exchange require their own records. A policy
needs sustained positive after-cost expectation and acceptable risk as well
as directional accuracy. Report trade counts and abstention/coverage.

Do not ship an 80%-scoring policy that has negative post-cost net R. Do not
increase leverage, weaken protective stops, use invalid future indicators,
or fabricate accuracy by removing difficult observations.

## Current measured baseline

Operator VPS authenticated research outputs for BTC (60) and ETH (46)
April–May candidates: 39/106 correct (36.79%), 36/106 wrong (33.96%) and
31/106 neutral (29.25%) at 60 minutes. Removing the 12 candidates
published in the 15:00 IST hour retrospectively leaves 39 correct/94
(41.49%), 27 wrong/94 and 28 neutral/94. All four BTC cost-model cohorts
evaluated so far have negative aggregate net R. **NO-GO for promotion.**

## Separation of concerns

The shadow scorecard and archive-research analyses run with network-disabled
read-only containers, frozen source revision and checksum-pinned source data.
Only explicitly approved research archive acquisition receives network egress
and an isolated writable research volume. Never write production trading
state, exchange orders, Telegram announcements or active strategy defaults.
