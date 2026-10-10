#!/usr/bin/env bash
# V6HBR BTC April-May source-bound full candidate export (NO PNL, NO LIVE ACTION).
# Only runs in the previously approved isolated research worktree.
set -Eeuo pipefail

WT="/tmp/mv-v5-history-pilot"
ARCH="/var/tmp/mv-v5-history-archives"
SPEC_SHA="48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64"

test "$(cd "$WT" && pwd -P)" = "$WT"
test "$(git -C "$WT" branch --show-current)" = "codex/mv-v6hbr-research"
test -z "$(git -C "$WT" status --porcelain)"
test -d "$ARCH"
test ! -L "$ARCH"
test "$(realpath -e "$ARCH")" = "$ARCH"
echo "$SPEC_SHA  $WT/packages/contracts/v5-history-v1.json" | sha256sum -c -

IMAGE="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
[[ "$IMAGE" == sha256:* ]] || {
  echo "STOP: pinned existing API image unavailable" >&2
  exit 2
}

echo "V6HBR isolated research HEAD: $(git -C "$WT" rev-parse HEAD)"
docker run --rm --pull never \
  --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges \
  --pids-limit 64 --user 10001:10001 \
  --cpus=0.5 --memory=768m \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/strategy:/work/services/api \
  -v "$WT:/work:ro" -v "$ARCH:/research:ro" \
  -w /work/services/api "$IMAGE" sh -eu -c '
    echo "=== V6HBR unit regressions (pure research code) ==="
    python -m pytest -q -p no:cacheprovider \
      tests/test_v6hbr_candidate_export.py \
      tests/test_v6hbr_execution_model.py

    echo "=== BTC April-May full decision-only candidate export ==="
    python -m app.research.v6hbr_candidate_export \
      --root /research --symbol BTCUSDT \
      --start 2026-04-01 --end 2026-06-01 \
      > /tmp/v6hbr-candidates.json

    python -c '"'"'
import json
from pathlib import Path
r = json.loads(Path("/tmp/v6hbr-candidates.json").read_text())
print(json.dumps({
    "status": r["status"],
    "candidate_count": r["candidates"],
    "v4_base": r["v4_base"],
    "15m_rescue": r["15m_rescue"],
    "reference_digest": r["reference_candidate_stream_sha256"],
    "export_digest": r["export_stream_sha256"],
    "source_series_sha256": r["source_series_sha256"],
    "holdout_access": False,
    "net_performance_claim": None,
}, indent=2, sort_keys=True))
'"'"'
    echo "V6HBR_BTC_CANDIDATE_EXPORT: PASS (NOT PNL)"
  '
