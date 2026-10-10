# V6HBR research test automation — GitHub-only stage

## Current scope

- Authoritative PR: #13 (`codex/mv-v6hbr-research`), intentionally **DRAFT** and never automatically merged.
- GitHub workflow: `.github/workflows/v6hbr-research.yml`; triggers only for V6HBR research branch pushes, source changes in the V6HBR PR, and manual dispatch on that branch.
- Runs only GitHub-hosted, unprivileged, no-secrets unit regressions and operator script static-safety tests, with `contents: read` and checkout credentials disabled.
- Uses the frozen archive contract digest `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64` as a **strict checksum guard**.
- It does **not** mount, fetch or publish the offline historical archives, fetch exchange data, connect to the VPS, trade, access Binance/Lighter accounts, perform database migrations, run deployment, restart a service, or use August–September 2026 performance holdout.
- GitHub-hosted tests are not evidence of the BTC cost-scenario backtest; only the earlier **operator-supplied** VPS runs establish the 34-test baseline and first proxy results.
- Workflow scheduling/execution is conditional on repository GitHub Actions availability and GitHub-hosted runner minute quota. A committed workflow does **not** prove it ran.

## Two independent engineering gates

1. **Repository regressions** (automated when GitHub Actions are enabled): candidate stream digest parity, 1-minute execution model fixture behavior, four independent prospective portfolio policies, historical proxy wiring fixture, post-hoc attribution, operator script static safety and Bash syntax. Logs are available in the PR's checks/Actions UI and through the connected GitHub API if surfaced.
2. **Private VPS archived-data replay** (not automated from ChatGPT or GitHub today): `tools/v6hbr-btc-pricing-pilot.sh` runs with read-only research/archive mounts, `--network none`, `--read-only`, UID 10001, and 0.5 CPU/768MB restrictions. Historical ZIPs remain only at `/var/tmp/mv-v5-history-archives`. The authoritative V4 release `0.14.0` remains unchanged.

## Why there is no unattended VPS access yet

The connected GitHub application can write repository files, but it does not provide SSH, an existing registered VPS runner, repository runner registration, an executable VPS agent, or access to GitHub Actions secrets. Do not suggest that code pushed to GitHub by itself authorizes or executes anything on the VPS.

An unattended VPS job **must not** run arbitrary unreviewed PR code directly on the production host. If later established through a separately approved one-time VPS setup, it requires:

- a non-root dedicated OS identity with no production Docker/Compose, DB, token, SSH agent or sensitive-directory permissions;
- tightly scoped repository read-only access, credential handling outside GitHub source and chat;
- pinned reviewed research SHAs plus an explicit review gate before newly committed code is executed; updating this research branch alone must not automatically authorize execution on the VPS;
- archive inputs bind-mounted read-only, immutable provenance checks, no network in execution container, resource/time limits, and write-only output artifacts to a dedicated restricted research result path;
- hard safety gates against production source, container management, volumes, credentials and exchange order submission;
- a clearly documented operator-controlled stop/disable procedure.

Even with a permitted runner, **automated research tests are not authorization to deploy a trading strategy**. Production cutover requires independent review and approval.

## Latest observed result

The operator provided the following offline results for commit `ab9a8045e9b8943ce476988d90aaf6edf8c036e4`: 34 unit regressions passed and a BTC April–May illustrative cost proxy produced negative aggregate net R in all four cohorts. The later candidate attribution additions and workflow changes are committed but have not been independently validated against VPS archives. Do not claim completion until corresponding evidence is obtained.

## Research continuity

Keep V6HBR PR #13 the single research source. Maintain immutable original V5 strategy/archive contract filenames, no holdout peeking, no unpublished optimization, and no V4 production changes. Avoid creating a second V7 or V6HBR branch just to install automation.
