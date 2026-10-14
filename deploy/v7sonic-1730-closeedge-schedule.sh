#!/usr/bin/env bash
# Schedule ONE exact-day, SSH-independent, V7 PAPER-ONLY simultaneous
# 15m/1h/4h close test on Oct 14, 2026. Never start V4, client
# Telegram, production PostgreSQL, exchange accounts or orders.
#
# Run ONCE before 17:16 IST today:
# V7_EXPECTED_SHA=<exact-clean-reviewed-sha> \
# V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES \
#   bash deploy/v7sonic-1730-closeedge-schedule.sh --schedule
#
# Timer fires at 17:17 IST and plans 17:20,25,30,35 IST boundaries.
# --execute is reserved for the systemd transient timer's service.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
HEAD="${V7_EXPECTED_SHA:?Exact pinned 40hex SHA mandatory}"
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$HEAD"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"
test "${V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED:-}" = YES
test "$(id -u)" = 0
test "$(docker inspect -f '{{.State.Running}}' mv-signal-engine-1)" = false
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' mv-signal-engine-1)" = no
test -z "$(docker ps -q --filter name=^/mv-v7sonic-paper-four-)"

STATE="/var/tmp/v7sonic-four-cycle-paper-${HEAD:0:12}"
if test -d "$STATE"; then
  test -z "$(find "$STATE" -mindepth 1 -maxdepth 1 -print -quit)"
else
  test ! -e "$STATE"
  test ! -L "$STATE"
fi
MODE="${1:-}"
case "$MODE" in
  --schedule|--execute) ;;
  *) echo "STOP: explicit --schedule or timer-only --execute required" >&2; exit 2 ;;
esac

# Time quality checked independently at BOTH timer creation and execution.
# A stale/future timer or late systemd wakeup must fail, not collect a
# different quartet or misclassify the target checkpoint.
python3 - "$MODE" <<'PY'
from datetime import datetime, timedelta, timezone
import sys
ist=timezone(timedelta(hours=5,minutes=30))
now=datetime.now(ist)
day="2026-10-14"
if now.date().isoformat()!=day:
    raise SystemExit("STOP: only 14 Oct 2026 IST permitted")
mode=sys.argv[1]
hms=(now.hour,now.minute,now.second)
if mode=="--schedule":
    if hms >= (17,16,0):
        raise SystemExit("STOP: too late to schedule the 17:30 pilot")
elif not ((17,16,0) <= hms < (17,19,0)):
    raise SystemExit("STOP: misfired/delayed timer outside 17:16-17:18 IST")
if mode=="--execute":
    step=300_000
    now_ms=int(now.timestamp()*1_000)
    first=(now_ms//step+1)*step
    for i,minute in enumerate((20,25,30,35)):
        dt=datetime.fromtimestamp((first+i*step)/1_000,ist)
        if (dt.date().isoformat()!=day or
                dt.hour!=17 or dt.minute!=minute):
            raise SystemExit("STOP: quartet does not cover exactly 17:30")
    print("Exact upcoming paper quartet:", "17:20,17:25,17:30,17:35 IST")
else:
    print("One-shot paper-only systemd launch requested for 17:17 IST")
PY

if test "$MODE" = --execute; then
  # The target script has its OWN exact-SHA, detached unit and V4 guards.
  exec /usr/bin/env \
    "V7_EXPECTED_SHA=$HEAD" \
    "V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES" \
    /usr/bin/bash "$ROOT/deploy/v7sonic-four-cycle-systemd-launch.sh"
fi

UNIT="v7sonic-1730-trigger-${HEAD:0:12}"
if systemctl cat "$UNIT.timer" >/dev/null 2>&1 ||
   systemctl cat "$UNIT.service" >/dev/null 2>&1; then
  echo "STOP: this exact-source 17:30 pilot already scheduled" >&2
  exit 3
fi

echo "=== INSTALL ONE 17:17 IST TIMER (11:47 UTC), ZERO RESTARTS ==="
systemd-run \
  --unit="$UNIT" \
  --on-calendar="2026-10-14 11:47:00 UTC" \
  --timer-property=AccuracySec=1s \
  --property=Type=oneshot \
  --property=Restart=no \
  --property=StandardOutput=journal \
  --property=StandardError=journal \
  -- /usr/bin/env \
    "V7_EXPECTED_SHA=$HEAD" \
    "V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES" \
    /usr/bin/bash "$ROOT/deploy/v7sonic-1730-closeedge-schedule.sh" --execute
echo "One-shot paper trigger timer: $UNIT.timer"
echo "Read timer: systemctl show $UNIT.timer -p ActiveState -p NextElapseUSecRealtime"
echo "After trigger: journalctl -u $UNIT.service --no-pager -n 40"
echo "Actual isolated worker: v7sonic-private-four-${HEAD:0:12}.service"
echo "No production modification, client sends, or exchange orders."
