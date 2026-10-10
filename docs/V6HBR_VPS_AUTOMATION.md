# V6HBR — optional one-time VPS research automation

This is a **repository-side prepared** systemd installer and a fixed host-side agent. Writing these files to PR #13 **does not install or start anything on the VPS**. There is no connected SSH tool in this conversation, and the user should **never paste root passwords, SSH keys, GitHub access tokens or API credentials into chat**.

## Responsibilities

- `tools/v6hbr-auto-install.sh` (operator invoked **once** on the VPS, not by ChatGPT): fail-closed root/branch/worktree/frozen-spec checks, fetch the exact **reviewed commit SHA** from `codex/mv-v6hbr-research`, copy the approved fixed host agent into `/usr/local/libexec`, create a new isolated `/var/lib/mv-v6hbr-auto` repository/results directory, and install/enable a systemd hourly timer.
- `tools/v6hbr-auto-agent.sh` (root-owned, never changed automatically): polls just the V6HBR branch, requires ancestry from the installed approved baseline and previous executed SHA, exports tracked files **without checking out or executing remote code on the host**, rejects unsafe archive members, verifies original immutable historical contract, runs the repository regression tests and BTC April–May development-only cost-scenario proxy within the existing image in Docker with networking disabled, no extra capabilities, read-only mounts, UID 10001, CPU 0.5, memory 768 MiB, no secrets, and bounded execution time/log output.
- No archival downloads, no `git reset` against production, no Compose, no production database access, no Telegram, no Lighter orders, no trading or migration; cannot promote or deploy V6HBR to V4 `0.14.0`.
- `/var/tmp/mv-v5-history-archives` is mounted **read-only**. The approved original `v5-history-v1.json` SHA-256 is `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64`.

## Operator installation gate

**Prerequisite:** The VPS already has the clean V6HBR research checkout at `/tmp/mv-v5-history-pilot` with a working GitHub `origin` remote and previously validated Docker image `mv-signal-api-1`. Only the *operator*, through an existing authorized VPS console, can approve and execute the first root-level install. The operator should review the new scripts and their SHA before running them. There is deliberately no remote code piping into an unchecked `bash`.

1. Fetch only `codex/mv-v6hbr-research` tracking ref into the existing clean research checkout. Do not switch production or delete files.
2. Verify its SHA matches the explicitly approved 40-character commit from this chat, then extract the installer **from that exact commit** using `git show SHA:tools/v6hbr-auto-install.sh`.
3. Run `bash -n` on the local installer, then execute it as root with the same exact SHA as its only argument. It independently re-verifies branch SHA, frozen contract, paths, dependencies, and nonexistence of any previous installation before creating a timer.
4. Verify initial execution through `systemctl status mv-v6hbr-auto.service --no-pager` and inspect `/var/lib/mv-v6hbr-auto/reports/latest.txt` and the per-commit log. **Do not report test success until real outputs exist.**

## Ongoing behavior and limitations

After a successful operator installation, **the VPS systemd timer** — not ChatGPT — checks for new V6HBR branch SHAs approximately hourly and runs their tests, with a locally retained per-commit report. It automatically executes unreviewed *research branch* content inside a constrained Docker sandbox; a container sandbox reduces but does not eliminate risks from compromised dependencies or malicious code. For stronger separation, use a dedicated research VPS instead of the production host.

**The assistant cannot retrieve the VPS logs directly** via the currently connected GitHub tools. GitHub Actions unit checks are separately committed to `.github/workflows/v6hbr-research.yml`, but their run status has not been confirmed. To make remote log retrieval possible without user copy/paste, a separately authorized, least-privileged log upload or SSH connector would be required. Avoid embedding a GitHub token, private key or VPS password in the repository.

The timer does not guarantee profitable signals, confidence or accuracy. The historical trade results use synthetic reference quotes and explicitly assumed spread/slippage/taker fees/funding. The August–September holdout remains untouched.

### Operator-controlled shutdown

```bash
systemctl disable --now mv-v6hbr-auto.timer
systemctl stop mv-v6hbr-auto.service
```

The installer refuses to overwrite any existing automation installation; it does not create a root login or accept credentials. Removing the service or result files is a separate reviewed maintenance action.
