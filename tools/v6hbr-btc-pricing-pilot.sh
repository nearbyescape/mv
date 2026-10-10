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
      tests/test_v6hbr_attribution.py \
      tests/test_v6hbr_decimal_reconciliation.py \
      tests/test_v6hbr_quality_diagnostics.py \
      tests/test_v6hbr_entry_adversity.py \
      tests/test_v6hbr_live_v4_forensics.py \
      tests/test_v6hbr_live_export_safety.py \
      tests/test_v6hbr_release_readiness.py \
      tests/test_v6hbr_math_abstention.py \
      tests/test_v6hbr_abstention_audit.py \
      tests/test_v6hbr_conservative_veto_stress.py \
      tests/test_v6hbr_directional_accuracy.py \
      tests/test_v6hbr_directional_development.py \
      tests/test_v6hbr_directional_preflight.py \
      tests/test_v6hbr_btc_pricing_operator.py \
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
    "attribution": {
        k: {
            "accepted_by_lane": v["accepted_by_lane"],
            "resolved_net_r_by_lane": v["resolved_net_r_by_lane"],
            "resolved_fee_debit_r_by_lane": v["resolved_fee_debit_r_by_lane"],
            "resolved_funding_debit_r_by_lane": v["resolved_funding_debit_r_by_lane"],
            "missing_v4_base_count": v["missing_v4_base_count"],
            "missing_v4_base_with_demonstrated_rescue_blocker": v["missing_v4_base_with_demonstrated_rescue_blocker"],
            "missing_v4_base_by_reason": v["missing_v4_base_by_reason"],
            "missing_v4_base_details": v["missing_v4_base_details"],
        } for k,v in r["post_hoc_attribution"]["cohorts"].items()
    },
    "balanced_rescue_filter_invariant": r["post_hoc_attribution"]["balanced_rescue_filter_invariant"],
    "hybrid_reserved_identical_accepted_ids": r["post_hoc_attribution"]["hybrid_reserved_identical_accepted_ids"],
    "limitations": r["limitations"],
}, sort_keys=True, indent=2))
'"'"'
    echo "V6HBR_BTC_COST_SCENARIO_PROXY: PASS (NOT CERTIFIED TRADING PNL)"
  '
