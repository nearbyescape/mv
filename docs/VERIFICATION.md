# Production release 0.9.2 verification

## 10 October 2026 — V5 archive inventory (research PR #12)

Added `services/api/app/research/v5_archive_inventory.py`, `services/api/tests/test_v5_archive_inventory.py`, and `docs/V5_ARCHIVE_COVERAGE_GATE.md`. The inventory is offline/read-only and labels mere manifest presence as `PRESENT_UNVERIFIED`; it cannot claim source continuity, strategy signals, or profitability. Synthetic/mock-backed tests have been authored but **are not recorded as executed or passed** in this checkpoint. The disposable VPS command and the expected 1,080-cell frozen matrix are documented in the coverage guide. Full 30-coin source completion, replay, execution costs, and V5 evaluation remain pending; no production V4 deployment was performed.


## Release 0.10.0 verification checkpoint

Implemented session boundaries, durable Telegram delivery and operator-only backed-up reset. Local API: 274 passed, 13 PostgreSQL checks skipped in this invocation. Windows web build, lint and TypeScript passed. Real PostgreSQL, Linux image, browser and production reset/destination checks remain pending at this checkpoint. The 9 AM–11 PM IST restriction has not been historically replayed for performance; no profitability claim follows from these correctness tests.


Current verification: 5 October 2026, Windows host with Node 24.14.1/Python 3.14.3, actual Linux Docker containers and the public Ubuntu VPS. Release 0.9.2 (API and web) is live at https://mv.jaleshwarima.com with a running OpenRouter worker and one successful real DeepSeek diagnostic. Telegram remains deferred by the owner; paper observation is canceled. Earlier research observations below are preserved as point-in-time history.

