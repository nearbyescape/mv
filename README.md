# MV Signal

A private Binance futures signal workspace: EMA20 + EMA50 + SMA200 + Wilder ATR14. Deterministic backend rules create signals; a separate OpenRouter worker explains immutable evidence asynchronously. No exchange orders are placed.

## Release 0.12.0 candidate — V2 Performance analytics

Release 0.12.0 adds a strictly observational analytics subsystem around the live `MV-TREND-DUAL-v2` strategy. The signal engine and V2 financial contract are unchanged. A separate `outcome-analytics` worker records post-publication reference outcomes from completed Binance 1-minute candles, including MFE/MAE, +0.5R/+1R/+1.5R/+2R milestones, stop/target ordering and conservative same-minute ambiguity handling. It also measures six-hour future movement after `NO_SETUP` decisions in source-ATR units.

Analytics has its own schema tables, worker lease, API namespace and a dedicated **Performance** page. It is deliberately absent from the Overview dashboard and cannot create, suppress, rank or modify a signal. The Performance page separates Pullback LONG, Pullback SHORT, Breakout LONG and Breakout SHORT, adds per-symbol reference statistics, blocker/missed-move diagnostics and CSV outcome export. See [V2 Performance analytics](docs/V2_PERFORMANCE_ANALYTICS.md).

Reference outcomes are not exchange fills, realized P&L or account returns. They are descriptive evidence used to decide whether a later versioned strategy change is justified.

## Release 0.11.0 — MV-TREND-DUAL-v2

Release 0.11.0 is live in direct production with the versioned deterministic `MV-TREND-DUAL-v2` engine. It is not a paper or shadow runtime. V1 code and historical reports remain unchanged for reproducibility.

V2 keeps completed 1H/4H EMA20/EMA50/SMA200/Wilder ATR14 evidence and the existing 2 ATR stop / 2R reference geometry, but adds two explicit setup families: **quality pullback continuation** and **12-bar structural momentum breakout**. The breakout path allows a valid short during a sustained selloff even when the previous candle is already below EMA20, addressing the principal V1 missed-opportunity blind spot. V2 also supports established/emerging trend regimes, ATR-normalized candle/extension quality, a 10 bps live spread ceiling and a BTC contradiction veto for altcoins. Existing 09:00 AM–11:00 PM IST session, quote freshness, source lineage, atomic publication, operator slots, AI commentary and Telegram delivery remain in force.

The strategy ID is new. First production startup baselines V2 at the current completed candle and cannot replay historical candles. Old V1 plans remain visible, and any retained V1 slot blocks a V2 signal for the same coin. See [V2 financial and cutover behavior](docs/STRATEGY_V2.md).

**Important:** implementation of V2 is not evidence of profitability or improved accuracy. Existing V1 research remains negative/fragile and does not validate V2 or the 30-coin universe.

## Release 0.10.0

Phases 6 and 7 are implemented: professional responsive dashboard, live charts, invite-only accounts, administrator/operator/viewer roles, audit history, durable web notifications and complete signal history. The core is deployed at https://mv.jaleshwarima.com with PostgreSQL, transaction-fenced workers, HTTPS, migrations and scheduled backups. Actual VPS owner readiness, independent market arithmetic and separate-database backup restoration passed. Existing websites were preserved. See the [VPS record](docs/VPS_DEPLOYMENT.md) and [chosen-market expansion](docs/CHOSEN_MARKET_SCALING.md).

The domain is **mv.jaleshwarima.com**. Follow the [deployment and recovery guide](docs/PRODUCTION_DEPLOYMENT.md). The owner account is configured and OpenRouter is deployed with a real DeepSeek diagnostic verified. Its key is mounted only into the AI worker; maximum 20 attempts per UTC day, bounded responses/retries and exact immutable-evidence binding. See [AI behavior](docs/PHASE9_AI_REVIEWS.md). Telegram uses a separate server-only worker and fixed verified chat, with a durable outbox, pacing, bounded safe retries and visible uncertain sends. See [Telegram/session/handover behavior](docs/TELEGRAM_SESSION_HANDOVER.md). Paper observation is disabled, stopped and removed from the live workflow; both research journals remain preserved separately.

New signals run daily from **09:00 AM to 11:00 PM IST**, with both source close and publication inside the window. The last hourly trigger is 10:30 PM IST. Collection, expiry and integrity monitoring continue around the clock; off-session setups are never replayed in the morning. Completed 1H candles trigger EMA20 reclaim/loss evaluation with exact completed 4H confirmation. The engine validates a fresh public bid/ask quote and commits rounded, frozen 2 ATR stop / 2R target levels with checksummed evidence. Startup establishes the current baseline and waits for the next completed trigger; historical download never creates retrospective entry opportunities.

The Signal journal defaults to today’s committed backend plans in IST. Use its date picker for earlier days, Today to return to the current day, or All dates for complete history. **Inspect signal** opens its live completed-candle chart with source marker and frozen entry/SL/target, exact evidence, guards, IST timestamps and downloads. Signal charts include Price focus / Full indicator range, broader source context, the latest 96 completed candles and Reset view. Interface times use IST with AM/PM; chart axes and crosshairs follow the same timezone. Entries expire five minutes after source close. **Mark as held** records an operator-reported slot, blocking another setup for that coin until release; it does not prove an exchange position or fill. Full history uses backend pagination. CSV covers the loaded rows, explicitly disclosed. Inbox reads persist per account.

