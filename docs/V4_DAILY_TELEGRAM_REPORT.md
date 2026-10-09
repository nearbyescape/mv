# MV V4 nightly Telegram report — production-schema-compatible release

## Requirements and boundaries

- Uses the existing V4 `SignalOutcome` journal, existing BotFather token and existing numeric Telegram destination.
- Posts one message per IST calendar session at **23:10 Asia/Kolkata** (after the 23:00 entry session closes).
- Published 09:00–23:00 IST signals form the primary cohort. Its resolved reference R excludes open and source-revised rows.
- Earlier signals resolved during the calendar day are separated as carryover, not added to the primary R.
- Reporting is reference-plan only, **not actual exchange fills/account P&L**.
- Uses Telegram `parse_mode=HTML` for bold headings, ✅/❌/🛡️ indicators; **no website URL or button**.
- Does not change trading strategy, market collection, API routes, normal Telegram alert payloads, or execution.

## Critical production compatibility (incident 2026-10-09)

The `0.14.0` production API `/health` endpoint explicitly requires `alembic_version = 0008`. Initial PR #7 introduced additive Alembic `0009`, which made the unchanged API unhealthy (HTTP 503). The user safely downgraded the empty report table; API health returned HTTP 200 and migration is back to `0008`.

**Do not run or reintroduce `0009` on this production application.** This corrective release removes the `0009` migration and reports table from the production SQLAlchemy metadata. The report worker only SELECTs production `signal_outcomes` and uses a **separate SQLite outbox** in the Docker named volume `daily-report-state`. No changes to the production PostgreSQL schema, V4 API image, or API health guard are required. The source repository's Alembic head is again `0008`.

## Delivery state and resilience

- Report ledger is `/var/lib/mv-daily-report/daily-reports.sqlite3` (inside the dedicated named Docker volume).
- Unique primary key: (IST report date, V4 strategy, destination chat ID).
- Payload text and delivery record are frozen at initial claim; subsequent outcomes cannot overwrite an already sent report.
- `pending → inflight → delivered` with Telegram message ID.
- An interrupted in-flight send or provider's ambiguous read/write result becomes `unknown`; **never auto resend**.
- Explicit pre-send connection failures and Telegram 429 can retry at most five attempts.
- Persistent file lock on the same named volume serializes dedicated report processes on the VPS. Do not deploy multiple independent volumes/hosts to the same Telegram destination.
- Keep the volume and any `unknown` state through upgrades. Never use `docker compose down -v` for this stack.
- Do not use `--once` as a preview; it can send if the report is due. Only `--preview-date` is guaranteed read-only.

## Exact release staging and build

This repository is distributed to the VPS as read-only versioned releases. `/opt/mv-signal/app` is a symbolic link to `/opt/mv-signal/releases/mv-signal-0.14.0`, NOT a Git working tree. Never perform `git pull` inside `/opt/mv-signal/app`.

Stage an **exact reviewed commit SHA**, verify it, then build **only the dedicated report image** using `services/api/Dockerfile.daily-report` from that staged checkout. Retain the original `compose.production.yml`, `compose.host-proxy.yml`, `compose.research.yml`, `compose.ai.yml` and the updated **staged** `compose.telegram.yml` in the same Compose invocation. Existing `telegram` and API containers continue to use the `0.14.0` image; the `telegram-report` service exclusively uses `mv-signal-api:0.14.0-daily-report-isolated`.

Before activation:
1. Check production schema **still 0008** and API `/health` is HTTP 200. Confirm engine/telegram/analytics current container IDs.
2. Verify existing `pg_dump` backup, SHA-256 checksum and isolated restore evidence. This report upgrade requires **no new PostgreSQL migration**.
3. Build only `mv-signal-api:0.14.0-daily-report-isolated` using the dedicated Dockerfile; inspect the new image digest.
4. Preview with `python -m app.telegram.daily_report --preview-date YYYY-MM-DD` via a `--rm --no-deps` run and the complete staged Compose overlay; preview must not send to Telegram.
5. Set `MV_DAILY_REPORT_START_AT` to the desired first-session 23:10 IST Unix timestamp in milliseconds, in the existing private `deploy/production.env`. If the due time has already passed, use the *following day's* 23:10 IST timestamp to avoid accidental backfill. Preserve file permissions.
6. Start **only** `telegram-report` with `docker compose up -d --no-deps --no-build telegram-report`. Verify state volume, container/image digest and worker logs.
7. Confirm production DB schema remains `0008`, API `/health` is 200, and existing API/engine/analytics/telegram IDs and startup times are unchanged.
8. After 23:10 IST inspect Telegram delivery and the report's isolated SQLite record/message ID. If state is `unknown`, inspect the destination manually—do not retry blindly.

## Rollback

Stop only `telegram-report`. Keep the **state volume** for deduplication. The production DB schema is never migrated, so no Alembic downgrade and no production service restart is needed.

## Tests

CI runs application tests and builds the isolated report Dockerfile with a no-send preview. Dedicated tests cover IST boundaries, cohort accounting, carryover, safe retry, persistence, duplicate prevention, formatting and omitted-line behavior.