| Check | Actual result | Coverage and boundary |
| --- | --- | --- |
| API pytest, Windows | 235 passed; ten optional PostgreSQL checks skipped | Prior arithmetic/research/access/operations plus twelve AI checks for immutable levels, durable attempts, interruption, evidence tamper, schema/reference rejection, bounded requests and redacted failures; four additional scaling checks cover stream progress/task cancellation, rate-limit recovery, the 30-coin boundary and health during 29 candidate decisions |
| API pytest, Linux image | 235 passed; ten optional PostgreSQL checks skipped | Executed in the new non-root Python production image built on VPS; one upstream TestClient deprecation warning |
| Real PostgreSQL integration | Ten passed separately | Actual disposable schemas, migration through 0005 up/down/reupgrade, concurrent access, singleton/fencing, financial delivery, last-admin/source serialization and AI daily-budget/stale-owner rejection |
| Fresh PostgreSQL installation | Passed | New isolated volume, automatic database init, application role with no superuser/createDB/createRole/replication rights, migration `0004` and BTC/ETH watchlist seeds |
| ESLint and strict TypeScript | Passed | Frontend rules and complete type checking |
| Complete Playwright suite | 70 passed | Desktop/mobile controlled transport, invitation/sign-in, chosen markets with 29 accepted / 31 rejected, exact backend-generated signal evidence, expiry/withdrawal/operator states, history/inbox/research and AI commentary shown alongside frozen levels and hidden after withdrawal; no live-fixture substitution |
| Linux Next standalone build | Passed | Actual pinned Node base image, production build and route generation; no production npm advisories reported by installation audit |
| Invitation regression | 20 repeated desktop/mobile checks passed | Existing interactive sign-in accepts a fragment invitation; token removed from URL; failed login remains unauthenticated. The form is disabled until hydrated. Fragment events retain their destination and transient invitation state remains only in memory |
| Actual private HTTPS path | Eight checks passed | Caddy → Next → FastAPI → PostgreSQL; anonymous redirect/401, real bootstrap owner/viewer, single-use invite, Secure/HttpOnly/Strict host cookie, backend/UI roles, exact-origin 403, disable/session revocation, logout and current measured operations/backup |
| Owner CLI recovery | Passed on validation owner | Server password reset command exercised with private stdin; account sessions revoked; no password printed. Real VPS interactive terminal use remains a deployment check |
| Actual accessibility and visual review | No detected WCAG A/AA violations, page overflow or runtime errors | Private login, overview, members/audit, inbox, history, account and system in desktop/mobile, light/dark; actual captures under `artifacts/production-validation` reviewed. Audit tables scroll horizontally with readable row sizes |
| Real Binance, Linux/PostgreSQL | Four streams warmed and checked | BTC/ETH 1H/4H, 500 completed bars each; latest three OHLCV bars per stream match direct REST; independent Fraction EMA20/50/SMA200/ATR checks within approved 1e-28 relative bound; checkpoint replay bit-for-bit |
| Financial delivery in PostgreSQL | Passed in isolated controlled scenarios | Actual strategy-generated publication: entry 200.1, stop 193.0, target 214.3; frozen evidence/events, notification retries idempotent. These are controlled source scenarios, not live opportunities |
| Actual worker/database recovery | Passed | Duplicate engine rejected; workers stopped/resumed; actual validation database container restarted; readiness recovered, origins/checkpoints/baseline initialization retained. Live plans remained zero before/after; a nonempty live-plan outage was not observed |
| Backup restore | Passed twice, including populated streams | Actual custom-format dump restored into a new temporary database; ten critical tables matched byte-for-byte; original database never overwritten; measured scheduled-backup status current |
| Protected HTTPS read burst | 200 requests, eight concurrent, zero errors | p50 12.06 ms / p95 100.32 ms / p99 2,129.41 ms, max 2,176.74 ms; mixed market/signal/history/inbox/status reads on local Docker, not a VPS/endurance/20-coin capacity claim |
| Private original research exports | Three reports / 17 files passed | Read-only Docker mount, authenticated HTTPS downloads match original backtest/exit/filter report and export bytes; original study/source identities retained |
| CI configuration | Extended, remote execution unverified | Web/API checks plus actual PostgreSQL service tests and Linux image build/test jobs are defined; no GitHub run result claimed |
| Source release | Verified | Original 0.7.0 installed archive had 191 files; 0.8.0 image-build archive had 201; SHA256/per-file manifest, secret/data exclusion, safe extraction and both Linux image builds on VPS passed; later documentation and host backup-helper updates are recorded separately |
| Public VPS deployment | Passed | Domain resolves to 187.127.170.151; trusted certificate issued; owner hello@chaliyaboy.com created their account; measured core ready=true, current backup, streaming collector, ready engine and web delivery backlog zero |
| VPS certificate renewal | Dry run passed | Actual Certbot staging renewal succeeded using MV-only configuration/work/log directories; twice-daily timer enabled and active; existing certificate management unchanged |
| VPS source/indicator checks | Four streams passed | BTC/ETH 1H/4H, 500 bars each; three latest direct Binance OHLCV bars match; independent rational EMA/SMA/ATR within 1e-28 relative bound; checkpoint replay bit-identical |
| Public browser boundary | Passed desktop/mobile | Strict TLS trust, anonymous redirect to login and signals 401, foreign-origin login 403, no detected Axe A/AA violations, overflow or runtime errors; captures in artifacts/vps-validation; no owner password/session minted for checks |
| Real VPS backup restore | Passed before and after AI upgrade | Initial ten-table check passed. Upgraded dump mv-signal-20261004T083425638206Z.dump restored separately with twelve selected critical tables matching, including AI reviews/requests; production never overwritten; backup current |
| Existing website preservation | Passed | Existing bharatedit.com and xtrade.jaleshwarima.com HTTPS both 200; their Nginx configuration SHA256 values unchanged; their containers were not restarted; MV uses loopback 43100 with its own Nginx site and certificate directories |
| VPS research | Three report identities verified | Original baseline/exit/filter reports transferred separately and mounted read-only; integrity checks pass; stopped paper journals and acquisition archives not deployed |
| Actual OpenRouter / DeepSeek | Diagnostic passed | Pinned deepseek/deepseek-v4-pro-0813, real completed Binance snapshots, valid JSON commentary; provider reported 407 prompt / 206 completion tokens and $0.000504628864 cost; durable diagnostic attempt, no signal inserted; key mounted only into AI worker |
| AI deployment/recovery | Passed | Migration 0005, optional Compose worker, heartbeat running, daily usage 1/20, core ready=true after MV-only database/worker restart; independent source/replay recheck passed; no live signal review at the initial 4 October upgrade check; by 5 October eight reviews were complete / two failed safely |
| Remaining integrations/operations | Pending | Longer VPS endurance/hourly-burst capacity, encrypted off-server transport, remote CI and Telegram deferred; eight market-driven reviews observed complete / two failed safely |

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

