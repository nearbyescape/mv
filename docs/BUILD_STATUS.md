# Phased delivery status

Milestone: **6 October 2026 — release 0.13.0/schema 0008 is deployed and its V3 engine is running; release 0.14.0 MV-TREND-DUAL-v4 is under validation**. V4 preserves the V3 financial core and adds completed BTC 15-minute timing, a two-signal same-direction source-close cap and a deterioration-triggered directional circuit breaker. V2/V3 history remains preserved.

| Phase | Status | Exit evidence |
| --- | --- | --- |
| 1. Requirements | Baseline documented | Versioned EMA-PULLBACK-ATR-v1 contract and chosen-market defaults |
| 2. Foundation and access | Implemented; exercised locally and in Linux Docker | Migrated database, server-only gateway, invite-only sessions, roles and audit |
| 3. Market data and indicators | Implemented; actual Binance verified | BTC/ETH 1H/4H streams, 500-bar warm-up, independent arithmetic, checkpoint replay and restart recovery |
| 4. Signal engine | Implemented; live and controlled checks passed | Actual earlier BTC publication/expiry; deterministic quote/risk/evidence; PostgreSQL publication/source serialization |
| 5. Backtesting | Implemented and exercised; profitability not established | Pinned sources, actual funding, costs, independent complete-ledger checks |
| 5.1. Diagnostics and exit studies | Implemented; no policy promoted | 27 experiments, exact original parity, independent accounting |
| 5.2. Independent entry filters | Implemented; neither established improvement | 27 experiments, 2,935 checked records, original live strategy unchanged |
| 5.3. V2 live outcome analytics | Implemented in 0.12.0 source; deployment pending | Isolated reference outcomes, R excursions, four setup/direction cohorts and six-hour NO_SETUP diagnostics |
| 6. Durable live operations | Implemented and verified in Linux Docker | PostgreSQL ownership fencing, committed web notifications, heartbeat/backlog, recovery, maintenance and backup status |
| 7. Private website | Implemented and verified | Responsive light/dark design, invitations/accounts/roles, administration, audit, full history and inbox |
| 8. Telegram | Implemented; deployment checks pending | Server-only bot secret, fixed destination, durable fenced outbox, rate limits, sanitized errors and uncertain-send protection |
| 9. DeepSeek / OpenRouter | Implemented and deployed; real signal reviews observed | Pinned model, isolated fenced worker, durable daily request/retry bounds, schema/reference validation and commentary UI; eight accepted real signal reviews; two failed commentary attempts are labeled |
| 10. Hardening and hosting | Core deployed and checked on VPS | Public trusted HTTPS, owner onboarding, live PostgreSQL/market workers, VPS backup restore and preservation of existing websites; endurance/off-server transport remain pending |
| 11. Forward paper pilot | Canceled by owner; originals preserved | Observer stopped, default disabled, omitted from live workflow; no continuity or assessment claim |

## Release 0.14.0 V4 market-safety candidate

Implemented on `codex/mv-v4-market-safety-governor`: V4 keeps V3 setup/risk arithmetic and adds a fail-closed BTC completed-15m timing veto, deterministic candidate ranking, a maximum of two same-direction publications per exact 1H source close and a two-hour directional circuit breaker after two recent signals reach -0.5R before +0.5R. Market Safety Mode is exposed on the signal feed and web workspace. BTC 15m is collected only for BTCUSDT. No schema migration is required beyond live schema 0008.

The V4 implementation is a safety response to observed correlated clustering, not a profitability claim. Production remains on V3 while the V4 candidate passes CI, packaged-image and controlled VPS gates. See [V4 strategy contract](STRATEGY_V4.md).

## Release 0.13.0 V3 production release

Implemented on `codex/mv-v3-anti-chase-multi-tp`: the candidate registers `MV-TREND-DUAL-v3`, schema 0008 and 0.13.0 images. V3 keeps the V2 trend/setup architecture but tightens EMA20 extension, adds a six-hour 2.50 ATR recent-run guard at source and live entry, suppresses repeated same-direction publications for the same symbol during one IST session, and publishes TP1/TP2/TP3 at nominal +1R/+1.5R/+2R with 30/30/40 reference allocation. Web, chart and Telegram surfaces expose the three targets. V2 source/history remain preserved.

Release 0.13.0 passed CI, package/build and controlled schema 0007→0008 cutover gates. Its engine was intentionally left stopped before first production scan while V4 safety work began. See [V3 strategy contract](STRATEGY_V3.md).

