#!/usr/bin/env bash
# MV V5: BTC-only, development-period, read-only source + decision replay pilot.
# Intentionally no production writes, downloads, database, Telegram or holdout access.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
BR="codex/mv-v5-historical-archive-pilot"
ARCHIVES="/var/tmp/mv-v5-history-archives"

if [[ "$WT" != "/tmp/mv-v5-history-pilot" ]]; then
    printf 'STOP: unexpected worktree %s\n' "$WT" >&2
    exit 2
fi
if [[ "$(git -C "$WT" branch --show-current)" != "$BR" ]]; then
    echo "STOP: expected V5 isolated research branch" >&2
    exit 2
fi
if [[ -n "$(git -C "$WT" status --porcelain)" ]]; then
    echo "STOP: isolated research worktree is not clean" >&2
    exit 2
fi
if [[ ! -d "$ARCHIVES" ]]; then
    echo "STOP: research archive directory is absent" >&2
    exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
    echo "STOP: docker is unavailable" >&2
    exit 2
fi

IMAGE="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
if [[ -z "$IMAGE" || "$IMAGE" != sha256:* ]]; then
    echo "STOP: could not read the existing production API image identifier" >&2
    exit 2
fi
printf 'V5 development pilot: isolated research checkout at %s\n' "$WT"
printf 'Research commit: %s\n' "$(git -C "$WT" rev-parse HEAD)"
printf 'Runs OFFLINE with both worktree and archives mounted READ-ONLY.\n'
printf 'Scope: BTCUSDT Jan-Jun source audit, Jan-May development decisions only.\n'

docker run --rm \
    --network none --read-only --pull never \
    --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 64 --user 10001:10001 \
    --cpus=0.5 --memory=768m \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/work/packages/strategy:/work/services/api \
    -v "$WT":/work:ro \
    -v "$ARCHIVES":/research:ro \
    -w /work/services/api \
    "$IMAGE" \
    sh -eu -c '
        echo "=== 1. Offline inventory and decision replay unit tests ==="
        python -m pytest -q -p no:cacheprovider \
            tests/test_v5_archive_inventory.py \
            tests/test_v5_decision_replay.py

        echo "=== 2. Independent BTC 15m to 1h OHLCV source reconciliation ==="
        python -m app.research.v5_archive_audit reconcile-15m-1h \
            --root /research --symbol BTCUSDT \
            --start-month 2026-01 --end-month 2026-06

        echo "=== 3. Independent BTC 1h to 4h OHLCV source reconciliation ==="
        python -m app.research.v5_archive_audit reconcile-1h-4h \
            --root /research --symbol BTCUSDT \
            --start-month 2026-01 --end-month 2026-06

        echo "=== 4. BTC V4 / V5 Jan-May development decisions, no P&L ==="
        python -m app.research.v5_decision_replay \
            --root /research --symbol BTCUSDT \
            --start-month 2026-01 --end-month 2026-05

        echo "V5_BTC_DEVELOPMENT_DECISION_PILOT: PASS"
    '
