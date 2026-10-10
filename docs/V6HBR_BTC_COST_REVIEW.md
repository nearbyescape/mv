# V6HBR: BTC Apr–May cost-model findings and next evidence gate

**Status:** V6HBR is an unmerged, draft, non-deployable research family. Live V4 release `0.14.0` is untouched.

## First independent VPS result (operator transcript, 2026-10-10)

Source coverage: BTC April–May 2026. 1m and aggregated 15m candle archives passed SHA/parity audit. 60 raw candidate references: 24 V4 base and 36 completed-15m rescues. Four variants were simulated under the same **illustrative** setup: assumed BTC price tick 0.1, 2 bps spread, 2 bps adverse slippage, 5 bps taker fee, 1 bps funding debit per 8h, 1-minute post-publication latency, unit risk 1 and aggregate proxy cap 4. All entries are synthetic references, **not observed Binance/Lighter order-book fills**.

| Cohort | Accepted | Resolved | Unresolved | Resolved net R | Mean resolved net R |
| --- | ---: | ---: | ---: | ---: | ---: |
| V4 | 15 | 14 | 1 | -1.944525 | -0.138895 |
| H | 25 | 24 | 1 | -2.172139 | -0.090506 |
| B | 24 | 23 | 1 | -1.050419 | -0.045670 |
| R | 25 | 24 | 1 | -2.172139 | -0.090506 |

**These results are all negative** and cannot justify live production. They do not certify expected profitability, signal accuracy, drawdown or 30-coin outcomes. H/R identical on this single-symbol BTC pilot; this does not invalidate the multi-symbol Reserved hypothesis. There were eight original V4 acceptances absent under H/R and nine under B; absent is NOT synonymous with earlier rescue displacement. Post-hoc attribution now distinguishes exact reasons, causal earlier rescue blockers and Balanced base-only filtering.

## New post-hoc diagnostics for the next automated execution

The new `services/api/app/research/v6hbr_quality_diagnostics.py` computes, using only already-finalized cohort membership and **terminally resolved** trades:

- win/loss/flat counts, resolved-only positive fraction, mean winning/losing R and net profit factor;
- gross / fees / funding / net reconciled sums, by V4-base/rescue, direction, established/emerging regime and UTC entry month;
- holding periods and the number of 1m candles where a protective stop and target were both crossed;
- **close-only terminal** peak-to-trough R drawdown. This is *not* a real intra-position equity curve or peak-to-trough cross-margin drawdown; simultaneous open exposure and unresolved positions are omitted;
- a conditional 3×3 *fee/funding multiplier* grid: 0×, 1× and 2× historical **assumed debit** on the **same simulated fills and same accepted trades**. It does not change spread, slippage, fill quality, stop geometry or live acceptance and must NOT be interpreted as a fully repriced alternative venue simulation.

Fail-closed conditions cover outcome reconciliation, duplicate accepted IDs, unexpected terminal status, position dates crossing the cutoff, missing price data and unresolved positions that incorrectly carry booked net R.

Quality diagnostics are available both as top-level `post_hoc_quality_diagnostics` and embedded in `post_hoc_attribution.post_hoc_quality_diagnostics`, since the **already installed, pinned host agent** prints that latter key. This avoids silently modifying the installed fixed root-owned service script.

Dedicated unit fixtures are included in `tests/test_v6hbr_quality_diagnostics.py` and wired into the GitHub-only workflow and manual pilot, although the **already installed agent has a fixed old pytest file list** and exercises the module at runtime through the BTC replay, not those new synthetic fixtures. GitHub Actions status remains independently unverified.

## Latest automation facts

The one-time systemd service and hourly timer have been installed by the operator. First run failed due to systemd `PrivateTmp` hiding the `/var/tmp` archives; a read-only `BindReadOnlyPaths` override fixed that. Second run reached the offline Python tests and reported 43 passed, 1 static test failed; the code contained a forbidden string in a comment only. Commit `591727f43b0ff34513c16d15a6abab11ada1e164` removed the false-positive comment. **There is not yet evidence here of a later fully passed automated report.** No claim should be made before inspecting the VPS-generated per-SHA logs.

The fixed agent polls new V6HBR branch SHA commits hourly, using a networkless, capability-free, read-only Docker research sandbox. It writes logs to `/var/lib/mv-v6hbr-auto/reports/` on the VPS; connected GitHub tooling cannot read those private logs. No automatic production deployment or Lighter orders.

## Decision gates before broadening

1. Verify a fully passing automated report with candidate attribution and post-hoc quality scorecards; examine the actual resolved rescue-lane contribution.
2. Investigate base preservation, fee burden, ambiguous 1m stops, censored position risk and reasonable **fully repriced** spread/slippage/fee stresses with independent scenarios.
3. Extend the same audited 1m/15m/1h/4h methodology to all preselected 30 symbols on the permitted development window; preserve fixed pre-specified policies.
4. Use June–July untouched-for-development independent validation; only then inspect August–September sealed holdout under a pre-registered configuration.
5. Require observed/as-of venue microstructure, contract filters, actual funding assumptions, manual Lighter fill limitations, credible uncertainty estimates and deployment-specific portfolio safety before considering a strategy promotion.

**No promise of additional profitable signals or expected win rate has been established.**