## Release 0.12.0 observational outcome analytics

Implemented on a separate branch without modifying `MV-TREND-DUAL-v2` rules. Migration 0007 adds `signal_outcomes` and `decision_opportunities`; the dedicated `outcome-analytics` worker is fenced independently and is never imported by the signal engine. Published V2 plans are measured from the first uncontaminated completed Binance 1-minute candle after publication. MFE/MAE and R milestones are retained with conservative same-minute stop/target ambiguity. Six-hour `NO_SETUP` diagnostics use future completed 1H candles and source ATR only, with no hypothetical fill/P&L claim.

The web UI exposes analytics only under a dedicated **Performance** navigation section. Overview does not render or request analytics. See [measurement contract](V2_PERFORMANCE_ANALYTICS.md).

## Release 0.11.0 V2 production strategy

Implemented in source on a dedicated branch: `MV-TREND-DUAL-v2` keeps completed 1H/4H EMA20/EMA50/SMA200/Wilder ATR14 evidence, the existing 2 ATR stop / 2R reference geometry, the registered IST session and all durable publication/Telegram/AI guards. It adds quality-controlled pullback continuation plus 12-bar structural momentum breakout, established/emerging trend regimes, ATR-normalized candle/extension checks, a 10 bps spread ceiling and a BTC contradiction veto for altcoins.

The strategy identity is distinct from V1. First V2 startup baselines every ready symbol at the current head, so no historical V2 opportunity is replayed. The V2 worker ignores V1 pending rows and checks active slots across strategy versions. V2 structure and BTC regime source snapshots are checksummed and revision-monitored.

The old V1 strategy module/contract and research pipeline remain unchanged so historical reports stay reproducible. No schema migration is required. V2 is now active production. Its implementation remains **not** a profitability claim; outcome evidence is collected separately. See [full V2 behavior](STRATEGY_V2.md).

## Release 0.10.0 client handover, Telegram and daily session

Implemented: separate versioned IST-DAY-v1 operating policy permits new signals only when both the completed source close and publication fall inside 09:00 AM–11:00 PM IST (close exclusive). Hourly Binance closes make 09:30 AM the first eligible close and 10:30 PM the last. Closed-session decisions become terminal SKIPPED; no morning replay. Market collection, expiry and source-revision checks continue. A paused session is operationally healthy when the collector and worker are current. Financial strategy-v1, indicator arithmetic and risk formulas are unchanged. The policy is bound to each new plan/evidence checksum.

Implemented: optional Telegram-only secret mount, destination preflight, one-time explicit setup test, independent fenced outbox, fixed entry/SL/target messages, activation cutoff, four-second pacing, bounded safe retries and withdrawal alerts for previously delivered/uncertain signals. Ambiguous network sends or interrupted in-flight jobs become unknown and are never blindly repeated. AI does not delay Telegram. Protected operations show delivery counts; the dashboard distinguishes session pause from service failure.

Authorized handover reset removes all generated decisions/plans/slots/events, web notifications/read receipts, AI reviews and Telegram outbox records after backup verification. Accounts, login sessions, invitations, settings, watchlist, candles/checkpoints, engine cursors, security audit and research are preserved. AI paid-request/cost records are retained with signal references cleared, so reset cannot reset the durable daily limit. Cursors advance to the retained checkpoint head to prevent replay. Reset and destination deployment verification remain pending here; see [operating behavior](TELEGRAM_SESSION_HANDOVER.md).

Local: 274 API tests pass; 13 real PostgreSQL tests require a separate invocation. Lint, TypeScript and Windows build pass. Browser and Linux/PostgreSQL/deployment verification are pending at this packaging checkpoint. Session-filter profitability and sustained Telegram delivery are not claimed.

## Release 0.9.2 journal date filter

Deployed 5 October: the full Signal journal defaults to Today in IST. A date picker retrieves earlier publication days, Today follows IST midnight, and All dates preserves complete history. The protected backend filters indexed publication timestamps before pagination; stored UTC timestamps and frozen risk/evidence are unchanged. Date changes reset loaded pages and ignore stale responses. Market/direction/search/CSV continue to compose with the selected date. Overview's recent plans and the latest-25 Evaluation log retain their existing scope. See [behavior and verification boundaries](JOURNAL_DATE_FILTER.md).

