#!/usr/bin/env bash
# V7Sonic public-data-only real one-boundary evidence capture.
# Creates ORIGINAL source receipts and a PRIVATE six-market paper SQLite journal.
# No production SQL, client Telegram, Binance private/account API or order API.
# This is NOT forward performance certification or signal publication.
#
# Operator invocation (only during frozen 09:00-23:00 IST session):
#   V7_EXPECTED_SHA=<reviewed 40-digit sha> \
#   V7_PUBLIC_MARKET_CAPTURE_APPROVED=YES \
#      bash deploy/v7sonic-capture-one-live-boundary.sh
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EXPECTED="${V7_EXPECTED_SHA:?Full reviewed Git commit SHA required}"
[[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]] || {
  echo "STOP: V7_EXPECTED_SHA must be exactly 40 lowercase hex characters" >&2
  exit 1
}
test "$(git -C "$ROOT" rev-parse HEAD)" = "$EXPECTED"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

assert_production_frozen() {
  local svc ref
  local -a refs
  for svc in engine telegram telegram-report ai; do
    mapfile -t refs < <(
      docker ps -aq \
        --filter label=com.docker.compose.project=mv-signal \
        --filter "label=com.docker.compose.service=$svc"
    )
    if [[ "$svc" == engine ]]; then
      test "${#refs[@]}" -eq 1
    else
      test "${#refs[@]}" -le 1
    fi
    for ref in "${refs[@]}"; do
      test "$(docker inspect -f '{{.State.Running}}' "$ref")" = false
      if [[ "$svc" == engine ]]; then
        test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$ref")" = no
      fi
    done
  done
  test -z "$(docker ps -q --filter label=com.docker.compose.project=mv-v7sonic-isolated)"
}
assert_production_frozen

if [[ "${V7_PUBLIC_MARKET_CAPTURE_APPROVED:-}" != "YES" ]]; then
  echo "STOP: This command requires an explicit public-data live-capture approval." >&2
  echo "No HTTPS requests or release signals have been created." >&2
  exit 2
fi

# Determine session eligibility from the local clock before creating any
# claim/disk evidence or making public HTTPS GETs. The Python runner will
# independently enforce the session and 5m deadline at the capture boundary.
if ! python3 - <<'PY'
from datetime import datetime, timedelta, timezone
import time
now = time.time_ns() // 1_000_000
future_boundary = (now // 300_000 + 1) * 300_000
ist = timezone(timedelta(hours=5, minutes=30))
when = datetime.fromtimestamp(future_boundary / 1000, ist)
print(f"Next future boundary: {when.isoformat()}")
if not (9 <= when.hour < 23):
    raise SystemExit("SESSION_CLOSED: No network capture attempted; rerun during 09:00–23:00 IST")
PY
then
  echo "STOP: next boundary outside frozen IST session; no Binance requests made." >&2
  exit 3
fi

command -v docker >/dev/null
test "$(docker info --format '{{.ServerVersion}}')" != ""
# Preserve evidence between runs for immutable boundary claims and forensic audit.
STATE="/var/tmp/v7sonic-live-receipts-${EXPECTED:0:12}"
if test -L "$STATE"; then
  echo "STOP: symlinked evidence directory not permitted" >&2
  exit 1
fi
if ! test -e "$STATE"; then
  mkdir -m 0700 -- "$STATE"
  chown 10001:10001 -- "$STATE"
fi
test -d "$STATE"
test ! -L "$STATE"
test "$(stat -c '%u:%g' "$STATE")" = "10001:10001"
test "$(stat -c '%a' "$STATE")" = 700
# Journal + saved 31-response original HTTP batches require free space.
FREE_BYTES="$(stat -f -c '%a %S' "$STATE" | awk '{print $1*$2}')"
test "${FREE_BYTES%.*}" -ge 2147483648 || {
  echo "STOP: <2 GiB free evidence disk" >&2
  exit 1
}

IMAGE="mv-v7sonic-live-evidence:${EXPECTED:0:12}"
echo "=== 1. BUILD V7-ONLY TEST IMAGE (NO V4 TAG REPLACEMENT) ==="
docker build --pull=false \
  -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"

echo "=== 2. VERIFY NO PRODUCTION WORKER STARTED ==="
assert_production_frozen
echo "=== 3. CAPTURE NEXT COMPLETE FIVE-MINUTE BOUNDARY (PUBLIC BINANCE GET ONLY) ==="
echo "Evidence host directory: $STATE"
echo "No production database, API credentials, BotFather token or Telegram mounts."
docker run --rm --pull=never \
  --network bridge \
  --read-only \
  --user 10001:10001 \
  --security-opt no-new-privileges:true \
  --cap-drop ALL \
  --pids-limit 64 \
  --memory 512m \
  --cpus 1.50 \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001 \
  --mount "type=bind,source=$STATE,target=/state" \
  "$IMAGE" \
  python -m services.t7sonic.release_capture_worker \
    --capture-once \
    --public-network-approved \
    --paper-only-acknowledged \
    --state-dir /state

echo "=== 4. VERIFY PRODUCTION WAS NOT RESTARTED ==="
assert_production_frozen

echo "V7 ORIGINAL ONE-BOUNDARY PAPER CAPTURE: PASS"
echo "Persisted evidence: $STATE"
echo "Client publication authorized: NO"
echo "Production DB writes: NONE"
echo "Exchange orders: NONE"
