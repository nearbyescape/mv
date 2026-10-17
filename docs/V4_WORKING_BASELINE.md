# V4-only working baseline — 17 October 2026

## Scope

The current MV Signal development baseline is release **0.14.0**, strategy **MV-TREND-DUAL-v4**, risk policy **RISK-ATR14-SCALED-TP-v4**, database schema **0008**. The existing `main` branch selects V4 in `services/api/app/signals/service.py`, `packages/strategy/mv_strategy/strategy_v4.py`, and `packages/contracts/strategy-v4.json`.

V5, V6HBR, V7Sonic and T7Sonic were experimental branches/PRs, **not** active production upgrades; the V5 PRs were closed unmerged and the 15 open V6HBR/V7-related PRs were closed on 17 October 2026. Removing their remote branch refs is a separate repository-maintenance task. None of their isolated changes needs to be reverted from `main`.

## Production boundary

- V4 release 0.14.0 was deployed in the 7 October 2026 controlled cutover.
- Last verified status from 14 October 2026: `/opt/mv-signal/app` referenced release `mv-signal-0.14.0`; the V4 engine and Telegram services were stopped, and restart was disabled for the engine. This is historical evidence **not** an assertion of present running state.
- Do not run unrestricted `docker compose up -d` as part of GitHub maintenance; such commands can resume previously suspended services.
- Do not modify production schema 0008, shared PostgreSQL data, historical signals, Telegram outbox, market history, secrets, or other VPS applications in any repository cleanup.
- MV provides reference signals only; it does not place exchange orders. Neither passing CI nor successful deployment establishes profitable signals.

## V4 contract to preserve

V4 delegates completed 1H/4H setup and financial plan generation to V3, preserving initial stop at 2 frozen ATR and nominal TP1/TP2/TP3 reference levels at +1R/+1.5R/+2R with 30/30/40 allocation. V4 adds a completed BTC 15-minute **hard-opposite-only veto**, fail-closed outcome-analytics freshness, deterministic per-close same-direction cap (two), unresolved same-direction reference cap (six), and 120-minute directional circuit breaker after two clustered adverse -0.5R-before-+0.5R outcomes. The 15-minute feed cannot originate trades.

Do not silently relax strategy rules or rewrite prior signal decisions: substantive strategy changes require explicit versioning, contract review, isolated performance research, regression tests and a controlled deployment plan.

## Next V4 investigation

Begin with **read-only** forensics of recent V4 signal failures and missing opportunities: audit source and guard rejection counts by symbol/day; classify 4H alignment, pullback/breakout trigger, BTC timing veto, analytics freshness, concentration and circuit-breaker rejections; compare accepted signals' directional correctness and drawdowns using completed market data with fees/slippage and realistic reference-state constraints. Separate engineering correctness from out-of-sample effectiveness and report sample sizes and uncertainty.

Only after a measured improvement is demonstrated should a new V4 maintenance patch be proposed. No engine/Telegram restart or production cutover is implicit in this source-code decision.
