# Chosen-market expansion — release 0.8.1

The owner requested additional markets and supplied 27 symbols. With existing BTCUSDT/ETHUSDT, the activated watchlist is 29. Each supplied symbol was checked against real Binance metadata: trading USDT crypto perpetuals with valid exchange filters. All 29 markets were activated and checked on the VPS; short measurements are distinguished from endurance below.

## Implementation

- Website/API accept at most 30 unique uppercase USDT symbols, retaining exact order and backend metadata validation. Setting the list does not create signals.
- The collector runs one periodic REST reconciliation task while continuing to receive WebSocket candles and publish heartbeats. It cancels/awaits the task on stream exit; rate-limit and validation failures propagate into normal fail-closed recovery. REST requests remain sequential, with at most one periodic reconciliation in flight.
- The engine bounds each quote operation to ten seconds and refreshes measured health between candidate decisions. Existing source checks, completed 4H alignment, frozen Decimal risk, publication serialization and ownership fencing remain unchanged.
- Startup warms 500 completed bars per timeframe and establishes fresh baselines for new symbols. Historical warm-up never manufactures entries. Existing BTC/ETH origins/cursors are retained.
- AI remains capped at twenty attempts per UTC day, including retries/diagnostics. More opportunities can create more pending commentary after that limit; deterministic web signals and notifications never await AI. Telegram remains deferred.

29 coins mean **58** 1H/4H streams and an initial total of **29,000** candles at 500 bars per stream (27,000 added warm-up candles). Ordinary completed-bar growth is **870 candles/day** across 1H/4H; actual network events, reconciliation, revisions, indicator snapshots and database overhead add workload. This is 14.5 times the original stream count, not a measured multiplier for CPU or latency. Broader monitoring does not change entry rules or prove better signal quality.

## Activated ordered watchlist

BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, BNBUSDT, UNIUSDT, NEARUSDT, SUIUSDT, ADAUSDT, LINKUSDT, WLDUSDT, TAOUSDT, ARBUSDT, AAVEUSDT, AVAXUSDT, FILUSDT, DOTUSDT, BCHUSDT, LTCUSDT, INJUSDT, APTUSDT, XLMUSDT, TRXUSDT, TIAUSDT, ATOMUSDT, ETCUSDT, OPUSDT, SEIUSDT.

## Observed VPS verification

Release 0.8.1 is activated on the VPS with **29 chosen coins / 58 ready streams / 29 engine cursors**. All supplied contracts passed Binance validation. There are 29,002 retained completed candles; BTC/ETH seed origins and cursors were preserved, while added markets established 27 fresh non-trading startup baselines. No VPS signal had been published at the end of these checks; BTC/ETH's latest completed hour produced `NO_FRESH_RECLAIM_OR_LOSS`.

All 58 streams passed direct Binance comparison of the latest three OHLCV bars, independent rational EMA20/EMA50/SMA200/Wilder ATR within the approved 1e-28 relative bound, and bit-identical checkpoint replay. The first verification attempt ran before new checkpoints existed; it was repeated only after all 29 markets were ready.

The approximately four-minute run included 4 fail-closed `backfilling` / `waiting-data` samples during the watchlist subscription transition. Following that transition, from **09:06:57–09:10:33 UTC** on 4 October, **44 consecutive samples** at five-second intervals over **215.53 seconds** all reported core readiness, streaming collector, running engine, zero web backlog and zero reconnects. Maximum sampled persisted event age in that steady segment was **4514 ms**, collector heartbeat age **4510 ms**, engine heartbeat age **1067 ms**. These are sampled persisted health ages, not packet-level latency maxima. Collector logs contain 2 complete 29-market reconciliations spanning **10.598, 10.984 seconds** from first to final stream-completion log; stream reading continued concurrently.

Twenty sequential database-backed reads of `chosen_market_views` for all 29 coins measured median **90.77 ms**, maximum **129.31 ms**. This server-function check excludes HTTPS, authentication and browser rendering. The end-of-observation snapshot reported collector 1.26% CPU / 78.3 MiB, engine 3.65% CPU / 66.64 MiB and 3,937 MiB VPS RAM available. Measurements are retained in `artifacts/vps-scale-observation.txt`; spare RAM and point-in-time CPU do not establish endurance or an hourly burst service-level guarantee.

After expansion, **mv-signal-20261004T091141005719Z.dump**, SHA256 **8569c15d297e4915d0a6882e91f6340525116f49ef52b6f4ff32c4814645112f**, restored into a new temporary PostgreSQL database with all twelve selected critical tables matching byte-for-byte. Only MV workers were paused and resumed; production data was never overwritten. Public desktop/mobile HTTPS/accessibility checks passed again. Existing BharatEdit/XTrade sites returned HTTPS 200, retained their Nginx checksums and their container uptimes.

Checks: **227 backend tests** on Windows and in the rebuilt Linux API image, **10 real PostgreSQL tests**, **58 desktop/mobile Playwright tests**, ESLint, strict TypeScript and both production builds passed. Financial contract and schema `0005` are unchanged. Telegram, off-server encrypted backup transport, remote CI and longer VPS endurance remain pending. The research is still fixed BTC/ETH history and establishes no profitability for the expanded watchlist.
