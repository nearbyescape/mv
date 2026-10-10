#!/usr/bin/env bash
# V6HBR: isolated BTC April-May execution COST-SCENARIO PROXY, NOT REAL FILLS.
# No order placement, DB, production Compose, Telegram, downloads or holdout.
set -Eeuo pipefail

WT=/tmp/mv-v5-history-pilot
ARCH=/var/tmp/mv-v5-history-archives
SPEC_SHA=48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64

test "$(cd "$WT" && pwd -P)" = "$WT"
test "$(git -C "$WT" branch --show-current)" = "codex/mv-v6hbr-research"
test -z "$(git -C "$WT" status --porcelain)"
test -d "$ARCH" && test ! -L "$ARCH"
test "$(realpath -e "$ARCH")" = "$ARCH"
echo "$SPEC_SHA  $WT/packages/contracts/v5-history-v1.json" | sha256sum -c -

IMAGE="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
[[ "$IMAGE" == sha256:* ]] || { echo "STOP: pinned API image unavailable" >&2; exit 2; }

echo "V6HBR isolated proxy research commit: $(git -C "$WT" rev-parse HEAD)"
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
    echo "=== RESEARCH REGRESSION SUITE ==="
    python -m pytest -q -p no:cacheprovider \
      tests/test_v6hbr_candidate_export.py \
      tests/test_v6hbr_execution_model.py \
      tests/test_v6hbr_portfolio_replay.py \
      tests/test_v6hbr_btc_pricing_pilot.py \
      tests/test_v6hbr_candidate_operator_script.py \
      tests/test_v6hbr_operator_pilots.py

    echo "=== BTC APRIL-MAY EXPLICIT-COST PROXY, NOT REALIZED PNL ==="
    python -m app.research.v6hbr_btc_pricing_pilot \
      --root /research \
      --assumed-tick 0.1 \
      --spread-bps 2 \
      --slippage-bps 2 \
      --taker-fee-bps 5 \
      --funding-debit-bps-per-8h 1 \
      --latency-minutes 1 \
      --risk-unit 1 \
      --max-aggregate-risk 4 \
      --acknowledge-proxy-not-fills \
      > /tmp/v6hbr-btc-proxy.json

    python -c '"'"'
import json
from pathlib import Path
r = json.loads(Path("/tmp/v6hbr-btc-proxy.json").read_text())
print(json.dumps({
    "status": r["status"],
    "candidate_count": r["candidate_count"],
    "historical_source_sha256": r["source_series_sha256"],
    "pricing_reasons": r["pricing_preliminary_reasons"],
    "assumptions": r["assumptions"],
    "cohorts": {
        k: {
            "accepted_references": v["accepted_references"],
            "resolved_references": v["resolved_references"],
            "unresolved_references": v["unresolved_references"],
            "resolved_net_r_sum": v["resolved_net_r_sum"],
            "resolved_net_r_mean": v["resolved_net_r_mean"],
            "v4_base_ids_displaced": v.get("v4_base_ids_displaced", []),
            "rejections": v["rejections"],
        } for k,v in r["cohorts"].items()
    },
    "limitations": r["limitations"],
}, sort_keys=True, indent=2))
'"'"'
    echo "V6HBR_BTC_COST_SCENARIO_PROXY: PASS (NOT CERTIFIED TRADING PNL)"
  '
