# MV Signal — V6HBR authoritative project charter and new-chat handoff

> **READ THIS FIRST.** This file and the V6HBR draft PR are the single active
> engineering context for the research successor to the V5 draft PR stack.
> **V6HBR = Hybrid + Balanced + Reserved**. It is an **unreleased research
> version**, NOT the currently deployed trading strategy. The running strategy
> remains `MV-TREND-DUAL-v4` (release 0.14.0).

## 1. The actual reason we built this — what must never be forgotten

**Not:** "We need more signals and must scan faster."

**The research question:** Does a strictly selective completed-15m rescue
mechanism recover **worthwhile** intraday opportunities that live V4 misses,
*while preserving V4 base opportunities and improving (or at least not
degrading) net portfolio-level performance after trading costs and risk
controls?* More trades alone is not success. No target win rate, profit, signal
count or guaranteed income has been established.

**Observed trigger:** On 7 October 2026, V4 processed 330 decisions
(30 symbols × 11 hourly scans) and emitted **zero** qualifying signals:
170 `4H_TREND_NOT_ALIGNED`, 134
`NO_PULLBACK_OR_BREAKOUT_TRIGGER`, and 26
`TREND_REGIME_NOT_READY`. The 134 cases are *not 134 lost profitable
trades*: some may be untradeable or unprofitable, and every proposed rescue
still needs independently verified acceptance/execution.

**Critical decision from earlier investigation:** A broader/higher-frequency
15m approach was studied in early October and was **not adopted** because the
quality/portfolio tradeoffs were worse. **Do not** convert the 1h engine to
15m blindly, weaken 4h confirmation, or allow an extra trigger just to inflate
alert counts. The selected direction was *selective rescue after an otherwise
qualified 1h context*, preserving all original V4 base setups.

**Critical discovery:** V5 Hybrid rescue alerts could consume a rolling
directional capacity slot before a later V4 base entry arrived. Because an
entry cannot be reversed after seeing future candles, we designed a
prospective reservation/quota rule, not a hindsight preference. Need
chronological portfolio simulation to learn if reservation improves net R.

## 2. Versions and exact strategy hypotheses (do not conflate)

| Cohort | Intended behavior | Key question |
|---|---|---|
| **V4 baseline** | Production completed-1h pullback/breakout setup with completed-4h trend and existing market-risk protections | What trades survive the real V4 process? |
| **H — Hybrid** | Preserve each V4-qualified base candidate. **Only** if V4 reports trend-aligned `NO_PULLBACK_OR_BREAKOUT_TRIGGER`, arm the same completed 1h/4h context and inspect subsequent completed 15m pullback/breakout candles for the first qualifying trigger before the next 1h close | Does selective rescue improve outcomes after costs? |
| **B — Balanced** | Independently clone Hybrid; established-regime entries unchanged; for emerging entries require that symbol's latest *completed* 15m EMA20>EMA50 directional order, favorable EMA20 slope, and directional close relative to EMA20 (mirror for shorts); fail closed on missing snapshots | Does tighter emerging-regime confirmation improve net quality? |
| **R — Reserved** | Independently clone Hybrid; preserve base lane eligibility; prospective max **one** same-direction rescue publication per rolling hour while retaining max **two** total same-direction publications in that rolling hour, plus all other caps | Does limiting early rescue crowd-out retain worthwhile base opportunities? |

"HBR" denotes the **research family**, not an instruction to combine all
three into a magically superior strategy. Compare H, B and R against the
same V4 baseline with independent, chronological portfolio state.
A future combined H+B+R product requires explicit specification, new
tests and objective evidence; do not quietly mix rules or optimize using
untouched holdout dates. Current underlying pure strategy source still calls
itself `MV-TREND-DUAL-v5-candidate` for historical traceability; that name
does **not** mean production was upgraded or that V6HBR is already live.

