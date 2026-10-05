# Telegram, daily session and client handover

## Operating policy

`packages/contracts/signal-session-v1.json` is an operational restriction, separate from the immutable financial strategy-v1. Production enables it with MV_SIGNAL_SESSION_ENABLED=true. Both completed 1H source close and final publication must be within 09:00 AM inclusive and 11:00 PM exclusive in IST. Actual hourly closes occur at xx:30 IST: first 09:30 AM, last 10:30 PM. Backend pre-quote and post-quote checks enforce the restriction. A rejected off-session candidate becomes terminal SKIPPED / OUTSIDE_SIGNAL_SESSION and does not replay next morning. Data collection, slot expiry, source withdrawal and held-position management continue. Paused hours do not fail core operational readiness, but new entry actions are disabled.

New evidence/plan checksums include the operating policy identity and hash. Existing financial strategy, EMA/Wilder ATR seeds, exact completed 4H alignment, Decimal exchange rounding, two-ATR stop and 2R target stay unchanged. Research retains the original full-day samples. No historical session-filter performance or improvement is claimed.

## Delivery

Use all existing host-proxy/research/AI overrides plus compose.telegram.yml on this VPS. Set MV_TELEGRAM_CHAT_ID to the verified numeric destination and MV_TELEGRAM_START_AT to the activation epoch in milliseconds in private deploy/production.env. The BotFather token is a private deploy/secrets/telegram_token file, mounted only into the Telegram worker. No token reaches API/web or browser bundles. The secret parent directory is private; the file is readable only by the worker UID.

Run `python -m app.telegram.setup` inside an isolated Telegram service container to verify getMe/getChat/getChatMember. Add --test-message only when explicitly authorized: it sends a clearly labeled connection test, never a fabricated signal. Destination migration/permission failures stop delivery; no silent destination change or webhook deletion.

The outbox queues only events after activation. Published messages use exact backend string levels, direction, source close/expiry in IST and a private website link. Delivery runs independently of AI, at least four seconds between claims, persisting the claim before network I/O. A successful receipt must include a positive message ID and the configured chat ID. Expired, withdrawn, tampered, released or off-session new entries are skipped before send. Source revision warnings can send outside the generation session, only if the audience previously received or may have received that signal.

Connection establishment failures and explicit 429 retry-after responses allow bounded retries (at most five attempts). A 429 pauses the destination globally. Write/read timeout, server 5xx, oversized/malformed success responses and crash-after-claim can be ambiguous: they become unknown, visible in System & delivery, with no automatic resend. Exactly-once external delivery is not claimed; unknown messages need operator review. Provider URLs, response descriptions and credentials are never logged. Official protocol: https://core.telegram.org/bots/api and pacing guidance: https://core.telegram.org/bots/faq.

## Authorized reset

Stop the MV API and all MV signal writers (engine, web delivery, AI, Telegram); pause the collector briefly for the separate-database backup comparison. Do not stop shared VPS services. Take a PostgreSQL custom-format backup, verify its SHA and restore only into a newly created disposable database. Compare retained/generated tables before deleting any production records. Never restore over production for this reset.

Inside the API image, `python -m app.operations.reset` lists generated counts. `--apply --verified-backup <receipt>` deletes generated records in one transaction only after writers are quiet. Removal includes NotificationRead, WebNotification, TelegramDelivery, SignalSlot, SignalEvent, AIReview, SignalPlan and SignalDecision. AIRequest paid-attempt/cost records remain with signal_id=null, preserving the daily spend budget. An audit record retains deletion counts and backup receipt.

Keep users, password hashes, invitations, login sessions, authentication controls, settings/watchlist, market contracts, candles, snapshots/checkpoints and research/artifacts. Retain engine cursors and advance them to checkpoint heads; the current historical candle cannot recreate an old signal. Resume MV workers after migration/reset and verify empty journal/inbox, expected preserved table bytes, fresh heartbeats, all 29 markets ready and other website/container identities/configuration unchanged. Future legitimate market signals may appear after handover; an empty journal is a reset observation, not a permanent state.

## Verification boundary

At the initial release packaging checkpoint: 274 local API tests, lint, TypeScript and Windows build passed. Production deployment, actual Telegram preflight/send, backup restore and reset are pending; this file is updated after those checks. Controlled tests exercise financial engine-generated fixtures, not fabricated production signals. Sustained live delivery, group-membership changes, hourly burst performance and profitability remain unverified.
