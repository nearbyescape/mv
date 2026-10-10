#!/usr/bin/env bash
# Root-owned, fixed-host V6HBR automation runner.
# Installed once from a PINNED reviewed SHA; never executes fetched shell
# or Python on the host. New research code runs only inside networkless,
# read-only, capability-free, resource-limited Docker.
set -Eeuo pipefail
umask 077

ROOT=/var/lib/mv-v6hbr-auto
REPO="$ROOT/repository"
SRCDIR="$ROOT/sources"
REPORTS="$ROOT/reports"
ARCH=/var/tmp/mv-v5-history-archives
BRANCH=codex/mv-v6hbr-research
BASELINE="$ROOT/last-reviewed-ancestor"
LAST="$ROOT/last-executed-sha"
LOCK="$ROOT/agent.lock"
SPEC=48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64

test "$(id -u)" -eq 0
test "$(realpath -e "$ROOT")" = "$ROOT"
test ! -L "$ROOT" && test ! -L "$ARCH"
test "$(realpath -e "$ARCH")" = "$ARCH"
test -d "$REPO/.git" && test -d "$SRCDIR" && test -d "$REPORTS"
test -f "$BASELINE" && test ! -L "$BASELINE"
[[ "$(cat "$BASELINE")" =~ ^[0-9a-f]{40}$ ]]

exec 9>"$LOCK"
flock -n 9 || exit 0

# No git checkout, scripts, code, or hooks run from remote on the HOST.
GIT_TERMINAL_PROMPT=0 git -C "$REPO" -c core.hooksPath=/dev/null \
  fetch --no-tags origin \
  "refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
HEAD="$(git -C "$REPO" rev-parse --verify "refs/remotes/origin/$BRANCH^{commit}")"
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]] || exit 2
git -C "$REPO" merge-base --is-ancestor "$(cat "$BASELINE")" "$HEAD" || {
  echo "STOP: research history rewritten or no longer descends from approved installation commit" >&2
  exit 2
}
if test -f "$LAST"; then
  PREVIOUS="$(cat "$LAST")"
  [[ "$PREVIOUS" =~ ^[0-9a-f]{40}$ ]] || exit 2
  git -C "$REPO" merge-base --is-ancestor "$PREVIOUS" "$HEAD" || {
    echo "STOP: non-fast-forward research head" >&2
    exit 2
  }
  if test "$HEAD" = "$PREVIOUS"; then
    echo "No new research commit. Last executed: $HEAD"
    exit 0
  fi
fi

SOURCE="$SRCDIR/$HEAD"
if test ! -d "$SOURCE"; then
  WORK="$(mktemp -d "$SRCDIR/.extract.XXXXXXXX")"
  # A Git archive is data-only on the host. All strategy tests run in Docker.
  git -C "$REPO" archive --format=tar "$HEAD" | python3 -c '
import pathlib
import shutil
import sys
import tarfile

root = pathlib.Path(sys.argv[1]).resolve(strict=True)
total = 0
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as archive:
    for member in archive:
        p = pathlib.PurePosixPath(member.name)
        if p.is_absolute() or not p.parts or ".." in p.parts:
            raise SystemExit("STOP: invalid repository archive path")
        dest = root.joinpath(*p.parts)
        if member.isdir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if not member.isfile():
            raise SystemExit("STOP: archive symlinks and special files prohibited")
        total += member.size
        if total > 250_000_000:
            raise SystemExit("STOP: research checkout archive exceeds size limit")
        dest.parent.mkdir(parents=True, exist_ok=True)
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit("STOP: unreadable archive file")
        with dest.open("xb") as output:
            shutil.copyfileobj(stream, output)
' "$WORK"
  test "$(sha256sum "$WORK/packages/contracts/v5-history-v1.json" | cut -d' ' -f1)" = "$SPEC"
  chmod -R a+rX "$WORK"
  mv "$WORK" "$SOURCE"