Repeatable commands: `npm run lint`, `npm run typecheck`, `npm run build`, `npm run test:web`, API `python -m pytest -q`, isolated `tools/check_postgres.py`, `tools/check-production.mjs`, `tools/check-live-postgres.py`, `tools/check-production-recovery.py` and `tools/check-production-research.mjs`. `tools/package_release.py` creates the release; `tools/verify_release.py --build` checks it and builds both Linux images from its extracted sources. Docker validation uses a separate project/database and loopback internal TLS. It does not deploy or issue a public certificate for `mv.jaleshwarima.com`.

Signals in controlled browser/operations fixtures are generated by the backend from isolated source bars, never presented as live Binance entries or written to a live database. Independent arithmetic and real exchange-source checks remain separate. Original historical losses remain unchanged. The source release excludes runtime data, local credentials and research archives; optional verified reports must be transferred separately. Local backup restoration does not establish off-server recovery or high availability.

## Archived Phase 5.2 verification record

The remainder records what had been implemented or unverified at that earlier milestone. Current authentication, PostgreSQL, restoration and production-package evidence is in the table above. The described active paper observer was subsequently stopped by owner request and is no longer a current workflow or release gate.

### Entry filters and forward shadow milestone

Verified locally on Windows, 4 October 2026. Node 24.14.1 / Python 3.14.3. Initial Phase 3 live/network observations were made on 3 October; source/arithmetic comparison was repeated on 4 October.

| Check | Result | Coverage |
| --- | --- | --- |
| API pytest | 189 passed | All earlier arithmetic, migration, live signal, replay, funding, source audit and exit-study tests; independent direction-aware inclusive filters, original controls, protected export/tamper checks, forward Decimal/record checkpoints, entry/target recovery, signed funding, transaction rollback, missing due settlements, observation settling/gaps, code-change and stale/frozen journal guards |
| Playwright | 46 passed | All earlier desktop/mobile checks; 27 filter comparisons, negative results/scenario selectors and exact export transport; six forward sleeves, zero-trade/inconclusive state, frozen unresolved positions, missing/offline/mismatched reports, responsive bounds and accessibility |
| ESLint | Passed | TypeScript and React Hooks recommended rules |
| TypeScript | Passed | Strict frontend type checking |
| Next.js production build | Passed | Compiled application and route generation |
| Browser/API/database integration | Passed | Real browser save, server-side proxy, FastAPI, database, reload; original chosen-coin configuration restored afterward |
| Live Binance verification | Passed | Actual REST and routed market WebSocket connection; BTC/ETH validated and warmed on both timeframes; stream health measured |
| Direct source/indicator comparison | Passed | Latest three OHLCV bars on each of four streams match direct Binance REST; independent rational EMA20/EMA50/SMA200/ATR14 checks pass; all checkpoints match uninterrupted replay bit-for-bit |
| Live continuity | Observed | Original origins retained across restart and overnight gap recovery; 510 completed 1H and 502 completed 4H bars per symbol at the final source check |
| Actual signal worker | Observed healthy | Current BTC/ETH baselines, retained restart cursors, actual BTC long publication at the next hourly close, ETH no fresh trigger, and subsequent reserved-slot expiry |
| Actual quote adapter | Passed at observation | Symbol-specific BTC/ETH public book tickers retain exchange timestamps and pass the five-second age check |
| Signal publication/state integration | Passed in isolated scenarios | Actual backend creates plans/evidence from controlled source bars, commits slots/events and handles operator state without changing levels; not a live Binance opportunity |
| Actual publication/web integration | Passed | Real BTC plan through SQLite/API/proxy/web journal/dialog and intact evidence download; independent rational trigger/risk/tick checks, immutable checksums, five-minute expiry without an operator hold |
| Network recovery | Observed | Actual DNS/network interruption produced reconnect backoff up to 60 seconds, followed by successful REST reconciliation and streaming recovery |
| Cross-origin write boundary | Passed | Foreign-origin configuration and signal-state requests rejected with 403 |
| Axe accessibility | No WCAG A/AA violations detected | Actual desktop overview, explicit Demo setup dialog, dark/mobile overview; controlled signal dialog in desktop/mobile browser tests |
| Dependency audit | No production npm advisories reported | Locked production dependencies, checked 4 October; full-tree audit passed at Phase 4 |
| Visual inspection | Captured and inspected | Actual light/dark desktop/mobile dashboard and explicitly labeled controlled signal dialogs; mobile dialog overflow fixed and regression-tested |
| Actual research data acquisition | Passed | 162 published-checksum archives, exact source validation; 2,370,240 audited minute rows and 4,386 timestamp/rate/associated-mark funding events |
| Higher-timeframe source audit | Passed with disclosed discrepancies | 20 native archive discrepancies retained; consistent completed UTC 1H/4H OHLCV aggregated from validated minutes; independent timeframe seeds, original native files preserved |
| Actual historical replay | Completed | All nine fixed BTC/ETH period/cost experiments; 1,469 overlapping trade records; model and source limitations preserved |
| Replay reproducibility | Passed | Repeated complete final run reproduced every report/export byte exactly; same dataset/spec/strategy/code identity |
| Independent trade arithmetic | Passed for all 1,469 records | Rational entry/confirmation/drift/tick/risk/fill/both-fee/actual-funding/net-P&L checks, group reconciliation and report/export/API integrity |
| Actual Research web integration | Passed | Protected backend → server-only proxy → actual page; report download exactly matched backend; no mocked transport or app console/runtime errors |
| Research visual/accessibility checks | Captured and inspected; no detected WCAG A/AA violations | Actual light/dark desktop and mobile, no page overflow; duplicate limitation rendering warning fixed and regression-checked |

