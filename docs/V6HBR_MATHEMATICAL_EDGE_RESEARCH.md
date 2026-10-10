# V6HBR mathematical edge / abstention study — 10 October 2026

Status: research-only and unverified on the current VPS SHA. Production V4 unchanged; no live V6HBR authorization.

## Economics: payout is not the same as accuracy

The original V4 plan scales partial exits: 30% at +1.0R, 30% at +1.5R, 40% at +2.0R. Thus an ideal full three-target result before frictions is 0.30 × 1 + 0.30 × 1.5 + 0.40 × 2 = **1.55R**. This is not an observed average winning outcome.

If every losing trade were -1R, every winning trade exactly +1.55R and roundtrip friction cR were charged on either result, the idealized break-even hit rate is p = (1 + c) / (2.55). For hypothetical c=0.10R, this is about 43.14%. If actual NET average winning trades were instead +0.40R and average losers -1.10R, the required hit rate rises to 1.10 / 1.50 = 73.33%. These figures are mathematical illustrations, NOT measured MV trading outcomes. Early stops, mixed targets, liquidation risk, price gaps, funding and fees make the true distribution more complex.

## Implemented: as-of evidence-gated abstention, research only

See services/api/app/research/v6hbr_math_abstention.py. It receives matured, individually identified NET R outcome records with published and terminal times, direction, setup and trend regime. Data from entries whose terminal time is at or after the decision are ignored, so it cannot learn tomorrow's outcome today.

Conservative predeclared minimums: 80 resolved reference trades across 20 UTC trading days within 90 days, no one day supplying more than 15% of samples, and evidence no older than seven days. Outcomes outside an explicit [-4R, +4R] research envelope are not clipped: the screen ABSTAINS pending tail-risk investigation. A deterministic 4,096-resample day-clustered bootstrap uses equal-day means and demands that the lower 2.5% sample quantile exceed an extra adverse 0.10R cost shock.

This is an exploratory dependence-aware screen, NOT a formally anytime-valid confidence sequence or certified 97.5% live reliability. Repeated testing, selection bias and distribution shifts can destroy nominal coverage. A positive screen means only RESEARCH_ELIGIBLE_FOR_FURTHER_INDEPENDENT_TEST, not permission to publish or trade. Insufficient data means ABSTAIN.

## Shadow-only integration

See services/api/app/research/v6hbr_abstention_audit.py. It computes an as-of shadow result using only V4 baseline references that had already terminally resolved when a BTC April–May candidate occurred. It leaves all actual simulated V4/H/B/R acceptances, portfolio capacity, and measured net R unchanged. The earlier BTC development sample had only 14 resolved baseline references, so insufficient-sample abstention is expected, NOT a demonstrated accuracy improvement.

The BTC pilot nests prospective_math_abstention_shadow in post_hoc_attribution, which the installed pinned VPS research agent already prints without changing its root-owned script. New tests live in test_v6hbr_math_abstention.py and test_v6hbr_abstention_audit.py. The agent also runs a smoke test through its already-pinned test_v6hbr_btc_pricing_pilot.py test suite. Verify actual execution before claiming tests pass.

## Release decision

NO-GO: the baseline BTC April–May reference outcomes were negative net R for V4/H/B/R, and the October live V4 losses have not been independently reconciled against actual signal_outcomes and venue fills. This prototype has not produced demonstrated profitable predictions. Do not promote without independent full 30-coin time-forward validation, preserved out-of-sample periods, venue-accurate costs, correlation-aware portfolio risk and explicit operator signoff.

## Additional fixed candidate protections tested only as counterfactuals

Research file services/api/app/research/v6hbr_conservative_veto_stress.py predeclares three no-hindsight experiments: (a) established 1h+4h trend regimes only; (b) skip momentum-breakout references whose source close is over +1.00 ATR in trade direction beyond EMA20; and (c) both restrictions simultaneously. The original production source still accepts emerging regimes and has a more permissive breakout extension limit. None of these experimental parameters are tuned to the observed BTC losses.

Each experiment first vetoes an entry using its decision-time regime/setup/source-extension only, then **independently replays the full chronological portfolio** under existing V4/H/B/R concurrency, deduplication and directional risk policies. This is crucial: simply subtracting losing trades after the fact ignores later trades that become possible when a slot is freed. Each report includes missed original signals, newly admitted candidates, accepted references and resolved net R change. Prospective filters can still miss future profitable V4 trades; both sides of that cost are displayed.

The BTC pilot inserts prospective_conservative_veto_stress into the post_hoc_attribution object printed by the installed research agent; the original V4/H/B/R cohort metrics and production API are untouched. GH-only and manual pilot tests exercise the fixed-rule counterfactuals. Actual independent validation, venue fills and portfolio drawdown remain required before any live strategy change.
