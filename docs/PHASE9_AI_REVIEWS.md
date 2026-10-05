# Phase 9 — immutable-evidence AI commentary

Release 0.8.0 adds a separate OpenRouter worker pinned to `deepseek/deepseek-v4-pro-0813`. Telegram remains deferred by the owner. Only the deterministic backend engine originates signals. AI receives a compact copy of frozen plan/evidence after commit and writes only separate commentary/request tables. Publication, web notifications, entry expiry and operator actions never await AI.

## Behavior

The worker discovers committed plans from the preceding 24 hours and creates one review per signal. Exact plan/evidence hashes bind its response to the original record. Invalidated/withdrawn evidence hides commentary. Model assessment is commentary, not an approval or signal filter. The website retains deterministic rule checks in pending, failed and unavailable states and renders model text as escaped React text.

Schema validation rejects extra fields, unknown/failed rule references, duplicate references, oversized text, HTML/control characters, URLs and selected misleading claims. It validates structure/reference identity, not every semantic claim. Generated commentary can be mistaken; frozen backend prices remain authoritative. No tools, trading credentials, user identity, operator notes or external news enter the prompt.

## Bounds and persistence

- Maximum **20 request attempts per UTC day**, including diagnostics, reserved durably before network access. Failed and ambiguous attempts count. Lower limits are configurable; higher limits are rejected.
- At most two attempts per review. Only HTTP 429/502/503/504 retry, after two minutes. Credential/payment/schema failures and ambiguous network timeouts fail without automatic rebilling. Interrupted requests fail on restart rather than being silently duplicated.
- Prompt JSON at most 12,000 bytes; completion budget 800 tokens including any provider reasoning allocation; 35-second total timeout; provider response at most 64 KiB.
- Provider routing requires parameters and enforces price ceilings of $1/M prompt and $5/M completion tokens. These ceilings and request bounds do not claim an exact account invoice or cover credit-purchase charges. Returned numeric token/cost metadata is retained when available.
- Dedicated database singleton plus transaction ownership fencing; heartbeat continues while an HTTP request is running. Losing ownership prevents result commits. AI tables never replace signal plans, events or levels.
- Secret is mounted only into the AI worker. API gets an enable flag; browser and API containers receive no OpenRouter key. Optional deployment uses `compose.ai.yml` in addition to the current shared-host/research overrides.

Migration `0005` adds `ai_reviews` and `ai_requests`; existing financial and account tables are not rewritten. The real-provider diagnostic uses actual retained completed Binance indicator snapshots, records its attempt, and creates no signal. It passed on the VPS: the pinned model returned schema-valid commentary, 407 prompt/206 completion tokens and provider-reported cost $0.000504628864. Controlled tests use backend-originated isolated plans and mocked network responses; they do not claim provider performance. Twelve new backend checks, a real PostgreSQL budget/fencing check and desktop/mobile commentary/withdrawal checks passed. The worker is running, with one request of twenty used, but no new market-driven VPS signal occurred during observation. Real-provider exercise and rollout results are recorded separately in verification.

The model ID was rechecked on 4 October against [OpenRouter's model page](https://openrouter.ai/deepseek/deepseek-v4-pro-0813). Parameter routing and JSON response behavior follow [provider routing](https://openrouter.ai/docs/guides/routing/provider-selection) and [structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs). These are dated catalog checks; a real request verifies the available route.