Browser tests mock transport for repeatable state/failure scenarios. Signal fixtures are generated by the actual strategy/service code from controlled source bars in an isolated backend test, with explicit provenance. They are not imported into product code or written to the live database. The capture tool adds a visible test-data label. Separate tools exercise the actual local API/database and Binance network. API tests use isolated SQLite databases; migration tests run real Alembic commands on a temporary database. One upstream TestClient deprecation warning remains; all tests pass.

Research browser fixtures sample a genuine backend report's curves for transport tests only; backend numeric metrics remain exact strings. Product results come from protected report files, never that fixture. The actual research capture uses no mocks. Application/React console errors are checked; fixture tests explicitly allow the 503 resource messages produced by their intentionally unavailable unrelated live endpoints.

At the final 4 October source check, BTCUSDT and ETHUSDT each had 510 completed 1H bars and 502 completed 4H bars. Origins remained 12 September 2026 at 20:00 UTC (1H) and 12 July 2026 at 08:00 UTC (4H). These are this installation's warm-up origins, not an all-time exchange seed. Independent comparison uses exact rational weighted sums and a relative bound of `1e-28`, with the same absolute floor; production arithmetic uses Decimal precision 34.

The collector repaired the overnight gap before the new worker established its current baselines. On 3 October, 1H history advanced from 500 to 501 and a real DNS/network interruption produced backoff followed by successful reconciliation/streaming recovery. Fresh quote observations are point-in-time checks, not guarantees of continuous availability or fills.

## Limits

One actual market-driven BTC long plan was observed for the 4 October 02:00 UTC source close. Publication was at 02:00:03.613 UTC using an exchange quote from 02:00:03.152 UTC. Its reference entry was `84764.90`, frozen stop `84366.30`, target `85562.10` and source ATR `199.2565092693528972785185333117372`. The exact completed 4H evidence opened at 3 October 20:00 UTC. ETH produced `NO_FRESH_RECLAIM_OR_LOSS`.

Read-only verification independently checked the persisted plan with rational trigger/rounding calculations and both checksums. The actual browser journal/detail/download matched the backend evidence. At 02:05 UTC the entry window closed; the worker appended an expired event at 02:05:00.798, released the unaccepted reservation and retained the original plan. Its ID is `d16931da9a624578175172a01ee6e0da19a6c036edf7c6b2e43e10dd64f25163`. No synthetic opportunity or operator hold was inserted into the live database. This single observed latency is not a production percentile/benchmark; this reference plan is not an observed trade or profitability result.

