# MV Signal application recovery — 15 October 2026

## Verified repository state (not VPS claims)

- Production source of record: GitHub `main`, still the V4/V3-compatible
  application at schema `0008`, with `MV-TREND-DUAL-v4` strategy and
  `compose.telegram.yml`.
- V7Sonic changes are on `codex/v7sonic-production-adapter` and draft
  review branches, **not merged into main**. Schema `0009` adds internal
  paper cycles; `0010` adds a separately approved delivery table. No
  authorized V7 publisher or automatic release-certification producer
  is implemented.
- Observed retrospective research: V7 original and first challenger
  generated zero qualifying candidates in 48 decisions. The 6-month
  EMA-reentry experiment produced 1,289 modeled trades averaging
  **−0.200391R**, and the 4H-regime/15m-breakout alternative produced
  974 trades averaging **−0.320265R**. Both were rejected.
- Existing application already includes the API, Next.js UI, Binance
  collector, worker leases, SignalDecision evidence, durable Telegram
  outbox, analytics and history. Rebuilding them is not necessary.

### Reproducible release blocker fixed in this PR

Before this patch, the API's public `/health` in production demanded
`alembic_version=0008` unconditionally. A complete and expected V7
schema `0010` would therefore be classified as an API/database
failure. This patch accepts only `0008` or complete `0010`, never
intermediate `0009`, unknown future or missing revisions. The fix
only changes code; it does not apply DB migrations.

### Added useful read-only diagnostics

- `GET /v1/operations/diagnostics` — authenticated; no mutation;
  last 24h V4 decision/outcome/rejection summary; collector and
  engine states; legacy Telegram delivery status counts; V7 private
  cycle/decision/delivery states if and only if the complete V7 schema
  is verified; explicit research/release blockers.
- `GET /api/diagnostics` — Next.js credential-forwarded,
  no-cache same-origin proxy.
- System & delivery dashboard — shows the explicit non-publication
  status and recent decision reasons, rather than presenting private
  V7 paper activity as actionable signals.
- Tests cover `0008` and `0010` production health, intermediate
  `0009` failing closed, bearer protection, no mutation and no
  unreviewed publication.

## Remaining before any user-facing signal release

1. **Do not treat the new health response or diagnostics as a
   certificate of strategy edge.** It only describes software state.
2. Finish a *separate*, independently validated, prospective
   economically positive strategy. Latest V7 trading models have
   negative modeled returns; do not activate them.
3. Independently rehearse a **production-shaped** PostgreSQL clone
   upgrade `0008 → 0010`, prove legacy API compatibility,
   backup/restore, and rollback. Do not apply migrations on the VPS
   merely because `/health` will now understand `0010`.
4. Implement and independently verify a V7 release authority
   (source/portfolio attestations, signed approval), publisher,
   emergency stop, duplicate-safe delivery and private Telegram
   fault testing. V7 paper SQL and private copies are not publishers.
5. Stage code side-by-side, check exact production source SHA,
   monitored service states and no old V4 restart, then perform an
   explicit authorized cutover only after every release gate.
6. Preserve audit data, archived V4 outcomes, and original paper
   source bytes. The application should continue as a **read-only
   market intelligence dashboard** until validation succeeds.

## What this pull request deliberately does not do

No VPS SSH, production Compose, PostgreSQL migration, Telegram
sending, account credential access, live market polling or strategy
threshold changes. A CI pass is not evidence that services are
running on the user's VPS.

**Operational deliverable:** a tested, repairable web application
foundation with precise readiness reporting.

**Financial deliverable:** none; profitability is not demonstrated.