BTCUSDT and ETHUSDT are starting defaults. The owner's live watchlist contains 30 coins; up to 30 are supported. Change chosen coins under **Manage markets**; the collector validates contracts and warms 500 completed bars on each timeframe before readiness. Explicit **Demo data** displays labeled synthetic charts. Missing live data never silently substitutes demo prices. Only the backend strategy engine originates real signals.

Historical **Research** retains fixed BTC/ETH comparisons, costs, actual funding, source provenance and exact exports. The baseline returned −27.68% in 2024, −17.91% in early 2025 and +1.76% in late 2025; higher costs changed the latter to −7.03%. Exit/filter studies did not establish a reliable improvement and changed no live strategy. See [results](docs/PHASE5_RESULTS.md). Reports are optional read-only mounted artifacts on production; missing reports show an unavailable state.

## Run locally on Windows

Requirements: Node.js 24, Python 3.14 and npm. Install from the root:

```powershell
npm ci
python -m venv .venv
.venv\Scripts\python -m pip install -r services/api/requirements.txt
.venv\Scripts\python -m pip install -e packages/strategy
```

From `services/api`, migrate and start the API:

```powershell
..\..\.venv\Scripts\python -m alembic upgrade head
..\..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start four separate terminals from `services/api`, one command in each:

```powershell
..\..\.venv\Scripts\python -m app.market.collector
..\..\.venv\Scripts\python -m app.signals.worker
..\..\.venv\Scripts\python -m app.operations.worker
..\..\.venv\Scripts\python -m app.analytics.worker
```

Allow the initial history download and connection to finish. Run all Python processes from `services/api` so they share the configured database. Collector/engine `--once` is a diagnostic scan and does not claim continuous service. One owner per worker is enforced. Do not start the canceled paper observer.

From the repository root in another terminal:

```powershell
npm run dev
```

Open [local MV Signal](http://127.0.0.1:3100). Development API docs: http://127.0.0.1:8000/docs. Stop processes with Ctrl+C. Local preview uses SQLite and a development token on loopback; this is not production user authentication and must not be exposed publicly.

## Verification

```powershell
npm run lint
npm run typecheck
npm run build
npx playwright install chromium
npm run test:web
cd services/api
..\..\.venv\Scripts\python -m pytest -q
```

Backend checks cover independent indicator/risk/accounting arithmetic, completed-candle alignment, recovery, correction, quote/rounding guards, atomic publication, roles, invitation/session lifecycle, durable notifications and history pagination. Nine optional PostgreSQL checks need `MV_TEST_PG_URL` and use disposable schemas. `tools/check_postgres.py` targets only the isolated local Docker validation stack.

Browser tests mock controlled transport for repeatable states. Signal fixtures are generated by the actual backend strategy on isolated source candles and never enter the product database. Separate tools exercise actual Binance, private HTTPS, PostgreSQL restore/recovery and research export hashes. See the complete [verification record](docs/VERIFICATION.md). Remote CI is configured, not claimed executed.

## Historical research

From `services/api`, with the original data/report directories retained:

```powershell
..\..\.venv\Scripts\python -m app.research prepare
..\..\.venv\Scripts\python -m app.research audit
..\..\.venv\Scripts\python -m app.research run
..\..\.venv\Scripts\python -m app.research exit-study
..\..\.venv\Scripts\python -m app.research filter-study
```

The original acquisition used 162 checksum-pinned archives, 2,370,240 minutes and 4,386 funding events. Twenty native higher-timeframe discrepancies remain disclosed. Canonical research OHLCV aggregates completed UTC minute data with separate seeded indicators. Replay/report directories are isolated from live plans. Keep ignored `research-data`, `artifacts/backtests`, `artifacts/exit-studies`, `artifacts/filter-studies` and `artifacts/baseline-source` to preserve provenance. Independent verifier tools check complete ledgers and exports. Prior forward-paper capture tools are archived research utilities, not the current launch workflow.

## Layout and deployment

| Path | Responsibility |
| --- | --- |
| `apps/web` | Next.js/TypeScript private dashboard and server-side session/API proxy |
| `services/api` | FastAPI, accounts, collector, strategy worker, web delivery, research, migrations |
| `packages/strategy` | Pure Decimal indicators, checkpoints, setup/risk and replay accounting |
| `packages/contracts` | Versioned strategy and fixed research specifications |
| `compose.production.yml`, `deploy` | Private PostgreSQL/Docker/HTTPS/backup deployment |
| `tools` | Independent verifiers, validation harnesses and release/backup utilities |
| `docs` | Phase status, design, research, verification and deployment |

Production requires HTTPS, PostgreSQL, a strong server gateway key and invite-only sessions; partial configuration is rejected. API and database stay inside Docker. The web proxy keeps keys out of browser bundles. Do not put secrets in `NEXT_PUBLIC_*`. Binance public data needs no trading account key.

Next: configure encrypted off-server backups and add Telegram when the owner is ready. VPS endurance, production load capacity and remote CI remain unverified. A real provider diagnostic and controlled signal-review tests passed; no new VPS signal occurred during checks, so its actual AI review remains unobserved. See [build status](docs/BUILD_STATUS.md), [live operations](docs/PHASE67_LIVE_OPERATIONS.md), [deployment](docs/PRODUCTION_DEPLOYMENT.md) and [research plan](docs/RESEARCH_AND_BUILD_PLAN.md).