fi
test ! -L "$SOURCE"
test "$(realpath -e "$SOURCE")" = "$SOURCE"
test "$(sha256sum "$SOURCE/packages/contracts/v5-history-v1.json" | cut -d' ' -f1)" = "$SPEC"

# INSPECT image: never restart/stop/rebuild the production API.
IMAGE="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
[[ "$IMAGE" == sha256:* ]] || exit 2

LOG="$REPORTS/$HEAD.log"
TMP="$(mktemp "$REPORTS/.run.XXXXXXXX")"
STATUS=1
{
  echo "V6HBR_OFFLINE_AUTOMATION"
  echo "sha=$HEAD"
  echo "source_spec=$SPEC"
  echo "execution_model=ILLUSTRATIVE_COST_SCENARIO_NOT_REAL_FILLS"
  if timeout --signal=TERM --kill-after=30s 35m \
    docker run --rm --pull never --name "v6hbr-auto-$(printf '%.12s' "$HEAD")" \
    --network none --read-only \
    --cap-drop ALL --security-opt no-new-privileges \
    --pids-limit 64 --cpus=0.5 --memory=768m --memory-swap=768m \
    --user 10001:10001 \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/work/packages/strategy:/work/services/api \
    -v "$SOURCE:/work:ro" -v "$ARCH:/research:ro" \
    -w /work/services/api "$IMAGE" sh -eu -c '
      python -m pytest -q -p no:cacheprovider \
        tests/test_v6hbr_candidate_export.py \
        tests/test_v6hbr_execution_model.py \
        tests/test_v6hbr_portfolio_replay.py \
        tests/test_v6hbr_btc_pricing_pilot.py \
        tests/test_v6hbr_attribution.py \
        tests/test_v6hbr_candidate_operator_script.py \
        tests/test_v6hbr_btc_pricing_operator.py \
        tests/test_v6hbr_operator_pilots.py

      python -m app.research.v6hbr_btc_pricing_pilot \
        --root /research \
        --assumed-tick 0.1 --spread-bps 2 --slippage-bps 2 \
        --taker-fee-bps 5 --funding-debit-bps-per-8h 1 \
        --latency-minutes 1 --risk-unit 1 --max-aggregate-risk 4 \
        --acknowledge-proxy-not-fills > /tmp/proxy.json

      python -c '"'"'
import json
from pathlib import Path
report = json.loads(Path("/tmp/proxy.json").read_text())
print(json.dumps({
  "status": report["status"],
  "candidate_count": report["candidate_count"],
  "assumptions": report["assumptions"],
  "cohorts": {
    k: {
      "accepted_references": v["accepted_references"],
      "resolved_references": v["resolved_references"],
      "unresolved_references": v["unresolved_references"],
      "resolved_net_r_sum": v["resolved_net_r_sum"],
      "resolved_net_r_mean": v["resolved_net_r_mean"],
      "v4_base_ids_displaced": v.get("v4_base_ids_displaced", []),
    } for k, v in report["cohorts"].items()
  },
  "attribution": report["post_hoc_attribution"],
  "limitations": report["limitations"],
}, indent=2, sort_keys=True))
'"'"'
    '; then
    STATUS=0
    echo "V6HBR_AUTOMATED_OFFLINE_RESEARCH_PASS"
  else
    STATUS=$?
    echo "V6HBR_AUTOMATED_OFFLINE_RESEARCH_FAIL exit_code=$STATUS"
  fi
} > "$TMP" 2>&1

mv -f "$TMP" "$LOG"
printf '%s\n' "$HEAD" > "$LAST"
printf 'commit=%s\nexit_code=%s\nlog=%s\n' "$HEAD" "$STATUS" "$LOG" > "$REPORTS/latest.txt"
if test "$STATUS" -ne 0; then
  echo "V6HBR research failed; see $LOG" >&2
  exit "$STATUS"
fi
echo "V6HBR research passed. Results: $LOG"
