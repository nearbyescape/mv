#!/usr/bin/env bash
# Isolated ETHUSDT 1h/4h Jan-Jun 2026 V5 archive pilot.
# PLAN (default) and VERIFY do not use the network. FETCH needs --confirm-fetch.
# Never runs in production Compose, never edits the live scanner/DB/Telegram.
set -Eeuo pipefail

readonly WT=/tmp/mv-v5-history-pilot
readonly RESEARCH=/var/tmp/mv-v5-history-archives
readonly BRANCH=codex/mv-v5-historical-archive-pilot
readonly SYMBOL=ETHUSDT

mode="${1:-plan}"
if [[ "$mode" == "fetch" ]]; then
  if [[ "${2:-}" != "--confirm-fetch" || "$#" -ne 2 ]]; then
    echo "STOP: fetch requires explicit argument: fetch --confirm-fetch" >&2
    exit 2
  fi
elif [[ "$mode" == "plan" || "$mode" == "verify" ]]; then
  if [[ "$#" -gt 1 ]]; then
    echo "STOP: unexpected extra arguments" >&2
    exit 2
  fi
else
  echo "Usage: bash tools/v5-eth-foundation-pilot.sh [plan|verify|fetch --confirm-fetch]" >&2
  exit 2
fi

[[ -d "$WT/.git" || -f "$WT/.git" ]] || {
  echo "STOP: isolated research worktree missing" >&2
  exit 2
}
[[ "$(git -C "$WT" branch --show-current)" == "$BRANCH" ]] || {
  echo "STOP: wrong branch" >&2
  exit 2
}
[[ -z "$(git -C "$WT" status --porcelain)" ]] || {
  echo "STOP: research worktree dirty" >&2
  exit 2
}
[[ -d "$RESEARCH" && ! -L "$RESEARCH" ]] || {
  echo "STOP: research volume missing or symlinked" >&2
  exit 2
}
[[ "$(realpath -e "$RESEARCH")" == "$RESEARCH" ]] || {
  echo "STOP: unexpected research volume path" >&2
  exit 2
}
[[ -d "$WT/services/api" ]] || {
  echo "STOP: research backend missing" >&2
  exit 2
}

# Disk guard at the host boundary is supplementary to the fetcher's
# per-archive free-space floor and checksum/strict continuity validation.
if [[ "$mode" == "fetch" ]]; then
  free_mib="$(df -Pm "$RESEARCH" | awk 'NR == 2 {print $4}')"
  [[ "$free_mib" =~ ^[0-9]+$ && "$free_mib" -ge 2304 ]] || {
    echo "STOP: research volume must have at least 2304 MiB available" >&2
    exit 2
  }
fi

image="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
[[ "$image" == sha256:* ]] || {
  echo "STOP: cannot pin existing API image by digest" >&2
  exit 2
}

container_args=(
  --rm --pull never --read-only
  --cap-drop ALL --security-opt no-new-privileges
  --pids-limit 64
  --user 10001:10001 --cpus=0.5 --memory=768m
  --tmpfs /tmp:rw,nosuid,nodev,size=64m
  -e PYTHONDONTWRITEBYTECODE=1
  -e PYTHONPATH=/work/packages/strategy:/work/services/api
  -v "$WT:/work:ro"
  -w /work/services/api
)
case "$mode" in
  fetch)
    # Container uses only the standalone default Docker bridge for outbound
    # HTTPS to the archive publisher, never the production Compose network.
    container_args+=(--network bridge -v "$RESEARCH:/research:rw")
    ;;
  *)
    container_args+=(--network none -v "$RESEARCH:/research:ro")
    ;;
esac

echo "=== V5 ETHUSDT 1h/4h 2026-01..2026-06 $mode ==="
echo "Research SHA: $(git -C "$WT" rev-parse HEAD)"
echo "Research root: $RESEARCH"
echo "No production Compose invocation, collector writes or database credentials."

run_archive() {
  local action="$1" frame="$2"
  local args=(
    python -m app.research.v5_archive_batch "$action"
    --root /research --symbol "$SYMBOL" --timeframe "$frame"
    --start-month 2026-01 --end-month 2026-06
  )
  if [[ "$action" == "fetch" ]]; then
    args+=(--max-new-mib 64 --min-free-mib 2048 --delay-seconds 1.25 --confirm-fetch)
  fi
  docker run "${container_args[@]}" "$image" "${args[@]}"
}

case "$mode" in
  plan)
    run_archive plan 1h
    run_archive plan 4h
    ;;
  fetch)
    echo "Source acquisition uses live publisher checksum and maximum 64 MiB per timeframe invocation."
    run_archive fetch 1h
    run_archive fetch 4h
    echo "Network acquisition completed; immediately verifying from local files offline."
    exec bash "$WT/tools/v5-eth-foundation-pilot.sh" verify
    ;;
  verify)
    run_archive verify 1h
    run_archive verify 4h
    docker run "${container_args[@]}" "$image" \
      python -m app.research.v5_archive_audit reconcile-1h-4h \
      --root /research --symbol "$SYMBOL" \
      --start-month 2026-01 --end-month 2026-06
    echo "V5_ETH_FOUNDATION_SOURCE_RECONCILIATION: PASS"
    echo "This verifies source integrity only, NOT candidate replay, signal accuracy, fills or profitability."
    ;;
esac
