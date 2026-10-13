#!/usr/bin/env bash
# V7Sonic repeatability experiment: exactly FOUR future five-minute
# public-market PRIVATE paper decisions; NO client publication/orders.
# Not a daemon deployment. No hidden background start, auto-restart,
# production PostgreSQL, Telegram token, or private exchange credential.
#
# V7_EXPECTED_SHA=<pinned-reviewed-40hex> \
# V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES \
#   bash deploy/v7sonic-four-cycle-paper-pilot.sh
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
HEAD="${V7_EXPECTED_SHA:?Pin exact full Git source commit SHA}"
[[ "$HEAD" =~ ^[a-f0-9]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$HEAD"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"
if test "${V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED:-}" != YES; then
  echo "STOP: no public Binance GETs until explicit 4-cycle approval." >&2
  exit 2
fi

frozen() {
  local svc cid
  local -a ids
  for svc in engine telegram telegram-report ai; do
    mapfile -t ids < <(
      docker ps -aq \
        --filter label=com.docker.compose.project=mv-signal \
        --filter "label=com.docker.compose.service=$svc"
    )
    if test "$svc" = engine; then
      test "${#ids[@]}" -eq 1
    else
      test "${#ids[@]}" -le 1
    fi
    for cid in "${ids[@]}"; do
      test "$(docker inspect -f '{{.State.Running}}' "$cid")" = false
      if test "$svc" = engine; then
        test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$cid")" = no
      fi
    done
  done
}
frozen
NAME="mv-v7sonic-paper-four-${HEAD:0:12}"
if test -n "$(docker ps -aq --filter "name=^/${NAME}$")"; then
  echo "STOP: previous four-cycle container still exists. Do not remove evidence." >&2
  exit 3
fi

cleanup() {
  local rc=$?
  trap - EXIT
  if test -n "$(docker ps -q --filter "name=^/${NAME}$")"; then
    docker stop -t 10 "$NAME" >&2 || true
  fi
  if ! frozen; then
    echo "CRITICAL: V4 production suspension changed during research." >&2
    exit 1
  fi
  exit "$rc"
}
trap cleanup EXIT

# Enforce enough remaining local session for all four future 5m closes
# to be done before 23:00 IST. Only 09:00 through 22:40 included.
# Recheck after image build; allow runner's own stricter boundary rule.
check_session() {
  python3 - <<'PY'
import time
from datetime import datetime, timedelta, timezone
NOW = time.time_ns() // 1_000_000
STEP = 300_000
first = (NOW // STEP + 1) * STEP
last = first + 3*STEP
ist = timezone(timedelta(hours=5, minutes=30))
start = datetime.fromtimestamp(first / 1000, ist)
stop = datetime.fromtimestamp(last / 1000, ist)
print("Four future V7 private-paper boundaries:", start.isoformat(), "through", stop.isoformat())
if not (start.date() == stop.date() and
        start.hour >= 9 and
        (stop.hour < 23)):
    raise SystemExit("STOP: not enough time for four 5m closes within frozen IST session")
PY
}
check_session

STATE="/var/tmp/v7sonic-four-cycle-paper-${HEAD:0:12}"
if test -L "$STATE"; then
  echo "STOP: symlinked state directory" >&2
  exit 4
fi
if test ! -e "$STATE"; then
  mkdir -m 0700 -- "$STATE"
  chown 10001:10001 -- "$STATE"
fi
test -d "$STATE"
test ! -L "$STATE"
test "$(stat -c '%u:%g %a' "$STATE")" = "10001:10001 700"
test "$(python3 - "$STATE" <<'PY'
import os,sys
s=os.statvfs(sys.argv[1])
print(int(s.f_bavail * s.f_frsize >= 2 * 1024**3))
PY
)" = 1

IMAGE="mv-v7sonic-four-cycle:${HEAD:0:12}"
echo "=== BUILD STANDALONE V7 PAPER-ONLY IMAGE ==="
docker build --pull=false -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"
frozen
check_session

echo "=== OFFLINE READ-ONLY SCHEDULER PREFLIGHT ==="
docker run --rm --pull=never \
  --network none --read-only --user 10001:10001 \
  --security-opt no-new-privileges:true --cap-drop ALL \
  --mount "type=bind,source=$STATE,target=/state,readonly" \
  "$IMAGE" python -m services.t7sonic.release_scheduler --state-dir /state

echo "=== FOUR FUTURE PRIVATE PAPER CYCLES; NO CLIENT SENDS OR ORDERS ==="
echo "Preserved paper journal + immutable receipts: $STATE"
# A prior incomplete attempt must never be silently classified as the
# current four-cycle pilot. Preserve its original evidence for forensics.
if find "$STATE" -maxdepth 1 -name 'v7sonic-private-claim-*.json' -print -quit | grep -q .; then
  echo "STOP: private state already has claimed boundaries; preserve it and review" >&2
  exit 5
fi
RUN_LOG="$(mktemp "/var/tmp/v7sonic-four-cycle-${HEAD:0:12}.XXXXXXXX.log")"
echo "Owner-private audit log: $RUN_LOG"
# Strictly foreground and bounded: operator Ctrl+C stops only THIS paper
# process; timeout also prevents lingering beyond the approved pilot.
# Capture the FINAL scheduler JSON to prove we actually completed four.
timeout --foreground --signal=TERM --kill-after=15s 1800s \
  docker run --rm --pull=never \
    --name "$NAME" \
    --network bridge --read-only --user 10001:10001 \
    --security-opt no-new-privileges:true --cap-drop ALL \
    --pids-limit 64 --memory 512m --cpus 1.50 \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001 \
    --mount "type=bind,source=$STATE,target=/state" \
    "$IMAGE" python -m services.t7sonic.release_scheduler \
      --run-private-paper-loop \
      --public-network-approved --paper-only-acknowledged \
      --state-dir /state --max-cycles 4 | tee "$RUN_LOG"

echo "=== REQUIRE EXACTLY FOUR COMPLETE JOURNAL-COMMITTED PAPER CYCLES ==="
python3 - "$RUN_LOG" "$STATE" <<'PY'
import json
from pathlib import Path
import sys

log, folder = map(Path, sys.argv[1:])
data = json.loads(log.read_text())
if not (
    data.get("status") == "V7_PRIVATE_PAPER_SCHEDULER_STOPPED_NO_SEND"
    and type(data.get("completed_cycles")) is int
    and data["completed_cycles"] == 4
    and type(data.get("durably_stored_cycles")) is int
    and data["durably_stored_cycles"] == 4
    and data.get("production_database_writes") is False
    and data.get("private_sql_journal_approved") is False
    and data.get("client_publication_authorized") is False
    and data.get("telegram_messages_sent") == 0
    and data.get("orders_submitted") == 0
):
    raise SystemExit("STOP: paper scheduler did not prove four successful no-send cycles")
summaries = list(folder.glob("v7sonic-private-paper-cycle-*.json"))
claims = list(folder.glob("v7sonic-private-claim-*.json"))
if len(summaries) != 4 or len(claims) != 4:
    raise SystemExit("STOP: four immutable paper claims/receipts not present")
boundaries = []
for path in summaries:
    item = json.loads(path.read_text())
    t = item.get("boundary_ms")
    if not (type(t) is int and
            item.get("status") == "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND" and
            item.get("market_count") == 6 and
            item.get("client_publication_authorized") is False and
            item.get("telegram_messages_sent") == 0 and
            item.get("orders_submitted") == 0):
        raise SystemExit("STOP: incomplete or unsafe private paper receipt")
    boundaries.append(t)
if len(set(boundaries)) != 4 or any(
    b - a != 300_000 for a, b in zip(sorted(boundaries), sorted(boundaries)[1:])
):
    raise SystemExit("STOP: four private paper boundaries are not consecutive")
print("FOUR FUTURE SIX-MARKET PAPER DECISIONS: VERIFIED")
PY

frozen
echo "V7 FOUR FUTURE PAPER BOUNDARIES: PASS"
echo "Private source and decision evidence: $STATE"
echo "Client Telegram: 0; production DB writes: 0; exchange orders: 0"
