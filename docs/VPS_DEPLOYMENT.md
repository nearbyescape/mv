# VPS deployment record — 5 October 2026

Release **0.9.2** (API and web) is deployed at **https://mv.jaleshwarima.com** on **187.127.170.151**. Owner **hello@chaliyaboy.com** accepted the private invitation and chose their own password. Core readiness passed after onboarding and the AI upgrade. OpenRouter is running and one real DeepSeek diagnostic passed. Telegram remains deferred by the owner; no Telegram message is claimed.

## Installation and isolation

Ubuntu 24.04.5 LTS, existing Docker/Compose 5.5.1 and Nginx 1.24 were used without upgrading packages, restarting the host or changing Docker daemon configuration. The dedicated SSH key has fingerprint `SHA256:/hnNjU7z0VobUBWZMredn3xdZvCavph7flXTX9ez6/E`. Its private key remains on the owner's Windows computer; no password or API credentials appear in the release.

Application: `/opt/mv-signal/app` points to `/opt/mv-signal/releases/mv-signal-0.9.2`; previous 0.7.0/0.8.0 release images are retained. Fresh server secrets, production environment and backups live under `/opt/mv-signal/shared`. Original core archive SHA256 is `ba16473111a27f418b5766bbc929f380f24f71447e8b013f0f43f86fa6a8f3b6` (191 files). The 0.8.0 image-build archive SHA256 is `220684a3db9951e44a6cede7f08aaf298f731d87bb772368aa01a17c02cd77fc` (201 files). Both new images built and 223 backend tests passed in the new image on this VPS. Later documentation and host backup-helper updates do not replace running image code.

Compose project `mv-signal` has its own PostgreSQL volume and services. Web binds **127.0.0.1:43100**; API and database have no public host ports. Always use the shared-host override and read-only research override:

```sh
cd /opt/mv-signal/app
docker compose --env-file deploy/production.env \
  -f compose.production.yml -f compose.host-proxy.yml -f compose.research.yml -f compose.ai.yml ps
```

Nginx owns public 80/443. MV's file is `/etc/nginx/sites-available/mv.jaleshwarima.com`, enabled as `zz-mv.jaleshwarima.com` to preserve the preceding HTTPS default host. Only MV's file/link was added; configuration was tested before graceful reload. Standalone Caddy is excluded. Do not run this VPS with only the base Compose file, which would attempt to bind 80/443.

Existing sites remained available with HTTPS 200, without restarting their containers. Their Nginx configuration checksums stayed unchanged:

| Existing site | SHA256 |
| --- | --- |
| bharatedit.com | c60b1047dac6faf533abded17d6132bca207e004a62dd6a41ad2ec45a4e753ac |
| xtrade.jaleshwarima.com | e06fe2e46dbf2ddc0cddcb0f4f02d75247be5d6c4d62205219f6e92f142f74c8 |

## Observed checks

- Public domain resolves to the VPS. Trusted HTTPS certificate issued 4 October, expires 2 January 2027. Separate Certbot configuration/work/log directories under `/opt/mv-signal` and an MV-only `mv-signal-cert-renew.timer` preserve existing certificate management. Renewal is scheduled twice daily with jitter. Actual Certbot renewal dry run succeeded; the timer is enabled/active.
- At 08:11 UTC (13:41 IST), public desktop/mobile Chromium checks used strict certificate validation. Anonymous requests redirected to sign-in; signals returned 401; foreign-origin login returned 403. Axe found no A/AA violations, and no viewport overflow or app runtime errors were detected. Screenshots/report are under ignored local `artifacts/vps-validation`.
- Core ready=true, enabled owner configured, collector streaming, engine ready, web delivery running/backlog zero, AI worker running/one request of twenty, scheduled backup current, paper disabled and orders disabled. Post-upgrade final health/source check passed at 08:35 UTC (14:05 IST). This is point-in-time health, not an endurance guarantee.
- All four BTC/ETH 1H/4H streams retained 500 completed bars. Last three OHLCV bars per stream matched direct Binance REST. Independent Fraction weighted-sum EMA/SMA/Wilder ATR passed the approved 1e-28 relative bound, and all saved checkpoints matched uninterrupted replay bit-for-bit. 1H origin is 1789300800000; 4H origin is 1783900800000. Fresh baseline initialization creates no retrospective signals.
- Original baseline, exit and filter report identities verified after a separate transfer and read-only mount: `0f0a77a2ec4747d1b6a228208fbd11704d30a67052777c4f7500f1f59b16cfdb`, `53156bdc0dc9962c54d59b080bcb104d748f5057c9ffb0c6c590921073831e40`, `243e7c39c4b2e483fa5f2e64009bbd1b6cff6bf2ff29cc5ff514eb2889e103bb`.