In all variants, retained constraints include: 09:00–23:00 IST entry
session; completed-candle / as-of timing only; 500-closed-bar warmup;
4h + 1h alignment; BTC market-regime/timing veto; validated quotes and
tick sizes; momentum/extension and anti-chase checks; repeat signal
deduplication; directional circuit breaker; active-position/exposure
caps; and V4-derived 2× ATR reference stop, scaled TP1/TP2/TP3.
V4 base preservation **before** safety has been observed; after safety
the variants may diverge due to chronological capacity competition.
Manual Lighter futures trading is the user workflow. Binance USD-M is
the *signal reference venue*, **not proof of Lighter fills**. Do not
introduce automated execution or alter capital/leverage defaults.

## 3. Objective success measures

Pre-register rules using development evidence; compare on identical
chronological data with venue-appropriate 1m execution references, fill
latency, spread and slippage scenarios, maker/taker fees, funding, stop-first
intrabar ambiguity, partial exits, concurrency and cross-margin/risk
exposure, BTC vetoes, rejection diagnostics and persistent open positions
across sessions. Examine net R after costs, expectancy, win/loss mix,
signal frequency, missed V4 base trades, drawdown, tail exposure and
risk-adjusted return. Report uncertainty and minimum sample limitations.
Do not confuse gross theoretical +R, adverse-first timing, mark-to-market,
reference signals, or rejected counterfactual outcomes with realized P&L.
No unverified performance claim may justify deployment.

## 4. Historical evidence and version-locked provenance

Frozen original archive spec:
- `packages/contracts/v5-history-v1.json`;
- **immutable SHA-256** `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64`;
- 30 chosen Binance USD-M coins; `1m,15m,1h,4h`; Jan–Sep 2026;
- Jan–Feb warmup, Mar–May development, Jun–Jul validation,
  Aug–Sep **untouched holdout**. April–May can be evaluated after
  the warmup gate; with a Jan-1 origin the 500th completed 4h candle
  is **25 March 2026 at 08:00 UTC**, so March 1–25 is ineligible.

**Never silently edit/rename this spec**, remove source hash bindings, or
relabel source paths and manifests. The historical archives live **only
on the operator VPS** at
`/var/tmp/mv-v5-history-archives`; GitHub contains acquisition,
integrity and replay code, **not** the downloaded ZIP data.
V6HBR **reuses** those archives in research mode. Do not move, rewrite,
delete, re-fetch without approval, or link them to production storage.
"V5" in archive filenames, manifests, source modules, and tests is
**legacy provenance**, not a competing active project.

Verified/reported pilot evidence as of 10 Oct:
- BTC Jan–Jun `15m=17,376`, `1h=4,344`, `4h=1,086`;
  independent aggregated OHLCV matches **exactly**, zero 15m→1h and
  1h→4h mismatches; live indicator reconstruction passes.
- BTC **development-only decision replay** observed 948 hourly
  contexts; 27 V4-qualified base references preserved **pre-safety**,
  plus 43 15m rescue trigger references. **Not** 70 executable or
  profitable trades.
- ETH Jan–Jun `1h+4h=12` monthly archives and `5,430`
  candles were reported as acquired/verified with zero 4h mismatches
  in a later conversation. This evidence must be rechecked against
  actual VPS verification output before asserting source-integrity
  parity in a final performance report; earlier GitHub documentation
  recorded the plan as `PLANNED_ONLY`. Neither report proves ETH
  15m triggers or completed 1m execution data.
- Repository inventory at an earlier checkpoint had just **21/1,080**
  monthly cells present and 1,059 missing. That snapshot is stale
  after ETH acquisition; do not use it as current coverage without
  rerunning the offline inventory. A 404 is not listing-age proof.

## 5. Exact lineage and what was migrated

**Single active V6HBR branch:** `codex/mv-v6hbr-research`.
New **draft PR targets `main`** and replaces the entire previously
stacked V5 research chain; the old PRs are historical only.

Source of migration:
- #5 — V5 15m Hybrid research, branch `codex/mv-v5-15m-entry-candidate`
- #9 — V5 Balanced, branch `codex/mv-v5-balanced-research-review`
- #10 — candidate audit and V4 displacement, branch `codex/mv-v5-candidate-decision-audit`
- #11 — Reserved policy, branch `codex/mv-v5-reserved-base-research`
- #12 — frozen historical archive, indicators, decision replay,
  archive inventory/worklist and operator pilots, branch
  `codex/mv-v5-historical-archive-pilot`
