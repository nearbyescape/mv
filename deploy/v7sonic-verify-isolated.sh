#!/usr/bin/env bash
# V7 standalone staging smoke. DOES NOT activate a client publisher, SQL
# writer, legacy engine, Telegram bot, database migration or exchange order.
#
# Usage in detached exact-SHA worktree:
#   V7_EXPECTED_SHA=<exact commit sha> bash deploy/v7sonic-verify-isolated.sh
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
EXPECTED="${V7_EXPECTED_SHA:?Set reviewed 40-digit V7 release-development commit SHA}"
[[ "$EXPECTED" =~ ^[0-9a-f]{40}$ ]] || {
  echo "STOP: V7_EXPECTED_SHA must be the full literal lowercase commit SHA" >&2
  exit 1
}
test "$(git -C "$ROOT" rev-parse HEAD)" = "$EXPECTED"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

mapfile -t ENGINES < <(
  docker ps -aq \
    --filter label=com.docker.compose.project=mv-signal \
    --filter label=com.docker.compose.service=engine
)
test "${#ENGINES[@]}" -eq 1
ENGINE="${ENGINES[0]}"

assert_production_frozen() {
  test "$(docker inspect -f '{{.State.Running}}' "$ENGINE")" = false
  test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$ENGINE")" = no
  for svc in telegram telegram-report ai; do
    mapfile -t refs < <(
      docker ps -aq \
        --filter label=com.docker.compose.project=mv-signal \
        --filter "label=com.docker.compose.service=$svc"
    )
    test "${#refs[@]}" -le 1
    for ref in "${refs[@]}"; do
      test "$(docker inspect -f '{{.State.Running}}' "$ref")" = false
    done
  done
}
assert_production_frozen

command -v python3 >/dev/null
command -v docker >/dev/null
docker compose version >/dev/null

IMAGE="mv-v7sonic-preflight:${EXPECTED:0:12}"
WORK="$(mktemp -d /tmp/v7sonic-isolated-check-XXXXXXXX)"
finish() {
  status=$?
  assert_production_frozen || status=1
  rm -rf -- "$WORK"
  exit "$status"
}
trap finish EXIT

echo "=== 1. ISOLATED IMAGE BUILD; V4 IMAGE UNMODIFIED ==="
docker build --pull=false \
  -f "$ROOT/services/api/Dockerfile" \
  -t "$IMAGE" "$ROOT"

echo "=== 2. NORMALIZE STANDALONE COMPOSE (NO PRODUCTION FILES) ==="
V7_PREFLIGHT_IMAGE="$IMAGE" docker compose \
  --profile v7-private-diagnostics \
  -f "$ROOT/compose.v7sonic-isolated.yml" \
  config --format json > "$WORK/compose.json"

# The script uses umask 077: normalized JSON starts as root-owned 0600.
# The read-only test container runs as UID 10001 and cannot read 0600.
# This JSON is an uncredentialed, standalone *preflight* configuration;
# the containing host directory remains 0700 and the container mount is :ro.
chmod 0644 "$WORK/compose.json"
test "$(stat -c %a "$WORK/compose.json")" = 644

echo "=== 3. VERIFY EXACT ISOLATED RUN CONTRACT ==="
docker run --rm --network none --read-only \
  -v "$WORK/compose.json:/tmp/compose.json:ro" \
  "$IMAGE" python -m app.v7sonic_compose_guard /tmp/compose.json

echo "=== 4. RUN ONLY THE NO-NETWORK V7 PREFLIGHT SERVICE ==="
V7_PREFLIGHT_IMAGE="$IMAGE" docker compose \
  --profile v7-private-diagnostics \
  -f "$ROOT/compose.v7sonic-isolated.yml" \
  run --rm --no-deps v7-preflight

echo "=== 5. VERIFY NO NEW V7 RUNNING SERVICE ==="
test -z "$(docker ps -q \
  --filter label=com.docker.compose.project=mv-v7sonic-isolated)"

echo "ISOLATED V7 PREFLIGHT: PASS"
echo "Production V4 engine: STOPPED"
echo "Production PostgreSQL: NOT CONTACTED BY PREFLIGHT"
echo "Client Telegram: NOT INVOKED"
echo "Exchange orders: NOT SUBMITTED"
