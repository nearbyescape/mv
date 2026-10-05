# MV Signal development instructions

- Follow the phased scope in `docs/BUILD_STATUS.md` and the current research plan. Report implemented, demonstrated and unverified work distinctly.
- Never treat synthetic fixtures or their floating-point display calculations as authoritative market data or engine arithmetic. Only the backend strategy engine may originate signals.
- Strategy rules are versioned in `packages/contracts/strategy-v1.json`. Seeded EMA and Wilder ATR, completed candles, deterministic 4H alignment, checkpoint recovery and exchange rounding are financial correctness requirements.
- Never expose API keys to browser bundles. Never place exchange orders in v1. AI explains evidence; it cannot alter signal risk levels or delay deterministic delivery.
- Keep the foundation loopback-only until invite-only authentication and production controls exist. Development credentials are not production user authentication.
- Run relevant checks: web lint, TypeScript, build, Playwright; API pytest. Add meaningful independent arithmetic and state-machine tests when implementing trading behavior.
- Keep `docs/BUILD_STATUS.md` and `docs/VERIFICATION.md` accurate. Do not claim PostgreSQL, CI, live data, profitability or delivery has been verified unless actually exercised.
