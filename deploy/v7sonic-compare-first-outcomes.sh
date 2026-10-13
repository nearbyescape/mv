#!/usr/bin/env bash
# Operator-approved historical 120-minute paper reference examination.
# NOT a publisher, broker executor, automatic trader or order generator.
# Requires 120 fully closed Binance futures 1m candles AFTER the 09:05
# decision's partial minute; no 30-second entry fills can be established.
#
#   V7_EXPECTED_SHA=<exact-reviewed-commit> \
#   V7_HISTORICAL_PUBLIC_GET_APPROVED=YES \
#      bash deploy/v7sonic-compare-first-outcomes.sh
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EXPECTED="${V7_EXPECTED_SHA:?Pinned 40-digit commit SHA required}"
[[ "$EXPECTED" =~ ^[a-f0-9]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$EXPECTED"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

assert_v4_frozen() {
  local svc cid
  local -a ids
  for svc in engine telegram telegram-report ai; do
    mapfile -t ids < <(docker ps -aq \
      --filter label=com.docker.compose.project=mv-signal \
      --filter "label=com.docker.compose.service=$svc")
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
assert_v4_frozen
on_exit() {
  local status=$?
  trap - EXIT
  if ! assert_v4_frozen; then
    echo "CRITICAL: V4 suspension altered" >&2
    exit 1
  fi
  exit "$status"
}
trap on_exit EXIT

if test "${V7_HISTORICAL_PUBLIC_GET_APPROVED:-}" != YES; then
  echo "STOP: explicit operator approval required; zero Binance requests." >&2
  exit 2
fi

# 2026-10-13 11:06 IST: first full 120 post-decision minute bars all
# completed. This is AFTER original 30s signal expiration. Not fill proof.
if ! python3 - <<'PY'
import time
from datetime import datetime, timezone, timedelta
boundary = 1791862500000
deadline = boundary + 121 * 60_000
next_ist = datetime.fromtimestamp(deadline / 1000, timezone(timedelta(hours=5, minutes=30)))
print("Earliest complete 120m historical evidence:", next_ist.isoformat())
if time.time_ns() // 1_000_000 < deadline:
    raise SystemExit("STOP: 120 full 1m bars not yet closed; no GETs")
PY
then
  exit 3
fi

SOURCE="/var/tmp/v7sonic-live-receipts-8e94be2f5cb5"
OUTPUT="/var/tmp/v7sonic-outcome-evidence-${EXPECTED:0:12}"
test -d "$SOURCE"
test ! -L "$SOURCE"
test "$(stat -c '%u:%g %a' "$SOURCE")" = "10001:10001 700"
for suffix in -wal -shm; do
  path="$SOURCE/v7sonic-paper-release.sqlite3$suffix"
  if test -e "$path" || test -L "$path"; then
    echo "STOP: private original evidence has uncheckpointed SQLite sidecar" >&2
    exit 4
  fi
done
if test -L "$OUTPUT"; then
  echo "STOP: outcome evidence symlink rejected" >&2
  exit 4
fi
if ! test -e "$OUTPUT"; then
  mkdir -m 0700 -- "$OUTPUT"
  chown 10001:10001 -- "$OUTPUT"
fi
test -d "$OUTPUT"
test ! -L "$OUTPUT"
test "$(stat -c '%u:%g %a' "$OUTPUT")" = "10001:10001 700"
test "$(python3 - "$OUTPUT" <<'PY'
import os, sys
s = os.statvfs(sys.argv[1])
print(int(s.f_bavail * s.f_frsize >= 2 * 1024**3))
PY
)" = "1"

IMAGE="mv-v7sonic-historical-outcome:${EXPECTED:0:12}"
echo "=== BUILD PINNED HISTORICAL ANALYSIS IMAGE (V4 UNTOUCHED) ==="
docker build --pull=false -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"
assert_v4_frozen

echo "=== TWO POST-DECISION PUBLIC BINANCE GETS, PAPER ONLY ==="
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
  --mount "type=bind,source=$SOURCE,target=/state,readonly" \
  --mount "type=bind,source=$OUTPUT,target=/outcomes" \
  "$IMAGE" \
  python -m services.t7sonic.outcome_capture_worker \
    --capture-once --public-network-approved --paper-only-acknowledged \
    --state-dir /state --outcome-dir /outcomes

echo "=== CONFIRM ZERO LIVE PUBLICATION AND RETIRED V4 ==="
assert_v4_frozen
echo "HISTORICAL 120M REFERENCE ACQUISITION: PASS"
echo "New outcome files: $OUTPUT"
echo "Original paper source folder was mounted read-only"
echo "No verified entry fills, no client publication and zero exchange orders"