Historical comparisons and forward modeled accounting were exercised in controlled tests. New actual completed-minute observations and a real forward observer restart were checked, but market-driven forward positions/exits/funding, a sufficient unseen sample, 90-day continuity, robust profitability, Telegram delivery, AI inference, production performance benchmarks, PostgreSQL runtime/concurrency, remote CI execution, invite-only authentication, backup restoration and deployment remain unverified. Live reference bid/ask snapshots are not assured fills; live plans exclude fees/funding and do not represent net performance. Research/forward shadow costs and fills are assumptions, with actual settled funding reads. Automated accessibility scans supplement visual/keyboard checks without establishing complete compliance.

## Phase 5 observations and research limits

The final report ID is `0f0a77a2ec4747d1b6a228208fbd11704d30a67052777c4f7500f1f59b16cfdb`; dataset hash is `9f66bc05f0b772985044f3444c2fca57468947233f4b459d4c78066d559f2af2`. Both historical timeframe origins are 1 October 2023 00:00 UTC, distinct from the current live installation. Source discrepancies caused acquisition/replay to stop before results; the minute-aggregation policy was then registered before any performance output. Original source differences are downloadable, not hidden.

Baseline returns were −27.68% in 2024, −17.91% in Jan–Jun 2025 and +1.76% in Jul–Dec 2025; higher final-period costs produced −7.03%. No parameters were tuned against the outcomes. These are separate capital-reset experiments and overlapping cost scenarios, not one compounded account or independent samples. This retrospective chronological split is not a forward unseen market test. See [results](PHASE5_RESULTS.md) and [methodology](PHASE5_BACKTESTING.md).

One-minute OHLC cannot recover intrabar event order or assured fills. Stops win ambiguous bars, adverse stop gaps are modeled, and funding inside a minute precedes its unknown intrabar exit. Historical spreads/slippage/latency are modeled; current dated price filters approximate historical rules. Fractional quantities omit historical quantity/notional filters and liquidation. Drawdown uses hourly contract-price equity after paid costs; open positions exclude hypothetical exit fees. Bootstrap samples contain only six or twelve calendar months. Broader ablations, regime analysis and walk-forward refitting remain future work; statistically sufficient forward paper results remain unobserved.

The finalized WebSocket ingestion path is exercised with controlled messages, and actual market WebSocket connectivity/received-event liveness are verified. Continuous history advancement is corroborated against REST; this milestone does not claim that every observed final bar was acquired through WebSocket rather than the concurrent reconciliation path. Long outage/24-hour renewal behavior and production-scale load still require longer-running failure and endurance tests.

CI definitions are included but have not run on GitHub. Dependency-audit results are a dated automated check, not a guarantee of application security. The local development token is not suitable for production access.

## Phase 5.1 observations

The registered exit study completed 27 experiments and 3,722 overlapping records. All nine baseline control groups and every original trade/evidence matched exactly. The repeated complete study reproduced every report/export byte. Original sources were preserved with their original checksum identity before extension; original report/artifacts and live financial contract remain unchanged.

Independent Fraction checks passed on every trade and all cohort counts, sums, mean R and observed-1R classifications. The actual API/proxy/website returned the exact report and all five evidence exports with matching hashes. Light/dark/mobile captures were inspected; accessibility scans found no WCAG A/AA violations, page overflow or app console/runtime errors. See [study methodology and results](PHASE51_DIAGNOSTICS_AND_EXITS.md). No variant established robust profitability or was promoted; no fresh holdout or forward paper performance was exercised.

## Phase 5.2 and local Phase 6 observations

The filter report `243e7c39c4b2e483fa5f2e64009bbd1b6cff6bf2ff29cc5ff514eb2889e103bb` contains 27 experiments and 2,935 overlapping records. Both filters retain original exits. All nine baseline groups and every original trade/evidence matched exactly; a repeated full study reproduced every report/export byte. Independent Fraction checks passed on every trade, both threshold formulas, risk/rules/grid/fills/fees/actual funding/P&L, group sums and immutable evidence/export/API integrity. The existing exit-study verifier also passed against its preserved source identity after the new extension.

Neither filter established reliable improvement. Original/slope/separation final-period baseline-cost returns were +1.76%/−3.72%/−2.77%; higher costs yielded −7.03%/−7.66%/−7.89%. Earlier periods and all cost scenarios remain visible. No threshold was retuned after this replay and no policy was promoted. Thresholds were informed by prior diagnostics, so these are exploratory tests on already-viewed data.