235 API tests passed on Windows and in the new Linux image; ten optional PostgreSQL checks were skipped in these invocations, with the earlier ten real PostgreSQL integration checks retained separately. The complete browser suite passed 70 checks; eight operations checks were repeated after the final responsive/selected-market refinements in an America/Los_Angeles browser timezone. Lint, strict TypeScript and Windows/Linux production builds passed. Controlled captures were reviewed on desktop/mobile.

Actual VPS PostgreSQL reads returned seven plans for 5 October IST, three for 4 October and ten for All dates. Two-row cursor pages matched independent native SQL order/count without duplicates or changed payloads. Only API/web were recreated; 19 other running containers retained IDs/start times, including every background worker, PostgreSQL and other websites. All ten original plans were preserved; core and 29 markets remained ready with zero web backlog. New CSS/client bundle were checked through trusted HTTPS. Public desktop/mobile checks passed; anonymous dated history returned 401 and foreign-origin writes 403. No owner session was minted. Both existing websites returned HTTPS 200 with unchanged Nginx checksums. Financial contract and schema remain unchanged; Telegram and longer endurance remain pending.

## Release 0.9.1 signal chart readability

Deployed 5 October: Latest candles now initially shows the latest 96 completed bars, independently of the source marker. Signal start shows broader context. Price focus scales visible candles and frozen risk levels; Full indicator range includes every selected overlay in scaling. Active buttons, Reset view, retained indicator values and a separate Last close prevent ambiguous labels. The source marker is compact and has right-hand space. IST AM/PM remains in place. See [behavior and verification boundaries](SIGNAL_CHART_READABILITY.md).

66 desktop/mobile browser checks passed; all 20 signal checks were repeated after the final compact marker label. Lint, strict TypeScript, Windows/Linux production builds and 230 Windows API checks passed; ten optional PostgreSQL checks were skipped in this invocation. Actual retained WLD data was rendered on desktop/mobile through isolated local browser transport and visually reviewed. No authenticated owner session was minted.

Only web was recreated. Twenty other running containers retained IDs/start times, including API, every worker, PostgreSQL and other websites. All ten existing plan payloads/hashes were preserved. Core and 29 markets remained ready with zero web backlog. Published CSS and the actual chart JavaScript bundle were checked through trusted HTTPS against the running image. Anonymous access, origin rejection and public desktop/mobile browser checks passed. Both existing websites returned HTTPS 200 using curl and retained their Nginx checksums; one urllib bot request returned 403 without any website change. Web is 0.9.1, API remains 0.9.0 and background workers remain on their unchanged image. No schema, financial strategy, indicator arithmetic or AI request policy changed. Telegram and longer endurance remain unverified/deferred.

## Release 0.9.0 IST and signal charts

Deployed 5 October: interface clocks/dates use Asia/Kolkata with AM/PM and IST labels; stored epochs and exchange boundaries are unchanged. Inspect signal now opens a polling completed-candle chart with its source marker, frozen entry/SL/target, default EMA20/EMA50/SMA200 lines and ATR14. Source/Latest views preserve historical context and distinguish stale/offline/withdrawn data. See [full implementation and verification boundary](IST_SIGNAL_CHARTS.md).

230 API tests passed on Windows and Linux, 64 desktop/mobile browser checks passed, and lint/TypeScript/builds passed. Both windows were exercised against all ten actual VPS plans in PostgreSQL; original plan payloads/hashes were preserved. Nineteen other running containers retained identities/start times; collector/engine/delivery/AI/database and existing websites were uninterrupted. Core remained ready with 29 ready markets and zero backlog. Eight real signal AI reviews were complete; two failed safely. Telegram remains deferred. Profitability and longer endurance are unverified.

## Release 0.8.2 chart layout fix

The 29-coin sidebar previously enlarged the shared grid row, stretching the chart vertically through `height:100%` and flexible chart sizing. Overview and Chosen markets now align panels at the top; the chart has a bounded viewport-based desktop height (395–560 px) and fixed responsive heights (360 / 330 px). The coin list scrolls within 360 px, retaining the header, management controls and all 29 keyboard-accessible market buttons.

Sixty desktop/mobile Playwright checks passed, including an explicit three-to-29-coin regression: chart height stays unchanged on both pages, the last coin remains reachable by keyboard and no horizontal overflow occurs. Controlled transport screenshots were reviewed on desktop/mobile; they verify presentation, not live signal arithmetic. ESLint, strict TypeScript, Windows and VPS Linux standalone builds passed. API regression: 227 passed / ten optional PostgreSQL tests skipped in this invocation; the earlier ten real PostgreSQL checks remain separate evidence.

