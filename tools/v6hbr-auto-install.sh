#!/usr/bin/env bash
# One-time operator-authorized install for the MV V6HBR isolated research timer.
# Run only from a reviewed, exact pinned commit. Never accepts credentials.
set -Eeuo pipefail
umask 077

if test "$#" -ne 1; then
  echo "Usage: bash v6hbr-auto-install.sh <exact-reviewed-40-char-commit>" >&2
  exit 2
fi
EXPECTED="$1"
ROOT=/var/lib/mv-v6hbr-auto
WT=/tmp/mv-v5-history-pilot
ARCH=/var/tmp/mv-v5-history-archives
BRANCH=codex/mv-v6hbr-research
EXEC=/usr/local/libexec/mv-v6hbr-auto-agent
SERVICE=/etc/systemd/system/mv-v6hbr-auto.service
TIMER=/etc/systemd/system/mv-v6hbr-auto.timer

if test "$(id -u)" -ne 0; then
  echo "STOP: install requires an interactive VPS operator with root privileges" >&2
  exit 2
fi
if ! [[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]]; then
  echo "STOP: expected a 40-character reviewed commit SHA" >&2
  exit 2
fi
test "$(cd "$WT" && pwd -P)" = "$WT"
test "$(git -C "$WT" branch --show-current)" = "$BRANCH"
test -z "$(git -C "$WT" status --porcelain)"
test -d "$ARCH" && test ! -L "$ARCH"
test "$(realpath -e "$ARCH")" = "$ARCH"
command -v docker >/dev/null
command -v systemctl >/dev/null
command -v flock >/dev/null
command -v timeout >/dev/null
command -v sha256sum >/dev/null
command -v python3 >/dev/null
test -d /run/systemd/system
test ! -e "$ROOT" && test ! -L "$ROOT"  # Never adopt an existing service.
test ! -e "$EXEC" && test ! -L "$EXEC"
test ! -e "$SERVICE" && test ! -L "$SERVICE"
test ! -e "$TIMER" && test ! -L "$TIMER"
test -r "$WT/packages/contracts/v5-history-v1.json"
echo '48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64  '"$WT"'/packages/contracts/v5-history-v1.json' | sha256sum -c -

ORIGIN="$(git -C "$WT" remote get-url origin)"
case "$ORIGIN" in
  https://github.com/nearbyescape/mv|https://github.com/nearbyescape/mv.git|git@github.com:nearbyescape/mv.git) ;;
  *) echo "STOP: unrecognized GitHub origin (do not supply credentials here)" >&2; exit 2 ;;
esac

# This fetch only updates the isolated RESEARCH remote tracking ref.
GIT_TERMINAL_PROMPT=0 git -C "$WT" \
  fetch --no-tags origin \
  "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
test "$(git -C "$WT" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}")" = "$EXPECTED"
test -z "$(git -C "$WT" status --porcelain)"

# Copy a fixed host-executed agent ONLY from the approved SHA.
# Future branch changes never update this root-owned executable.
AGENT_TMP="$(mktemp /tmp/v6hbr-approved-agent.XXXXXXXX)"
trap 'rm -f "$AGENT_TMP"' EXIT
git -C "$WT" show "$EXPECTED:tools/v6hbr-auto-agent.sh" > "$AGENT_TMP"
bash -n "$AGENT_TMP"

install -d -m 0700 "$ROOT" "$ROOT/sources" "$ROOT/reports"
git clone --quiet --no-checkout -- "$WT" "$ROOT/repository"
git -C "$ROOT/repository" remote set-url origin "$ORIGIN"
GIT_TERMINAL_PROMPT=0 git -C "$ROOT/repository" \
  fetch --no-tags origin \
  "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
test "$(git -C "$ROOT/repository" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}")" = "$EXPECTED"
printf '%s\n' "$EXPECTED" > "$ROOT/last-reviewed-ancestor"

install -d -m 0700 /usr/local/libexec
install -m 0700 "$AGENT_TMP" "$EXEC"
cat > "$SERVICE" <<'UNIT'
[Unit]
Description=MV V6HBR isolated research check (never production)
Wants=network-online.target
After=network-online.target docker.service
ConditionPathExists=/var/lib/mv-v6hbr-auto/last-reviewed-ancestor

[Service]
Type=oneshot
User=root
Group=root
UMask=0077
ExecStart=/usr/local/libexec/mv-v6hbr-auto-agent
TimeoutStartSec=45min
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ReadWritePaths=/var/lib/mv-v6hbr-auto
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
UNIT

cat > "$TIMER" <<'UNIT'
[Unit]
Description=Hourly isolated V6HBR research check for new GitHub branch SHAs

[Timer]
OnCalendar=hourly
RandomizedDelaySec=3min
Persistent=true
Unit=mv-v6hbr-auto.service

[Install]
WantedBy=timers.target
UNIT

chmod 0600 "$SERVICE" "$TIMER"
systemctl daemon-reload
systemctl enable --now mv-v6hbr-auto.timer
# Initial run is scheduled non-blocking. A failure never changes live V4.
systemctl start --no-block mv-v6hbr-auto.service

echo "V6HBR automation installation requested."
echo "Research timer: mv-v6hbr-auto.timer"
echo "Research logs: $ROOT/reports/latest.txt and <sha>.log"
echo "Check status: systemctl status mv-v6hbr-auto.service --no-pager"
echo "Stop: systemctl disable --now mv-v6hbr-auto.timer"
echo "Production MV V4 / Compose / DB / Telegram: untouched"
