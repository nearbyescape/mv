# Signal chart readability — web release 0.9.1

Implemented and deployed 5 October 2026 following the owner's WLDUSDT chart capture.

The previous Latest candles view accidentally reused the signal-source anchor, showing only about 24 preceding bars even though 120 were returned. Latest now initially shows the most recent 96 completed candles. Signal start initially frames up to 72 preceding and 48 following candles from the retained source window. Dragging and axis/pinch zoom remain available; Reset view restores the chosen window. Polling does not repeatedly reset a user's view.

Price focus is the default for signal charts. Its scale includes visible candle highs/lows and every frozen entry/SL/target. Selected EMA20/EMA50/SMA200 series remain plotted, but do not expand this scale; distant lines can be outside it, explicitly explained below the chart. Full indicator range restores their normal scale contribution. ATR14 retains its independent pane. These are display choices, never indicator recalculation or altered signal levels.

Selected source/latest and scale buttons now have a visible active state. Indicator legend values show retained backend snapshots. Last close is separate from the saved entry; the duplicate candle price-axis label/line is omitted from signal charts to avoid overlapping Entry. A compact Start marker and responsive right-hand space keep the source point readable. The normal market chart retains its existing price label and scaling.

Local verification: lint, strict TypeScript and production build passed; 230 API checks passed with ten optional PostgreSQL checks skipped in this invocation. The complete desktop/mobile browser suite passed 66 checks. A new rendered-canvas regression independently counts candle bodies to reject the narrow latest-window bug and confirms that a distant SMA no longer compresses candles in Price focus. Frozen text levels and responsive bounds are preserved. Signal checks were repeated after the final compact marker label.

Actual retained WLDUSDT chart data was read without modifying production PostgreSQL and rendered through isolated local browser transport on desktop/mobile: 97 source bars, 120 latest bars, Entry 0.5839000 / SL 0.5668000 / Target 0.6181000. Source/Latest/Full-range captures were visually reviewed; no runtime errors or overflow occurred. This is real saved-data presentation evidence, not an authenticated production-owner browser session or profitability verification.

This release changes only web presentation. The API remains 0.9.0; financial rules, schema, collector, engine, delivery and AI behavior are unchanged. Telegram remains deferred.

VPS rollout: only web was recreated; 20 other running containers retained identities/start times. All ten existing plan payloads and frozen identities were preserved. Core readiness, 29 ready markets and zero web backlog passed. New CSS and the chart JavaScript bundle are served over trusted HTTPS and match the running web image. Public desktop/mobile TLS/accessibility/overflow/runtime checks passed; anonymous signals/chart access remains denied and foreign-origin writes rejected. Other websites retained configuration checksums and returned HTTPS 200 with curl (a urllib bot request received 403).

The initial 208-file Linux web-build archive SHA256 was `29e4ca859ac0f6b2e8771f73b8de5a0a003142153d9e8e7bc59b4d9cb5d5a4ef`. Final documentation hashes and archive checksum are refreshed separately; executable sources must already match before documentation synchronization. No database restart, migration or new backup restoration was needed for this presentation-only update.