Only the web service was recreated for deployment. API/collector/engine/delivery/AI/database and all existing website container identities/start times were preserved (20 other running containers compared). Live core remained ready with 29 ready markets and zero web backlog. Public HTTPS assets contain the new chart/list rules; existing sites returned HTTPS 200 with unchanged Nginx checksums. API image remains 0.8.1 and financial strategy/schema are unchanged. The initial web-build archive SHA256 was `5d2f88a9d62db91f179c21db6f90620c5205342256bd64812583342e8def8e5b`; final documentation/source hashes are refreshed separately.

## Release 0.8.1 chosen-market expansion

All 27 owner-supplied additions are activated: **29 chosen coins, 58 ready streams, 29 engine cursors** and 29,002 retained completed bars. All streams passed direct Binance OHLCV comparison, independent rational indicators and exact checkpoint replay. Following the subscription transition, 44 consecutive samples over 215.53 seconds stayed ready with no reconnects or web backlog; two complete REST reconciliation log spans were 10.598 / 10.984 seconds. Twenty sequential all-market database view reads measured median 90.77 ms / maximum 129.31 ms, excluding HTTPS/authentication/browser. These short checks do not establish endurance or hourly-burst capacity.

The expanded database restored separately with twelve selected tables matching. Public desktop/mobile checks passed again and existing sites remained unchanged. At the 4 October expansion check, VPS signal count was zero; new symbols established startup baselines, while BTC/ETH's most recent completed hour had no fresh reclaim/loss setup. At that 4 October check, AI was running at 1/20 daily requests; Telegram was deferred. See [full scaling evidence and ordered watchlist](CHOSEN_MARKET_SCALING.md).

## Implemented

- Deterministic EMA20/EMA50/SMA200/Wilder ATR14 engine, completed exact 1H/4H alignment, original seed/checkpoint preservation, Decimal exchange rounding, quote age/drift/expiry guards and frozen risk/evidence.
- Atomic decisions/plans/slots/events, no retrospective startup entries, operator-reported holds/releases, expiry and source-correction withdrawal. Immediate evidence reads prevent action when saved lineages differ from current sources.
- Chosen-market public Binance collector with backfill, WebSocket, REST reconciliation, fail-closed freshness/gaps and checkpoint replay. Release 0.8.1 accepts up to 30 selected coins and keeps receiving stream events during one background sequential REST reconciliation; engine quotes have a ten-second bound and health refreshes between candidate decisions.
- PostgreSQL singleton advisory ownership plus transaction-row fencing; per-symbol source/publication locks prevent overlap with ingestion. Losing ownership terminates workers.
- Durable event-to-web-notification delivery, idempotent retry, per-account reads, stable full-history/inbox cursors and exact evidence/loaded-row CSV exports.
- Server bootstrap, single-use email/role-bound invites, Argon2id passwords, hashed opaque sessions, persistent throttling, expiry/revocation/password rotation and last-administrator protection.
- Administrator/operator/viewer enforcement, account management, invitation revoke, audit log, responsive sign-in/account/administration and measured system status. Secrets stay server-side; production uses a Secure/HttpOnly/Strict host cookie and exact-origin writes.
- Linux Docker deployment for the specified domain, pinned base images/dependencies, private database/API, unprivileged app containers, bounded resources/logs, schema-gated startup, daily backups/checksums, restore verification and maintenance controls.
- Portable source release at `artifacts/releases/mv-signal-0.7.0.tar.gz`: SHA256 sidecar and per-file manifest, verified local-secret exclusion and safe extraction. The installed 191-file archive was checksum-verified and both Linux images built on the VPS. Later deployment documentation updates are recorded separately.
- Shared-VPS deployment uses the existing Nginx with an MV-only site, certificate and renewal timer. `compose.host-proxy.yml` binds web only to 127.0.0.1:43100 and excludes the standalone Caddy gateway. Existing site configuration checksums remained unchanged and both existing HTTPS sites returned 200.
- Prior reproducible research and negative sensitivity results retained. Optional reports mount read-only and pass integrity checks before exports. Neither exits nor filters changed live v1.
- Disabled paper workflow with both research journals retained. Telegram remains not-configured and makes no sends. Exchange orders remain disabled.
- Separate OpenRouter commentary worker, migration 0005, immutable plan/evidence binding, failed/revised fallback, bounded provider price/output/response limits and durable maximum 20 attempts per UTC day. The key is mounted only into the AI worker. One actual DeepSeek diagnostic used retained market snapshots without creating a signal; the API-reported cost was $0.000504628864. See [AI design and bounds](PHASE9_AI_REVIEWS.md).