- final verified V5 stack head **`2619f0cc78a88f0a709267095a13a27185c74a0e`**.

V6HBR branch was created from that exact final V5 stack head,
**preserving all Git-tracked research code, tests, documents and
previous commits without squashing away provenance**.
This is a research reorganization, *not* an algorithmic revision.
Keep existing `strategy_v5.py`, `v5_compare.py`,
`v5_decision_replay.py`, `v5_archive_*.py`, tests and legacy
V5 file names, until any renaming is implemented as a separate,
reviewed, testable compatibility change. A missing V6HBR-specific
production strategy identity is intentional: production upgrade
has NOT been approved.

GitHub `main` has diverged from the old V5 stack, containing
separately merged V4 daily Telegram-report changes; a draft PR may
require a conflict-resolution/rebase before any possible merge. Never
force-update `main` or blindly overwrite its Telegram changes.

## 6. Production state is sacred

The VPS live release is V4 `0.14.0`, with manual Lighter trading,
not an automated execution bot. Latest read-only evidence:
- `mv-signal-api-1` internal `/health` **HTTP 200** and `{"status":"ok"}`
  (production schema `0008`);
- engine and ordinary Telegram worker running;
- daily Telegram worker delivered report dated 2026-10-09 with
  message id `196`;
- public `/health` returning 404 is normal through the public
  Next.js frontend; API internal `/health` is the correct test.

**Absolutely no changes to** `/opt/mv-signal/app`,
production Compose stack, V4 source/runtime images, PostgreSQL,
migration history, collector, live signal worker, analytics, Telegram,
secrets, live historical journals or other websites without explicit
owner permission. No `docker compose up/down`, engine restart, live
backfill, schema migration, order execution or unsafe ref reset.
Use ephemeral network-disabled Docker analysis containers with the
research code/archive read-only, pinned existing API image, UID 10001,
~0.5 CPU/768MiB RAM and no environment secrets.
Fetching archives, when explicitly approved, may write **only**
the separate research volume with strict disk/network/timeout caps.

## 7. Prioritized next work — don't mistake acquisition for the goal

1. Verify the new PR code lineage/CI and the latest ETH source evidence.
   Keep archived checksums and historical origin intact.
2. Achieve a **full economically meaningful BTC research outcome
   pilot**: acquire/verify required 1m execution reference months;
   compare V4/H/B/R with historical quote/price filters, exchange
   constraints, BTC veto, realistic costs/stop-first conservative
   exits and ongoing active-position/cross-margin state. A
   decision-only rescue count is *not* that pilot.
3. Extend symbol coverage incrementally from BTC/ETH to 30, with
   eligibility audits for inception/delisting and independent
   15m→1h→4h reconstruction. No unapproved bulk downloads.
4. Pre-register frozen policies and metrics; validation Jun–Jul;
   do NOT inspect August–September trading outcomes until models and
   risk settings are locked. Use one final holdout evaluation.
5. Only if net risk-adjusted evidence survives validation, tests,
   independent review and approval, prepare a future V6HBR
   production proposal, separately from this draft PR.

## 8. New-chat operational contract

Start by reading **this entire file**, then the new V6HBR PR body.
Explain back:
(a) *why* broader 15m was not promoted,
(b) why the Hybrid only rescues the aligned hourly no-trigger,
(c) why prospective reservation is needed,
(d) that 27+43 is **not** a profitable-trade count,
(e) what evidence is missing for a real-cost V4/H/B/R conclusion.

**Do not** autonomously choose a different strategy, optimize on
holdout, claim profits, change versioned contract hashes, or touch
production. Ask for the VPS read-only output when a claim requires
host access. Continue toward net-cost performance evidence.

**One sentence:** *V6HBR tests whether select completed-15m
rescues can recover valuable hourly misses while protecting V4
base signals and improving cost-adjusted portfolio returns — not
whether a scanner can print more alerts.*
