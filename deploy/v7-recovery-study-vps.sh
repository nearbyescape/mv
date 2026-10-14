#!/usr/bin/env bash
# ONE bounded V7Sonic retrospective research job. NO customer signals/orders.
# Installs nothing on host other than a detached source checkout supplied by operator.
# Required: V7_STUDY_SHA=<reviewed exact head> and opt-in public archive download.
set -Eeuo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SHA="${V7_STUDY_SHA:?Exact reviewed full source SHA required}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"
command -v docker >/dev/null

# Check all original signal publishers and engine, not just one container.
for svc in engine telegram telegram-report ai; do
  mapfile -t cids < <(docker ps -aq \
    --filter label=com.docker.compose.project=mv-signal \
    --filter "label=com.docker.compose.service=$svc")
  if [[ "$svc" == engine || "$svc" == telegram ]]; then
    test "${#cids[@]}" -eq 1
  fi
  for cid in "${cids[@]}"; do
    test "$(docker inspect -f '{{.State.Running}}' "$cid")" = false
    if [[ "$svc" == engine ]]; then
      test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$cid")" = no
    fi
  done
done

IMAGE="mv-v7-recovery-research:${SHA:0:12}"
ARCHIVES="/var/tmp/v7-recovery-publisher-archives"
RESULTS="/var/tmp/v7-recovery-reports"
REPORT="$RESULTS/recovery-${SHA:0:12}.json"
test ! -e "$REPORT"  # no overwrites or unexplained replays
install -d -m 0700 "$ARCHIVES" "$RESULTS"
test ! -L "$ARCHIVES"
test ! -L "$RESULTS"
# Dedicated owner: these are NEW research-only directories, never production.
chown 10001:10001 "$ARCHIVES"
test "$(stat -c %u "$ARCHIVES")" = 10001

echo "=== 1. BUILD EXACT SOURCE RESEARCH IMAGE ==="
docker build --pull=false \
  -f "$ROOT/services/api/Dockerfile" \
  -t "$IMAGE" "$ROOT"

echo "=== 2. OFFLINE NEGATIVE AND STRATEGY TESTS ==="
docker run --rm --pull=never \
  --network none --read-only \
  --user 10001:10001 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 1g --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  "$IMAGE" python -m pytest -q -p no:cacheprovider \
    tests/test_v7_recovery_study.py \
    tests/test_t7sonic_release_candidate.py \
    tests/test_v7sonic_client_delivery.py

echo "=== 3. ACQUIRE CHECKSUM-VERIFIED CLOSED MONTHS ==="
if [[ "${V7_PUBLIC_ARCHIVE_DOWNLOAD_APPROVED:-}" != YES ]]; then
  echo "STOP: No public data download approval; no archive was changed." >&2
  exit 3
fi

docker run --rm --pull=never \
  --network bridge --read-only \
  --user 10001:10001 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 1g --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  --mount "type=bind,source=$ARCHIVES,target=/data" \
  "$IMAGE" python -m app.research.v7_recovery_acquire \
    --data-root /data \
    --acquire --acknowledge-public-download YES \
  > "$RESULTS/archive-acquisition-${SHA:0:12}.json"

echo "=== 4. SIX-MONTH RETROSPECTIVE COSTED RESEARCH ==="
docker run --rm --pull=never \
  --network none --read-only \
  --user 10001:10001 \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --memory 2g --pids-limit 64 \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m,mode=1777 \
  --mount "type=bind,source=$ARCHIVES,target=/data,readonly" \
  "$IMAGE" python -m app.research.v7_recovery_study \
    --data-root /data > "$REPORT"

echo "=== 5. MACHINE-READABLE RESULT GATE ==="
python3 - "$REPORT" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    p=json.load(f)
assert p["status"] == "V7_SIX_MONTH_COSTED_RESEARCH_ONLY_NO_PRODUCTION_AUTHORIZATION"
assert p["client_publication_authorized"] is False
assert p["orders_submitted"] == p["telegram_messages_sent"] == 0
assert p["promotable_without_later_unseen_prospective_validation"] is False
assert p["complete_15m_bars_per_market"] >= 17000
assert len(p["source_provenance"]) == 6
for symbol, parts in p["source_provenance"].items():
    assert len(parts) == 6, symbol
s = p["full_exploratory_summary"]
print("V7 SIX-MONTH RETROSPECTIVE RESEARCH: PASS")
print("Total qualifying proposals:", p["proposals_before_portfolio_filters"])
print("Portfolio-selected references:", p["selected_paper_references"])
print("Hypothetical closed ideas:", s["hypothetical_closed_ideas"])
print("Mean net R:", s["mean_costed_R_per_closed_reference"])
print("Day-clustered 95% CI:", s["day_cluster_bootstrap_mean_R_95pct"])
print("Closed-trade drawdown (illustrative):", s["illustrative_closed_trades_only_max_drawdown"])
print("Economic readiness established: NO (retrospective data)")
PY

echo "=== 6. FINAL NO-PRODUCTION CHECK ==="
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"
test "$(docker inspect -f '{{.State.Running}}' mv-signal-engine-1)" = false
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' mv-signal-engine-1)" = no
echo "No customer Telegram message or exchange order sent by this job."
echo "Full signed research report: $REPORT"
echo "Production remains suspended."