## Backup evidence and remaining work

VPS dump **mv-signal-20261004T080304159945Z.dump**, SHA256 **6eff2c3965041ce3c79b968f26dc1f51755bcdf9cf603c62fc7fc30008960fd2**, restored successfully into a newly named temporary database with all ten critical tables matching byte-for-byte. Production was not overwritten. Only MV collector/engine/delivery were paused for comparison and resumed afterward. Daily backup retention is 14 days; same-server backups do not cover loss of the VPS.

The post-upgrade dump **mv-signal-20261004T083425638206Z.dump**, SHA256 **da6feef56a3cf7b1c36ddcde4cc1049245738c27d73c6c1e6c1679675ac4648e**, restored separately with all **twelve** selected critical tables matching, including AI tables. Workers were resumed and independent Binance/indicator/checkpoint checks repeated after the MV database/worker restart. Original owner/cursors/origins remained available; no new VPS plan was generated. The unchanged financial contract SHA256 is `2a7956f1292fbceade18124dcab32f337f8e1663f9a312397446c6c34253610f`.

Real DeepSeek diagnostic: pinned `deepseek/deepseek-v4-pro-0813`, 407 prompt/206 completion tokens and API-reported cost **$0.000504628864**. Its validated commentary explicitly identified the snapshots as a connectivity diagnostic with no published signal or risk plan. The durable attempt consumes one of the twenty daily request slots. API and web receive no OpenRouter key; only the AI worker does. See [AI behavior and bounds](PHASE9_AI_REVIEWS.md).

Pending: Telegram durable delivery and real send verification; encrypted off-server backup destination; longer VPS endurance/load observations and remote CI execution. No VPS signal existed during the initial 4 October checks. By 5 October, ten plans were published with eight accepted AI reviews and two safe failures, as recorded below. Profitability is not established, and the original negative research results remain published. No exchange orders or paper observer run in this release.

## Release 0.8.1 expansion

Release 0.8.1 is activated on the VPS with **29 chosen coins / 58 ready streams / 29 engine cursors**. All supplied contracts passed Binance validation. There are 29,002 retained completed candles; BTC/ETH seed origins and cursors were preserved, while added markets established 27 fresh non-trading startup baselines. No VPS signal had been published at the end of these checks; BTC/ETH's latest completed hour produced `NO_FRESH_RECLAIM_OR_LOSS`.

All 58 streams passed direct Binance comparison of the latest three OHLCV bars, independent rational EMA20/EMA50/SMA200/Wilder ATR within the approved 1e-28 relative bound, and bit-identical checkpoint replay. The first verification attempt ran before new checkpoints existed; it was repeated only after all 29 markets were ready.

The approximately four-minute run included 4 fail-closed `backfilling` / `waiting-data` samples during the watchlist subscription transition. Following that transition, from **09:06:57–09:10:33 UTC** on 4 October, **44 consecutive samples** at five-second intervals over **215.53 seconds** all reported core readiness, streaming collector, running engine, zero web backlog and zero reconnects. Maximum sampled persisted event age in that steady segment was **4514 ms**, collector heartbeat age **4510 ms**, engine heartbeat age **1067 ms**. These are sampled persisted health ages, not packet-level latency maxima. Collector logs contain 2 complete 29-market reconciliations spanning **10.598, 10.984 seconds** from first to final stream-completion log; stream reading continued concurrently.