The first genuine forward sample began 04:37 UTC and froze after six symbol-minutes on a revised early REST close/volume, without positions or trades. Its journal and exact source tree remain preserved. The revised v2 observer requires a 15-second minute-settling delay. It registered six flat sleeves at the future 04:44 UTC minute; actual protected journal checks saw new BTC/ETH observations, contiguous cursors, settling/grace times, immutable hashes and rational cash reconciliation. A real worker restart retained the same sample, flat 5,000 USDT sleeves and durable cursors; no duplicate or old setup was inserted. Current sample ID is `0a409beda8d75fdf94c4bdd35179af2902ff123e5cf6a56b808b35a9aba870b1`. The actual observation count is point-in-time evidence and continues only while the observer remains running.

The actual API → server-only proxy → browser filter/native report download matched the report exactly; all five other export hashes matched. Forward UI read the real six-sleeve journal and displayed the prior frozen sample separately. Light/dark/mobile views were captured and inspected; Axe found no WCAG A/AA violations, no page overflow and no app console/runtime errors. A duplicate limitation key warning was fixed by deduplicating presentation while preserving the report bytes. Fixture export tests fetch mocked transport payloads; actual native downloads are exercised separately because Chromium downloads bypass route mocks in this environment.

Controlled independent tests demonstrate long/short threshold equality, unchanged risk levels, filter independence, precision isolation, pending/open-position JSON recovery, target P&L, signed funding, atomic rollback, duplicate/future/late/gap rejection, due settlement withholding, code identity and stale/frozen/missing/tampered APIs. They do not prove real future trades. No market-driven forward entry, exit or funding charge was observed during these first checks. Source monitoring is bounded, model fills are retrospective to the newly received completed minute's open, and the live seed history differs from historical replay. The 90-day/100-trades-per-policy gate, endurance, sufficient unseen performance and profitability remain unverified. See [methodology and results](PHASE52_FILTERS_AND_FORWARD.md).

```powershell
.venv\Scripts\python tools/verify-filter-study.py
.venv\Scripts\python tools/verify-forward-paper.py
node tools/capture-filter-paper.mjs
```

Browser research/study fixtures sample actual report curves for isolated transport checks. Chromium native downloads bypass route interception in this environment, so fixture tests inspect export links and fetched payloads. Separate actual capture tools exercise native downloads and proxy exports; browser test success does not imply a live Binance fill.

## Repeatable checks

Follow `README.md` for standard checks and the four-process setup. With API, collector, signal worker and website running, use:

```powershell
node tools/check-integration.mjs
.venv\Scripts\python tools/verify-market-data.py
.venv\Scripts\python tools/verify-signal-engine.py
node tools/check-accessibility.mjs
node tools/capture-preview.mjs
node tools/capture-signal-fixture.mjs
node tools/capture-live-signal.mjs
.venv\Scripts\python tools/verify-backtest.py
node tools/capture-research.mjs
.venv\Scripts\python tools/verify-exit-study.py
node tools/capture-exit-study.mjs
```

Reports/images are saved under ignored `artifacts/`, including `live-market-verification.json` and `phase4-engine-verification.json`. Read-only market/engine checks use real network data and intentionally fail if readiness is unavailable; a close-boundary update can briefly be in progress while the worker catches up.

Historical acquisition/replay commands are in `README.md`. The completed dataset lives under ignored `research-data/`; pinned reports/CSV/JSONL/manifest/source audit under `artifacts/backtests/<report-id>/`. Independent rational verification writes `artifacts/backtest-verification.json`. Actual research captures are `research-desktop.png`, `research-dark.png` and `research-mobile.png`. Report verification requires the prepared artifacts and running API; actual browser capture also requires the website. Keep the pinned local dataset to reproduce the exact run if upstream archives later change.

The integration tool temporarily reverses the watchlist and restores it in cleanup. The fixture capture mocks signal transport only in its own browser and never changes live data/slots. The live signal capture requires an actual published plan, uses no transport mocks and reads/downloads it without actions. These tools send no alerts or trades. The website uses loopback port 3100 because another local application occupies port 3000.
