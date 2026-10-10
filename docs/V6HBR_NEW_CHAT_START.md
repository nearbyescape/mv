# Copy this complete message into a NEW ChatGPT chat

Continue MV Signal **V6HBR (Hybrid, Balanced, Reserved)** from the authoritative consolidated draft GitHub PR **#13**:
https://github.com/nearbyescape/mv/pull/13

Repository `nearbyescape/mv`, research branch
`codex/mv-v6hbr-research`, target `main`.
**First read the ENTIRE**
`docs/V6HBR_PROJECT_CONTEXT.md` and
`packages/contracts/v6hbr-research-v1.json` **from that research branch**,
and the PR description. Use the connected GitHub tools.
Do not infer requirements from the name V6HBR or give me a generic V5
strategy summary; read the original rationale and empirical decisions.

**The mission**: V4's strict hourly setup misses *potentially worthwhile*
intraday entries (Oct 7: 330 checks, 0 signals; 170 4H unaligned, 134
1H no-trigger, 26 regime unready). Earlier explorations showed that
blanket 15m entry acceleration harmed the tradeoffs, so we deliberately
chose **selective 15m rescue ONLY after trend-aligned, completed-1h
`NO_PULLBACK_OR_BREAKOUT_TRIGGER`**, not bypassing 4h trend vetoes.
Keep every qualified V4 base entry; compare separate H (Hybrid),
B (Balanced extra completed-15m emerging-regime check) and
R (Reserved: maximum one rescue / two overall same-direction signals
per rolling hour) *prospectively*, with independent safety and
portfolio state. Early rescues can displace later V4 base setups;
a hindsight "winner" policy is forbidden. A higher alert count is
**not evidence of profitability**.

**Proof already obtained**: BTC Jan–Jun 15m/1h/4h source OHLCV
reconciliation PASS; historical deterministic indicators PASS;
Jan-origin Mar–May development-only BTC replay yielded **948**
hourly contexts, **27 V4 base setup references preserved pre-safety**,
**43 V5 15m rescue trigger references**. These are *not* fills,
actual published alerts, net R or profitable trades. The user
also reported ETH Jan–Jun 12/12 1h+4h source archives acquired and
verified, 5,430 candles with zero 4h mismatches. Do not claim ETH
15m/1m/portfolio outcomes from this.

**Research data contract remains frozen**:
`packages/contracts/v5-history-v1.json`,
SHA-256 `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64`;
30 chosen Binance USD-M coins, Jan–Sep 2026,
frames 1m/15m/1h/4h, Mar–May development,
Jun–Jul validation, Aug–Sep untouched performance holdout.
Because Jan-1 start means 500 closed 4h candles become available
only March 25 08:00 UTC, earlier March is ineligible.
Existing `v5` source files and manifests were intentionally carried
forward unchanged as frozen research provenance, not a competing
V5 roadmap. Archived ZIP data is on VPS
`/var/tmp/mv-v5-history-archives`, not in GitHub.
The old stacked V5 PRs #5/#9/#10/#11/#12 were closed, with comments
pointing to this new sole authoritative V6HBR PR; do not reopen them.

**No production changes**: Live V4 `0.14.0` is healthy with
PostgreSQL schema `0008`, existing engine, API, Telegram; manual
Lighter futures workflow. Do not deploy, merge, reset, rebuild or
restart `/opt/mv-signal/app`, alter live DB, add migrations, restart
Telegram/engine, alter risk, or make trades without my explicit approval.
Only work in the V6HBR draft branch and isolated, constrained research
Docker/container, read-only with respect to production. No surprise
historical bulk downloads. Main has six commits not in the inherited
research branch, including important daily Telegram-report fixes;
PR #13 has unresolved integration divergence/mergeability and must
not be auto-merged.

**Your first reply** should briefly verify:
1. GitHub PR #13 is open/draft, and its current head;
2. the original reason blanket 15m scans were rejected and why
   V6HBR tries H/B/R;
3. what is proven vs unproven;
4. the next lowest-risk step toward a *real cost-aware, chronological
   V4 versus H/B/R trading outcome backtest*.

**Prioritize** completing a credible BTC execution/portfolio pilot:
1m reference fills, venue-appropriate spread/slippage/fees/funding/
latency, ATR stop/partial TPs, adverse-first ties, cross-margin
exposure, BTC vetoes, V4-base displacement, independent cohort state.
Then scale cautiously to 30 coins and evaluate untouched holdout
only after policies/metrics are frozen. Do not declare "finished"
based on raw candidate counts. Ask for read-only VPS evidence rather
than inventing it. Preserve all strategy and source SHA lineage.

Do not treat this as an invitation to redesign the strategy.
Continue exactly from the checked-in V6HBR evidence and decisions.
