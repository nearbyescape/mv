# MV Signal V6HBR — pre-session live release gate

**Decision on 10 October 2026:** **NO-GO for V6HBR live signal publication.**
This is an engineering/safety gate, not a forecast of cryptocurrency prices.
The operator requested a next-session release and stronger accuracy after adverse recent V4 signals. The current evidence does **not** demonstrate a reliable live edge. Shipping under a deadline must not substitute for proof.

## What is ready

- V6HBR draft PR #13 has research cohorts V4, H, B, R and chronologically isolated offline replay.
- The initial BTC Apr–May development-only 1m proxy returned **negative modeled net R for every cohort**, with 14–24 terminally resolved references per cohort. No 30-coin sample or actual Lighter fills in these metrics.
- Cohort attribution, resolved-only quality statistics, conditional fee/funding stresses, and early 15/30/60 minute adverse-first diagnostics are implemented in research code.
- Separately authorized V4 `signal_outcomes` forensic analysis and sanitized PostgreSQL read-only export are prepared, **not executed on production**. Real October 7–10 signal outcomes and venue fills remain unverified.
- An operator has installed an hourly VPS research service. Previous operator logs confirmed one run with 43 passing regressions and one false-positive static test. A later start was observed, but **the output from the newest V6HBR SHA is not available to GitHub tools**. Do not describe the current suite as passed.
- Live V4 release `0.14.0` remains unchanged; V6HBR is unmerged and DRAFT.

## Minimum controls for any candidate to be reviewed for live publication

`services/api/app/research/v6hbr_release_readiness.py` exposes `assess_release_readiness(evidence)`. It returns **NO_GO_FOR_LIVE_V6HBR** for absent, partial, nonfinite, or negative evidence. This is a *pre-registered minimum research gate*, not a target win rate or an automated deployment approval.

All gates are required:

1. Exact reviewed source SHA, immutable historical-source hashes, passing GitHub and VPS regressions *on that SHA*, no live V4 modifications.
2. Recent actual published V4 signals independently audited by coin, direction, setup, trend regime, 0.5R adverse-first timing, candle revisions and closeout reference outcome; reconcile with operator venue fills separately. Never infer current alert performance from old BTC candles.
3. Audited chronological multi-coin replay on development data, preserving V4 base opportunities, correlation/risk caps and as-of guards. No lookahead.
4. Rules frozen **before** independent June–July validation and untouched August–September holdout. If the holdout was consulted for model selection, it is no longer a valid untouched holdout and a fresh future period is needed.
5. Research sample minimum: at least **100 resolved trades across 10 or more symbols in validation** and **100 across 10 or more symbols in holdout**. These are minima, not guarantees of precision; the underlying effective sample shrinks under coin correlation.
6. Positive after-cost net R for both independent windows, **positive lower 95% confidence bound on mean net R** after costs in each window, and positive R under a **fully repriced stressed** execution scenario in both. The research 3×3 post-hoc fee/funding grid on fixed fills **does not** by itself satisfy the full stressed replay gate.
7. Measured mark-to-market portfolio maximum drawdown (accounting for overlapping positions/open risk) no worse than V4; the research settled-trade-only drawdown does **not** satisfy this.
8. Validated as-of venue liquidity/tick/fees/funding, integrity and source revision checks, safety rollback/alert plan, independent reviewer approval and operator signoff.
9. Safety stance if independent edge fails: **do not release as actionable signals**. A research-only preview with conspicuous no-trade labeling can be considered separately; it must not silently change V4 or instruct real-capital trades.

The code returns `ELIGIBLE_FOR_MANUAL_RELEASE_REVIEW_ONLY` even if **all** self-reported proof flags pass, because a Boolean manifest is not independently authenticated evidence. It *always* emits `can_auto_deploy: false` and `can_claim_high_accuracy: false`.

## Before next session: concrete go/no-go

- Capture actual latest VPS per-commit regression and BTC replay log. Passing tests mean the code executed; they do not mean profitable signals.
- Independently review the last several days' production V4 `signal_outcomes` with a bounded read-only export **only if separately authorized**. No production table change, restart, order or Telegram posting is implied.
- If investigation finds an entry gate worth proposing, freeze it prospectively and run development → validation → sealed holdout comparisons with net costs and missed V4 opportunity accounting. Do not make an accuracy claim from the same sample used to choose the filter.
- **NO-GO remains the default** unless all evidence and signoffs exist. Do not hurry a live trading system because the clock is approaching the next 09:00 IST session; extending research is preferable to exposing users to unvalidated predictions.

**No auto promotion/deploy code is included.** Never enable an unsupervised production rollout by reinterpreting research success flags.
