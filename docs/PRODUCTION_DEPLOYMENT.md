# Production deployment: MV Signal 0.9.2

The application is deployed on the owner's shared Linux VPS at **https://mv.jaleshwarima.com**. Owner onboarding, public HTTPS, live workers and a separate-database backup restore passed. OpenRouter commentary is running and a real DeepSeek diagnostic passed. Telegram remains deferred by the owner. This release sends web notifications and places no exchange orders. See the [actual VPS record](VPS_DEPLOYMENT.md).

## Current shared VPS: use these operations commands

The installation on **187.127.170.151** already exists. Do not rerun bootstrap or generate replacement secrets. Its existing Nginx owns 80/443; MV binds only loopback 43100. Always include the host, research and AI overrides in operational Compose commands:

```sh
cd /opt/mv-signal/app
docker compose --env-file deploy/production.env \
  -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml ps

# After an intentional MV configuration change:
docker compose --env-file deploy/production.env \
  -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml up -d

# Read-only health diagnostics; never print secret files or environment values.
docker compose --env-file deploy/production.env \
  -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml logs --tail 30 collector engine delivery ai
systemctl status mv-signal-cert-renew.timer --no-pager
```

The same overrides apply to any `exec`, `stop`, `build` or selective `up` command below when operating this VPS. Running only the base Compose file would start the standalone Caddy gateway and conflict with existing websites, and omitting the AI override would remove the API's AI enable flag. Run all lifecycle operations from `/opt/mv-signal/app` consistently; alternating between the symlink and an explicit release path can change bind-mount paths and recreate services. Existing sites and containers are outside MV's operations scope. Secrets/backups/environment live under `/opt/mv-signal/shared`; research mounts from its `artifacts` directory. MV certificates use their own `/opt/mv-signal/tls`, work and log directories. The twice-daily renewal timer and an actual successful renewal dry run are verified.

The remaining installation instructions describe **a new dedicated host using standalone Caddy**. They are not instructions to reinstall or reconfigure the current shared VPS. For another shared Nginx host, use `compose.host-proxy.yml`, adapt the MV-only templates in `deploy/nginx-mv-http.conf` and `deploy/nginx-mv-https.conf`, and preserve the existing default server and certificate management. Validate `nginx -t` before graceful reload. Never replace an existing site's configuration.

## Before installation on a new dedicated host

