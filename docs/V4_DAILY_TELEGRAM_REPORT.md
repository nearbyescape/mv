# MV V4 daily Telegram report (session-close)

## Contract

- Existing V4 financial strategy, analytics, web and real-time Telegram worker are unchanged.
- A separate `telegram-report` container publishes one *reference-only* daily report to the already-configured numeric Telegram destination.
- Schedule is **23:10 Asia/Kolkata**, ten minutes after new-signal publication ends at 23:00.
- A live report includes V4 outcomes **published 09:00–23:00 IST** on that date. Its resolved R total excludes open/source-revised rows.
- Previously published signals resolved during the report date appear under carryover, outside the primary signal count and primary R total.
- Existing analytic terminal statuses are authoritative. Later price touches cannot turn a protected exit into TP3.
- Emoji ✅ ❌ 🛡️ ⏳, Telegram `parse_mode=HTML` for real bold styling; no website URL or inline button in daily reports. Real-time signal alerts are unchanged.
- A sufficiently long report explicitly says how many result lines were omitted to remain within Telegram's size limit. Never send malformed partial HTML.
- Reports are simulated reference-plan analytics, **not actual trades** or net account P&L.

## Delivery guarantees

Table `telegram_daily_reports` is keyed by (IST report date, strategy, destination) with immutable report text frozen at first claim. The new worker uses its own DB singleton/fence, takes an atomic `pending → inflight` claim before its network request and stores the Telegram receipt on success. A recovered inflight claim becomes **unknown**, never blindly resent. Explicit rate-limit or pre-send connection failures permit up to five bounded retries. An unknown response or an interrupted send requires manual confirmation in Telegram before any exceptional operator intervention.

The start cutoff `MV_DAILY_REPORT_START_AT` is the **epoch milliseconds** of report activation. Sessions due before that cutoff are not backfilled automatically. For the first rollout, set it *before the intended 23:10 due time* if the day's report should be sent. Do not leave it at 0; the worker will refuse to start.

## Isolated VPS staging — no production mutation

From `/opt/mv-signal/app`, after reviewing and merging the PR, fetch the exact release SHA but **do not** restart all Compose services. Use the complete Compose overlay set throughout (host Nginx owns port 80/443):

```bash
COMPOSE=(docker compose --env-file deploy/production.env \
  -f compose.production.yml -f compose.host-proxy.yml \
  -f compose.research.yml -f compose.ai.yml -f compose.telegram.yml)

# Verify the target is the exact reviewed commit/release.
git rev-parse HEAD
# Set MV_DAILY_REPORT_START_AT=<deployment-time epoch milliseconds>
# inside deploy/production.env with owner-only permissions.

# Rebuild ONLY the dedicated report image; do not recreate existing services.
"${COMPOSE[@]}" build telegram-report

# Read-only preview. No Telegram message is sent.
"${COMPOSE[@]}" run --rm --no-deps \
  telegram-report python -m app.telegram.daily_report --preview-date 2026-10-08
```

Take and validate a consistent PostgreSQL backup before the schema migration. Review the generated Alembic delta and verify current DB revision is `0008`. The **only** migration is an additive `telegram_daily_reports` table. Apply the reviewed migration with the report image (rather than rebuilding or recreating the production API/engine):

```bash
"${COMPOSE[@]}" run --rm --no-deps telegram-report \
  python -m alembic upgrade head

# Verify revision and inspect any unexpected worker activity before enabling.
"${COMPOSE[@]}" run --rm --no-deps telegram-report \
  python -m alembic current

# Enable the isolated report service only.
"${COMPOSE[@]}" up -d --no-deps --no-build telegram-report
"${COMPOSE[@]}" ps telegram-report
"${COMPOSE[@]}" logs --tail=100 telegram-report
```

**No live sends during preview.** Test report formatting/aggregation on the reviewed branch (Python pytest), run an isolated report image, and check existing production container image IDs before and after activation. At 23:10 IST verify a single Telegram report message and a single delivered row with valid message ID. Do not run `--once` for dry-run: `--once` may send the report.

## Pause, investigation and rollback

```bash
"${COMPOSE[@]}" stop telegram-report
```

This leaves real-time `telegram`, `engine`, `analytics` and all other services running. The additive state table can remain in PostgreSQL; **do not downgrade live schema without reviewing downstream dependencies**. Preserve the report state and any `unknown` deliveries for diagnosis to avoid duplicate sends. A failure to receive a report does **not** justify blind manual replay if Telegram might already have accepted it.

## Read-only report verification

```bash
"${COMPOSE[@]}" run --rm --no-deps telegram-report \
  python -m app.telegram.daily_report --preview-date 2026-10-08
```

Preview uses the same formatting and database queries but does not claim report state or send to Telegram. It can reflect later database updates and is therefore not always byte-for-byte identical to the frozen nightly message.