Twenty sequential database-backed reads of `chosen_market_views` for all 29 coins measured median **90.77 ms**, maximum **129.31 ms**. This server-function check excludes HTTPS, authentication and browser rendering. Resource snapshots are retained in `artifacts/vps-scale-observation.txt`; spare RAM and point-in-time CPU do not establish endurance or an hourly burst service-level guarantee.

After expansion, **mv-signal-20261004T091141005719Z.dump**, SHA256 **8569c15d297e4915d0a6882e91f6340525116f49ef52b6f4ff32c4814645112f**, restored into a new temporary PostgreSQL database with all twelve selected critical tables matching byte-for-byte. Only MV workers were paused and resumed; production data was never overwritten. Public desktop/mobile HTTPS/accessibility checks passed again. Existing BharatEdit/XTrade sites returned HTTPS 200, retained their Nginx checksums and their container uptimes.

Checks: **227 backend tests** on Windows and in the rebuilt Linux API image, **10 real PostgreSQL tests**, **58 desktop/mobile Playwright tests**, ESLint, strict TypeScript and both production builds passed. Financial contract and schema `0005` are unchanged. Telegram, off-server encrypted backup transport, remote CI and longer VPS endurance remain pending. The research is still fixed BTC/ETH history and establishes no profitability for the expanded watchlist.

Initial 202-file scaling archive SHA256 was `60b01977d0db4a2dd06cb06e930eab5924f8bedb9cc59d4ae560f089e77340ef`. The API metadata version/description were then corrected and the API image rebuilt with the full backend suite passing. Final documentation is refreshed separately; `release-manifest-current.json` binds all final source bytes, and the final archive checksum is stored beside it in the private shared release-archives directory. The final check also compares all API/strategy Python and contract JSON files against the running image. No database container restart or schema change was needed for this release.

## Release 0.8.2 chart layout fix

The 29-coin sidebar previously enlarged the shared grid row, stretching the chart vertically through `height:100%` and flexible chart sizing. Overview and Chosen markets now align panels at the top; the chart has a bounded viewport-based desktop height (395–560 px) and fixed responsive heights (360 / 330 px). The coin list scrolls within 360 px, retaining the header, management controls and all 29 keyboard-accessible market buttons.

Sixty desktop/mobile Playwright checks passed, including an explicit three-to-29-coin regression: chart height stays unchanged on both pages, the last coin remains reachable by keyboard and no horizontal overflow occurs. Controlled transport screenshots were reviewed on desktop/mobile; they verify presentation, not live signal arithmetic. ESLint, strict TypeScript, Windows and VPS Linux standalone builds passed. API regression: 227 passed / ten optional PostgreSQL tests skipped in this invocation; the earlier ten real PostgreSQL checks remain separate evidence.

Only the web service was recreated for deployment. API/collector/engine/delivery/AI/database and all existing website container identities/start times were preserved (20 other running containers compared). Live core remained ready with 29 ready markets and zero web backlog. Public HTTPS assets contain the new chart/list rules; existing sites returned HTTPS 200 with unchanged Nginx checksums. API image remains 0.8.1 and financial strategy/schema are unchanged. The initial web-build archive SHA256 was `5d2f88a9d62db91f179c21db6f90620c5205342256bd64812583342e8def8e5b`; final documentation/source hashes are refreshed separately.


## Release 0.9.0 IST and signal charts

Deployed 5 October: interface clocks/dates use Asia/Kolkata with AM/PM and IST labels; stored epochs and exchange boundaries are unchanged. Inspect signal now opens a polling completed-candle chart with its source marker, frozen entry/SL/target, default EMA20/EMA50/SMA200 lines and ATR14. Source/Latest views preserve historical context and distinguish stale/offline/withdrawn data. See [full implementation and verification boundary](IST_SIGNAL_CHARTS.md).