## Demonstrated

230 backend tests passed on Windows and in the new Linux image. Ten optional PostgreSQL tests passed separately against real PostgreSQL: migration up/down/reupgrade, concurrent invitation acceptance/login budgets, worker ownership/handoff rollback, atomic financial publication/delivery, last-administrator concurrency, observed source-lock serialization and AI request-budget/ownership fencing. All 64 desktop/mobile browser tests passed, including invitations, controlled engine evidence, complete history, inbox failure handling, AI commentary visibility/withdrawal and accessibility. ESLint, strict TypeScript and production builds passed. Current production checks are recorded in [verification](VERIFICATION.md).

Actual Linux Docker BTC/ETH collection warmed all four 1H/4H streams. Their latest three OHLCV bars matched direct Binance REST; independent Fraction EMA/SMA/ATR calculations passed within the approved 1e-28 relative bound. Saved checkpoints matched uninterrupted replay bit-for-bit. This installation established fresh baselines and generated no retrospective plans. The separate original SQLite installation's actual BTC long at the 4 October 02:00 UTC close and five-minute expiry remain historical observations, not a new Docker trade.

The production-configuration private HTTPS path was exercised through Caddy → Next → FastAPI → PostgreSQL: anonymous access denied, actual owner/viewer invitations, role restrictions, Secure cookie, cross-origin rejection, account-disable revocation and logout. Daily backup metadata became current. A dump restored into a separate temporary database with all ten critical tables matching byte-for-byte. Fresh database creation/migrations and the non-superuser application role were checked independently.

Duplicate engine ownership was rejected. Stopping workers and restarting the real validation PostgreSQL container recovered readiness while retaining seed origins, checkpoints and baseline initialization. A local protected-read burst of 200 requests at eight concurrent clients had zero errors: p50 12.06 ms, p95 100.32 ms, p99 2,129.41 ms. This short Windows-hosted Linux Docker measurement does not establish VPS latency, 20-coin capacity or endurance.

The original historical baseline's net returns remain −27.68% (2024), −17.91% (early 2025), +1.76% (late 2025), with −7.03% under final-period higher costs. Original/control/source hashes remain intact; robust profitability was not established. Paper journals were stopped/preserved rather than reset or presented as continuous observations.

## Deployment and unverified work

Public DNS, trusted TLS issuance/renewal dry run, owner onboarding and core readiness are verified on VPS 187.127.170.151. All four BTC/ETH 1H/4H streams had 500 completed bars: latest three bars matched direct Binance, independent rational indicators passed and checkpoint replay was bit-identical, including after the upgrade's MV-only database/worker restart. The upgraded VPS backup restored into a separate database with all twelve selected critical tables matching, including both AI tables. Original historical reports are mounted read-only and integrity checked. See [VPS deployment record](VPS_DEPLOYMENT.md).

Actual VPS hourly-burst throughput/endurance, off-server encrypted backup transport and remote CI execution remain unverified. CI defines PostgreSQL and container checks, but no remote run is claimed. Telegram remains deferred. The first 4 October checks had no VPS signals. By 5 October, ten plans were published; eight real AI reviews were complete and two failed safely. Signal accuracy/profitability remains unestablished. Multi-host failover, account-executable fills, quantity/leverage/liquidation sizing and automatic orders are outside this release.

The chosen 29-coin watchlist, 1H/4H and fixed 2 ATR/2R levels remain strategy assumptions. A software release does not prove returns. Historical revisions are not rescanned indefinitely: periodic engine scanning covers the latest 100 plans and all active slots; reading any plan additionally checks its saved source lineages. Browser floats only format displays. A running engine or ready market does not imply a trigger; only committed backend plans are signals. Held slots are operator reports.

See [deployment runbook](PRODUCTION_DEPLOYMENT.md), [live architecture](PHASE67_LIVE_OPERATIONS.md), [verification](VERIFICATION.md), [research results](PHASE5_RESULTS.md) and [strategy design](PHASE4_SIGNAL_ENGINE.md).
