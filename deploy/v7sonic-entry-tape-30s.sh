#!/usr/bin/env bash
# ONE SHOT, private research only: public Binance aggregate trades during the
# initial 09:05:00-09:05:30 IST decision expiry window on 13 Oct 2026.
# NO private exchange API, NO orders, NO Telegram, NO production Postgres.
# Run within 40 hours of the saved original 09:05 UTC-equivalent boundary.
#
# V7_EXPECTED_SHA=<reviewed-exact-full-sha> \
# V7_PUBLIC_ENTRY_TAPE_APPROVED=YES bash deploy/v7sonic-entry-tape-30s.sh
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EXPECTED="${V7_EXPECTED_SHA:?Exact pinned source SHA mandatory}"
[[ "$EXPECTED" =~ ^[a-f0-9]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$EXPECTED"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

verify_frozen() {
  local s id
  local -a ids
  for s in engine telegram telegram-report ai; do
    mapfile -t ids < <(docker ps -aq \
      --filter label=com.docker.compose.project=mv-signal \
      --filter "label=com.docker.compose.service=$s")
    if test "$s" = engine; then
      test "${#ids[@]}" -eq 1
    else
      test "${#ids[@]}" -le 1
    fi
    for id in "${ids[@]}"; do
      test "$(docker inspect -f '{{.State.Running}}' "$id")" = false
      if test "$s" = engine; then
        test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$id")" = no
      fi
    done
  done
}
verify_frozen
finish() {
  local rc=$?
  trap - EXIT
  if ! verify_frozen; then
    echo "CRITICAL: V4 production suspension changed" >&2
    exit 1
  fi
  exit "$rc"
}
trap finish EXIT

if test "${V7_PUBLIC_ENTRY_TAPE_APPROVED:-}" != YES; then
  echo "STOP: Public Binance research GETs require separate explicit approval." >&2
  exit 2
fi

python3 - <<'PY'
import time
from datetime import datetime, timezone, timedelta
boundary = 1791862500000
now = time.time_ns() // 1_000_000
expiry = boundary + 30_000
if not expiry + 1000 <= now < boundary + 40*60*60*1000:
    raise SystemExit("STOP: 30s window unclosed or outside 40h source API safety window")
print("Historical entry tape boundary (IST):",
      datetime.fromtimestamp(boundary/1000, timezone(timedelta(hours=5,minutes=30))).isoformat())
PY

SOURCE="/var/tmp/v7sonic-live-receipts-8e94be2f5cb5"
OUT="/var/tmp/v7sonic-entry-tape-${EXPECTED:0:12}"
test -d "$SOURCE"
test ! -L "$SOURCE"
test "$(stat -c '%u:%g %a' "$SOURCE")" = "10001:10001 700"
for suffix in -wal -shm; do
  name="$SOURCE/v7sonic-paper-release.sqlite3$suffix"
  if test -e "$name" || test -L "$name"; then
    echo "STOP: Original SQLite journal not checkpointed. Do not edit evidence." >&2
    exit 2
  fi
done
if test -L "$OUT"; then
  echo "STOP: Destination evidence symlink" >&2
  exit 2
fi
if ! test -e "$OUT"; then
  mkdir -m 0700 -- "$OUT"
  chown 10001:10001 -- "$OUT"
fi
test -d "$OUT"
test ! -L "$OUT"
test "$(stat -c '%u:%g %a' "$OUT")" = "10001:10001 700"

IMAGE="mv-v7sonic-entry-tape:${EXPECTED:0:12}"
echo "=== BUILD ISOLATED V7 PUBLIC TAPE IMAGE; V4 UNCHANGED ==="
docker build --pull=false -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"
verify_frozen
echo "=== PUBLIC HISTORICAL AGGREGATE TRADES: 2 MARKETS, 6 x 5s SLICES EACH ==="
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
  --mount "type=bind,source=$OUT,target=/output" \
  "$IMAGE" \
  python -m services.t7sonic.entry_tape_capture_worker \
    --capture-once --public-network-approved --paper-only-acknowledged \
    --state-dir /state --output-dir /output

verify_frozen
echo "V7 HISTORICAL ENTRY PRINT RESEARCH: PASS"
echo "Evidence in $OUT"
echo "Original source folder mounted read-only; Telegram 0; orders 0"