230 API tests passed on Windows and Linux, 64 desktop/mobile browser checks passed, and lint/TypeScript/builds passed. Both windows were exercised against all ten actual VPS plans in PostgreSQL; original plan payloads/hashes were preserved. Nineteen other running containers retained identities/start times; collector/engine/delivery/AI/database and existing websites were uninterrupted. Core remained ready with 29 ready markets and zero backlog. Eight real signal AI reviews were complete; two failed safely. Telegram remains deferred. Profitability and longer endurance are unverified.


## Release 0.9.1 signal chart readability

Deployed 5 October: Latest candles now initially shows the latest 96 completed bars, independently of the source marker. Signal start shows broader context. Price focus scales visible candles and frozen risk levels; Full indicator range includes every selected overlay in scaling. Active buttons, Reset view, retained indicator values and a separate Last close prevent ambiguous labels. The source marker is compact and has right-hand space. IST AM/PM remains in place. See [behavior and verification boundaries](SIGNAL_CHART_READABILITY.md).

66 desktop/mobile browser checks passed; all 20 signal checks were repeated after the final compact marker label. Lint, strict TypeScript, Windows/Linux production builds and 230 Windows API checks passed; ten optional PostgreSQL checks were skipped in this invocation. Actual retained WLD data was rendered on desktop/mobile through isolated local browser transport and visually reviewed. No authenticated owner session was minted.

Only web was recreated. Twenty other running containers retained IDs/start times, including API, every worker, PostgreSQL and other websites. All ten existing plan payloads/hashes were preserved. Core and 29 markets remained ready with zero web backlog. Published CSS and the actual chart JavaScript bundle were checked through trusted HTTPS against the running image. Anonymous access, origin rejection and public desktop/mobile browser checks passed. Both existing websites returned HTTPS 200 using curl and retained their Nginx checksums; one urllib bot request returned 403 without any website change. Web is 0.9.1, API remains 0.9.0 and background workers remain on their unchanged image. No schema, financial strategy, indicator arithmetic or AI request policy changed. Telegram and longer endurance remain unverified/deferred.


## Release 0.9.2 journal date filter

Deployed 5 October: the full Signal journal defaults to Today in IST. A date picker retrieves earlier publication days, Today follows IST midnight, and All dates preserves complete history. The protected backend filters indexed publication timestamps before pagination; stored UTC timestamps and frozen risk/evidence are unchanged. Date changes reset loaded pages and ignore stale responses. Market/direction/search/CSV continue to compose with the selected date. Overview's recent plans and the latest-25 Evaluation log retain their existing scope. See [behavior and verification boundaries](JOURNAL_DATE_FILTER.md).

235 API tests passed on Windows and in the new Linux image; ten optional PostgreSQL checks were skipped in these invocations, with the earlier ten real PostgreSQL integration checks retained separately. The complete browser suite passed 70 checks; eight operations checks were repeated after the final responsive/selected-market refinements in an America/Los_Angeles browser timezone. Lint, strict TypeScript and Windows/Linux production builds passed. Controlled captures were reviewed on desktop/mobile.

Actual VPS PostgreSQL reads returned seven plans for 5 October IST, three for 4 October and ten for All dates. Two-row cursor pages matched independent native SQL order/count without duplicates or changed payloads. Only API/web were recreated; 19 other running containers retained IDs/start times, including every background worker, PostgreSQL and other websites. All ten original plans were preserved; core and 29 markets remained ready with zero web backlog. New CSS/client bundle were checked through trusted HTTPS. Public desktop/mobile checks passed; anonymous dated history returned 401 and foreign-origin writes 403. No owner session was minted. Both existing websites returned HTTPS 200 with unchanged Nginx checksums. Financial contract and schema remain unchanged; Telegram and longer endurance remain pending.