Use a supported Linux distribution and install Docker Engine with the Compose plugin following [Docker's official installation instructions](https://docs.docker.com/engine/install/). Compose must support `!override` if you run the optional local validation stack. Starting provision: 4 CPU cores, 8 GB RAM and 40 GB disk. This is an initial resource budget for the private BTC/ETH installation, not a measured VPS capacity guarantee. Watch PostgreSQL, candles and backup disk growth before expanding the watchlist.

Point the domain's A record to the VPS. Publish an AAAA record only if that IPv6 address reaches this server. Allow inbound TCP 80/443 and your SSH access. PostgreSQL, the API and worker services have no public host ports in `compose.production.yml`. Caddy requests the real domain certificate after DNS and connectivity work; the local validation certificate does not prove public TLS issuance. See [Caddy's HTTPS prerequisites](https://caddyserver.com/docs/automatic-https).

Extract the release archive into a private directory, such as `/opt/mv-signal`. Verify the accompanying SHA256 before extracting. A release contains application sources, locked dependencies, contracts, scripts and documentation. It excludes local databases, credentials, validation accounts, backups and research archives. Generate fresh secrets on the VPS; never copy the local validation credentials.

```sh
sha256sum -c mv-signal-0.9.2.tar.gz.sha256
tar -xzf mv-signal-0.9.2.tar.gz
cd mv-signal-0.9.2
```

## Install and bootstrap

Run from the release root, as the account that manages Docker:

```sh
cp deploy/production.env.example deploy/production.env
# Set MV_OWNER_EMAIL to the real owner's email in this file.
# MV_SITE and MV_PUBLIC_ORIGIN are already set for mv.jaleshwarima.com.
chmod 600 deploy/production.env
python3 tools/prepare_secrets.py
mkdir -p deploy/backups
chmod 700 deploy/backups
docker compose --env-file deploy/production.env -f compose.production.yml build api web
docker compose --env-file deploy/production.env -f compose.production.yml up -d
docker compose --env-file deploy/production.env -f compose.production.yml ps
```

The secret generator refuses partial replacement or silent rotation. Keep the owner-only `deploy/secrets` directory private. Its individual read-only files must remain readable by unprivileged application containers. Back up these secrets separately with restricted access. Compose secrets are server-side mounted files, not an encrypted secret vault. See [Docker's secret guidance](https://docs.docker.com/compose/how-tos/use-secrets/).

The first PostgreSQL boot creates a restricted application role and an application-owned database/schema. The migration service upgrades to `0006` before the API and workers start. A migration failure stops startup; inspect it rather than deleting the database volume. Never use `docker compose down -v` on production.

Create the first owner invitation on the server, replacing the sample email:

```sh
docker compose --env-file deploy/production.env -f compose.production.yml exec api \
  python -m app.auth bootstrap --email YOUR_OWNER_EMAIL
```

This command prints a private, single-use invitation URL, valid for 24 hours. Open it yourself, confirm the bound email, choose a 15–128 character password and create the owner account. The invitation token is removed from the browser address bar and consumed once. An existing enabled administrator prevents another anonymous bootstrap. Invitations for other members come from **Administration**; copy the link directly to the intended person. There is no invitation email sender in this release.

Roles: **administrator** manages membership and access; **operator** can change chosen markets and report held/released slots; **viewer** reads the workspace. An administrator also has operator permissions. Disabling an account or changing its role revokes its sessions. At least one enabled administrator is retained. Password changes revoke prior sessions. Server recovery uses a private interactive prompt:

```sh
docker compose --env-file deploy/production.env -f compose.production.yml exec api \
  python -m app.auth reset-password --email YOUR_OWNER_EMAIL
```

Do not supply passwords on the command line. Argon2id hashes and opaque session hashes are stored in PostgreSQL. Production sessions use a Secure, HttpOnly, SameSite=Strict host cookie with a 12-hour expiry.

## Launch checks

1. Open the HTTPS domain anonymously: the workspace must redirect to sign-in, and `/api/signals` must return 401.
2. Sign in as owner. Confirm BTCUSDT/ETHUSDT, or select your intended coins under **Manage markets**. Wait for 500 completed candles on each 1H/4H stream and a connected collector.
3. Open **System status**. Collector and engine must be ready, web delivery running, backlog clear, owner configured and backup current. New installs need the first successful backup before full readiness.
4. Check **Signal journal** and **Notifications**. An empty journal is valid: startup records the current baseline and waits for a fresh completed 1H trigger. History download never creates backdated entry opportunities.
5. Invite a viewer, verify it cannot change markets or operate slots, then disable it and verify the session stops working.
6. Confirm logout, password recovery access, disk monitoring and an off-server backup destination. Record actual VPS recovery and latency measurements before broadening the watchlist.

Only the backend creates plans. EMA20/EMA50/SMA200/Wilder ATR14, exact completed 4H alignment, Decimal arithmetic, exchange rounding and frozen 2 ATR / 2R levels remain governed by `packages/contracts/strategy-v1.json`. A quote must pass the five-second age and 0.5 ATR drift limits; unaccepted entries expire five minutes after source close. A held slot records the operator's report, not an exchange fill. No API key for a Binance trading account is needed.

## Backups and recovery

The backup container writes a custom-format PostgreSQL dump on startup and every 24 hours, with SHA256 sidecars. Local retention is 14 days. Backup status is measured separately and becomes stale after 36 hours. Configure encrypted off-server copies during deployment; local copies on the same VPS do not protect against losing that VPS. Monitor failed/stale backups, disk space and external HTTPS uptime.

Create a manual backup:

```sh
python3 tools/backup_database.py
```

For a consistency rehearsal, stop the collector, engine, delivery and AI (when configured), and keep members from writing during the comparison. On the current shared VPS run:

```sh
docker compose --env-file deploy/production.env -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml stop collector engine delivery ai
python3 tools/backup_database.py --verify-restore
docker compose --env-file deploy/production.env -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml up -d collector engine delivery ai
```

The verifier creates a uniquely named temporary database, restores the dump there and compares nineteen selected critical tables byte-for-byte on schema 0006 (eighteen on schema 0005; ten in the original core implementation). It never restores over `mv_signal` and deletes only the temporary database it created. The scheduler provides backups without stopping workers; the stop above is for comparing restored rows against a stable source. Ensure workers resume even if a rehearsal fails.

For an actual outage, retain a copy of the failed database and secrets, validate the backup checksum, and restore into a separate recovery database first. Review plans, slots, events, indicator seeds/checkpoints and cursors before switching the application. A missed or stale setup must expire; never manufacture an entry to make up for downtime. Restored records may be older than an operator's actual position, so reconcile held slots manually before reopening entry actions. Production database restoration is an attended operation, not an automatic overwrite.

## Maintenance and upgrades

Set `MV_MAINTENANCE=true` in `deploy/production.env`, then recreate the API and engine. This blocks new publication and entry holds; collector ingestion, existing expiry/revision handling, reads and slot release remain available. Recreate all services after removing maintenance.

```sh
docker compose --env-file deploy/production.env -f compose.production.yml up -d api engine
```

Before an upgrade, record current image IDs, take a verified backup and preserve the preceding release/images. Apply migrations through the migration service; never automatically downgrade financial or identity tables. Roll back application images only when their schema compatibility is known. Keep Caddy's persistent certificate data and PostgreSQL's persistent volume. Worker locks and transaction fencing prevent concurrent owners from committing, but they do not make a single VPS highly available.

Protected status gives collector/engine freshness, delivery heartbeat/backlog and backup state. Public `/health` returns minimal database/schema health; API documentation is disabled in production. Logs are bounded in Docker. Detailed readiness remains authenticated; use a private monitoring account or the owner UI for it. Persistent external alerting and off-site backup transport require the deployment provider configuration.

## Historical research, AI and Telegram

If you want the existing verified historical reports visible on the VPS, copy only `artifacts/backtests`, `artifacts/exit-studies` and `artifacts/filter-studies`, including their `latest.json` pointers. Add `-f compose.research.yml` to the Compose commands to mount the reports read-only. The API validates hashes before returning reports/exports. Missing reports show an unavailable state. Research acquisition data and both stopped paper journals are excluded from the release; preserve the originals separately. Paper observation is disabled and removed from the live workflow by owner request.

OpenRouter is implemented and deployed through `compose.ai.yml`. Its key lives in the private shared secret directory and mounts only into the AI worker. The API gets an enable flag. AI receives immutable evidence after publication; bounded requests/retries/provider prices cannot alter financial levels or delay deterministic web delivery. A real DeepSeek diagnostic passed using retained market snapshots, with no signal insertion. See [AI design and bounds](PHASE9_AI_REVIEWS.md). A new VPS signal's actual AI response has not yet been observed.

For a new host, configure the `openrouter_key` secret before adding the AI override; omit the override when no AI key is configured. Telegram is deferred by the owner. When ready, implement BotFather linking and durable Telegram retries consuming committed events, verify real sending, and keep its token server-side.

## Evidence and remaining deployment gates

Local Linux Docker checks include PostgreSQL cold installation/migrations, restricted database role, actual BTC/ETH REST/WebSocket ingestion, independent Fraction indicator checks, checkpoint replay, private HTTPS access, session revocation, source/publication serialization, database restart recovery and backup restore comparison. A 200-request protected read burst at eight concurrent clients had zero errors: median 12.06 ms, p95 100.32 ms and p99 2,129.41 ms. This is a short local Docker measurement, not a VPS service-level promise or a 20-coin capacity result.

Public domain/ACME issuance, renewal dry run, owner onboarding, actual VPS live indicators, upgraded twelve-table backup restore and a real AI diagnostic are verified. VPS performance/endurance, remote CI execution, off-server encrypted backup transport, Telegram sending and a market-driven VPS signal's AI response remain unverified. The prior historical strategy losses remain published; application correctness is separate from profitability. See `docs/VERIFICATION.md` for the test record and `docs/BUILD_STATUS.md` for phase completion.

## Chosen-market expansion

Release 0.8.1 supports at most 30 selected markets. The owner's actual VPS list has 29 validated coins, each with completed 1H/4H history. Stream reading continues while one sequential REST reconciliation runs, and quote operations are bounded with health updated between candidate decisions. Short 29-market checks, independent arithmetic, preservation of existing origins and backup restoration are recorded in [scaling evidence](CHOSEN_MARKET_SCALING.md). Keep the twenty-attempt daily AI cap unless deliberately changing the approved budget. Monitoring more coins does not call AI continuously.

## Display timezone and signal context

Release 0.9.0 adds IST presentation and a protected read-only signal chart endpoint; no migrations or strategy changes are required. Only API/web were replaced on the actual shared VPS. See [release verification](IST_SIGNAL_CHARTS.md).

Web release 0.9.1 corrects signal-chart scale/window readability. API remains 0.9.0. On the shared VPS only web was recreated, preserving all other container identities. Use the complete existing Compose overrides and `up -d --no-deps web` for this presentation-only rollout. See [verification](SIGNAL_CHART_READABILITY.md).

Release 0.9.2 adds protected IST publication-date filtering. No schema or financial strategy change is needed. The actual shared VPS rollout replaced only API/web using the complete Compose overrides and `up -d --no-deps api web`; unchanged background workers retain their prior image. See [verification](JOURNAL_DATE_FILTER.md).

## Telegram and daily operating session

Production enables the versioned 09:00 AM–11:00 PM IST generation window; collection remains continuous. For Telegram, include `-f compose.telegram.yml` after existing overrides, configure the numeric chat/activation timestamp, and mount only the worker secret. Preflight and explicit test-message commands, ambiguous-send handling and the backed-up operator reset are documented in [Telegram/session/handover](TELEGRAM_SESSION_HANDOVER.md). Pause the Telegram worker along with other MV writers for a stable backup restoration comparison. Always include the existing host-proxy override on the shared VPS; do not start the base gateway.
