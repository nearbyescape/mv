#!/usr/bin/env bash
# Explicit, SINGLE bounded V7 paper pilot detached from SSH via systemd.
# DOES NOT merge/deploy V7, start retired V4, publish Telegram, place
# any exchange order, or write production database.
#
# V7_EXPECTED_SHA=<exact-reviewed-source-SHA> \
# V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES \
#   bash deploy/v7sonic-four-cycle-systemd-launch.sh
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
HEAD="${V7_EXPECTED_SHA:?Exact reviewed 40-hex source SHA is mandatory}"
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$HEAD"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

if test "${V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED:-}" != YES; then
  echo "STOP: separate operator approval is mandatory" >&2
  exit 2
fi
command -v systemd-run >/dev/null
command -v systemctl >/dev/null
command -v docker >/dev/null

# Keep all suspended, including any unrelated adjacent V7 pilot.
mapfile -t eng < <(docker ps -aq \
  --filter label=com.docker.compose.project=mv-signal \
  --filter label=com.docker.compose.service=engine)
test "${#eng[@]}" -eq 1
test "$(docker inspect -f '{{.State.Running}}' "${eng[0]}")" = false
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${eng[0]}")" = no
test -z "$(docker ps -q --filter name=^/mv-v7sonic-paper-four-)"

UNIT="v7sonic-private-four-${HEAD:0:12}"
STATE="/var/tmp/v7sonic-four-cycle-paper-${HEAD:0:12}"
# Fail before enqueueing a job if this pinned code has existing
# original pilot evidence: never overwrite, retry in place or backfill.
if test -d "$STATE"; then
  if find "$STATE" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
    echo "STOP: existing private evidence must be preserved; no second job" >&2
    exit 3
  fi
elif test -e "$STATE" || test -L "$STATE"; then
  echo "STOP: invalid private evidence path" >&2
  exit 3
fi

# Preflight on host BEFORE detaching. The invoked original script has
# independent checks again immediately before each public market capture.
python3 - <<'PY'
import time
from datetime import datetime, timedelta, timezone
now = time.time_ns() // 1_000_000
step = 300_000
first = (now // step + 1) * step
last = first + 3 * step
tz = timezone(timedelta(hours=5, minutes=30))
begin = datetime.fromtimestamp(first / 1000, tz)
end = datetime.fromtimestamp(last / 1000, tz)
print("Requested fresh private paper boundaries:", begin.isoformat(), "to", end.isoformat())
if not (begin.date() == end.date() and 9 <= begin.hour < 23 and
        end.hour < 23):
    raise SystemExit("STOP: no valid four-boundary IST session")
PY

echo "=== INSTALL ONE TRANSIENT SYSTEMD PAPER JOB (NO AUTO-RESTART) ==="
systemd-run \
  --unit="$UNIT" \
  --description="V7Sonic four-boundary private paper ONLY; no send/order" \
  --property=Type=exec \
  --property=Restart=no \
  --property=TimeoutStartSec=1900 \
  --property=RuntimeMaxSec=1900 \
  --property=KillMode=control-group \
  --property=StandardOutput=journal \
  --property=StandardError=journal \
  -- /usr/bin/env \
    "V7_EXPECTED_SHA=$HEAD" \
    "V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES" \
    /usr/bin/bash "$ROOT/deploy/v7sonic-four-cycle-paper-pilot.sh"

echo
echo "Transient unit started: $UNIT"
echo "This paper job is independent of your SSH session."
echo "Read progress: journalctl -u $UNIT --no-pager -n 80"
echo "Read status: systemctl show $UNIT -p ActiveState -p SubState -p Result"
echo "Original failed 21:30 evidence stays untouched; no production cutover."
