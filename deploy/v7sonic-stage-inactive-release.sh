#!/usr/bin/env bash
# Stage V7Sonic CODE and an isolated preflight image tonight, but DO NOT
# switch production or activate trading/client Telegram.
# REQUIRE: reviewed clean detached worktree at exact SHA, root on VPS.
#
#   V7_EXPECTED_SHA=<reviewed-full-40-hex-commit> \
#     bash deploy/v7sonic-stage-inactive-release.sh
#
# This script NEVER changes /opt/mv-signal/app, any production Compose
# service, database, customer Telegram, exchange orders, or active systemd.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SHA="${V7_EXPECTED_SHA:?Pinned reviewed 40-digit V7 source SHA required}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || {
  echo "STOP: exact full lowercase SHA is required" >&2
  exit 2
}
test "$(id -u)" = 0
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" =   "/opt/mv-signal/releases/mv-signal-0.14.0"

# The client sender is intentionally not implemented as an automated
# certified production service. Never imply this is a live cutover.
grep -q 'NO AUTOMATIC RELEASE PRODUCER OR STARTUP ENTRYPOINT' \
  "$ROOT/services/api/app/v7sonic_client_delivery.py"
grep -q 'No automatic promotion is implemented' \
  "$ROOT/docs/V7SONIC_RELEASE_GATE.md"

assert_v4_frozen() {
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
assert_v4_frozen

# No room for ambiguous staging: never overwrite, append into an
# existing release, or convert a previously staged SHA to 'live'.
PARENT="/opt/mv-signal/v7sonic-inactive-staging"
TARGET="$PARENT/v7sonic-$SHA"
if test -e "$TARGET" || test -L "$TARGET"; then
  echo "STOP: exact staged release already exists: $TARGET" >&2
  exit 3
fi
if test -e "$PARENT"; then
  test -d "$PARENT"
  test ! -L "$PARENT"
else
  install -d -m 0700 "$PARENT"
fi
test "$(stat -c %u "$PARENT")" = 0
test "$(stat -c %a "$PARENT")" = 700

# The existing gate uses a SEPARATE Compose project, --network none
# preflight, no DB or Telegram secrets, and never creates a persistent
# V7 daemon. Failure stops before any staging artifact is published.
echo "=== EXISTING EXACT-SHA ISOLATED NO-SEND CERTIFICATION ==="
V7_EXPECTED_SHA="$SHA" \
  bash "$ROOT/deploy/v7sonic-verify-isolated.sh"
assert_v4_frozen

IMAGE="mv-v7sonic-preflight:${SHA:0:12}"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$IMAGE")"
[[ "$IMAGE_ID" == sha256:* ]] || {
  echo "STOP: missing isolated preflight image digest" >&2
  exit 4
}

# Snapshot tracked source, NOT user .env / SSH files / production
# bind mounts. Publish atomically after writing audit manifest.
WORK="$(mktemp -d "$PARENT/.v7sonic-build-${SHA:0:12}-XXXXXXXX")"
cleanup() {
  local rc=$?
  trap - EXIT
  if test -d "$WORK" && [[ "$WORK" == "$PARENT"/.v7sonic-build-* ]]; then
    rm -rf -- "$WORK"
  fi
  if ! assert_v4_frozen; then
    echo "CRITICAL: retired V4 worker state changed during staging" >&2
    exit 1
  fi
  exit "$rc"
}
trap cleanup EXIT

echo "=== SNAPSHOT REVIEWED TRACKED SOURCE WITHOUT CHANGING PRODUCTION ==="
git -C "$ROOT" archive --format=tar "$SHA" |
  tar -C "$WORK" --no-same-owner --no-same-permissions -xf -
test -f "$WORK/services/api/app/v7sonic_release.py"
test -f "$WORK/deploy/v7sonic-four-cycle-systemd-launch.sh"
test ! -e "$WORK/.env"
test ! -e "$WORK/deploy/production.env"
test ! -e "$WORK/.git"

python3 - "$WORK" "$SHA" "$IMAGE" "$IMAGE_ID" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

folder, git_sha, image, digest = sys.argv[1:]
root = Path(folder)
source_files = sorted(
    p for p in root.rglob("*") if p.is_file() and not p.is_symlink()
)
manifest = {
    "schema": 1,
    "status": "V7_INACTIVE_CODE_STAGED_NO_CLIENT_PUBLICATION",
    "commit_sha": git_sha,
    "preflight_image": image,
    "preflight_image_id": digest,
    "staged_at_utc_unattested": datetime.now(timezone.utc).isoformat(),
    "file_count": len(source_files),
    "source_manifest_sha256": sha256(
        b"".join(
            str(p.relative_to(root)).encode() + b"\0" +
            sha256(p.read_bytes()).digest() for p in source_files
        )
    ).hexdigest(),
    "production_symlink_changed": False,
    "production_database_migrated": False,
    "client_telegram_enabled": False,
    "exchange_order_routing_enabled": False,
    "v4_workers_restarted": False,
    "production_cutover_certified": False,
}
(root / "V7_INACTIVE_STAGE_MANIFEST.json").write_text(
    json.dumps(manifest, sort_keys=True, indent=2) + "\n"
)
print(json.dumps(manifest, sort_keys=True, indent=2))
PY
chmod -R go-rwx "$WORK"
assert_v4_frozen
test ! -e "$TARGET"
mv -T -- "$WORK" "$TARGET"
WORK=""  # atomic stage completed; trap must not remove it

assert_v4_frozen
test "$(readlink -f /opt/mv-signal/app)" =   "/opt/mv-signal/releases/mv-signal-0.14.0"

echo "=== V7 INACTIVE RELEASE STAGING: PASS ==="
echo "Code snapshot: $TARGET"
echo "Preflight image: $IMAGE"
echo "PRODUCTION CUTOVER: NOT PERFORMED"
echo "CLIENT TELEGRAM: DISABLED"
echo "V4 WORKERS: STILL STOPPED"
echo "NO PRODUCTION DATABASE MIGRATIONS OR ORDER API"
