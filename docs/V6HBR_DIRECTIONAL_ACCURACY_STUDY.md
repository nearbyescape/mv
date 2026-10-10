# MV V6HBR — predecision directional accuracy laboratory

**Engineering state:** The new code is a reproducible research analysis capability, not a trained directional predictor and not a trade recommendation. Real improvement requires the VPS archive run, causal baseline comparison and independent validation. This report intentionally keeps deployment out of scope.

## The exact accuracy question

For EACH original V4 base or first qualified 15-minute rescue candidate at a closed-candle publication time, measure whether the price from the *next complete 15-minute candle opening* moves in the intended direction by a meaningful amount. Do this over fixed 15, 30, 60 and 120 minute forward windows. A nominal 10 bps round-trip price-move hurdle is an illustration, not observed exchange costs.

Report three mutually exclusive outcomes per horizon:

- DIRECTION_SUPPORTED_OVER_HURDLE: signed closing move is greater than +10 bps.
- DIRECTION_OPPOSITE_OVER_HURDLE: signed closing move is less than -10 bps.
- NEUTRAL_WITHIN_HURDLE: signed closing move stays within ±10 bps.

Also report whether market price first touched -0.5 of the original *1h ATR* against the proposed signal or +0.5 ATR in favor, assuming adverse-first if both thresholds are crossed by the same 15m bar. This is a directional diagnostic, distinct from the historical 1m execution-model stop or 0.5R milestone. Reports display observation and censoring counts rather than pretending end-of-window trades are wins.

There are four predeclared *decision-time feature hypotheses*: original unfiltered candidate stream, established trend regime only, momentum-breakout source extension at most 1 ATR beyond source 1h EMA20, and their combination. Each subset's retained/rejected count and directional score are shown. The fully chronological portfolio veto comparison remains a separate component; a filtered directional score is not itself the portfolio's executable win rate.

Output: overall; by V4 vs 15m rescue, long vs short, emerging vs established, breakout vs pullback; by symbol; and per fixed hypothesis. For each 15/30/60/120m horizon, report counts of supported/opposite/neutral, marginal Wilson 95% directional interval and exploratory day-clustered interval on equal-day signed forward BPS after the illustrative hurdle. Day clustering is not a cure for signal overlap, serial correlation, selection bias or regime changes, and cannot be represented as guaranteed accuracy.

## Data provenance / unchanged original candidate rules

Module `services/api/app/research/v6hbr_directional_development.py` is explicitly restricted to **April–May 2026 development outcomes**, using only checksum-pinned Jan–May 2026 historical archive sources. Original candidate generation is reconciled against the inherited frozen V5 decision replay. It will refuse to summarize the default 30-market study if even one selected symbol archive is missing. An explicitly selected single-symbol subset is labelled as a **smoke test**, not 30-coin validation. The original `v5-history-v1.json` file, SHA `48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64`, is never rewritten.

Only 15m, 1h and 4h historical snapshots are needed for these **directional labels**. There are **no real fills**, no adverse 1m slip simulation, no actual Lighter order-book constraints, funding or fees, no contemporaneous October signal performance, and no assumed final profitability. The separate BTC cost-replay module handles limited 1m reference execution scenarios; it is not replaced by this accuracy-only scorecard.

## Operator-run analysis (isolation preserved)

The hourly service already stages verified read-only GitHub source archives under `/var/lib/mv-v6hbr-auto/sources/<exact-commit-sha>`. Once its latest SHA has been staged, the operator can perform this OPTIONAL read-only, offline study without executing remote shell scripts on the host. **Do not run the command on production V4 containers.** It creates a disposable network-disabled research container using an existing inspected image.

```bash
bash <<'BASH'
set -Eeuo pipefail
umask 077
BASE=/var/lib/mv-v6hbr-auto
REPO="$BASE/repository"
HEAD="$(git -C "$REPO" rev-parse refs/remotes/origin/codex/mv-v6hbr-research)"
[[ "$HEAD" =~ ^[0-9a-f]{40}$ ]]
SOURCE="$BASE/sources/$HEAD"
ARCH=/var/tmp/mv-v5-history-archives
REPORT="$BASE/reports/v6hbr-directional-$HEAD.json"
test -d "$SOURCE" && test ! -L "$SOURCE"
test "$(realpath -e "$SOURCE")" = "$SOURCE"
test "$(realpath -e "$ARCH")" = "$ARCH"
test ! -L "$ARCH"
echo '48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64  '"$SOURCE"'/packages/contracts/v5-history-v1.json' | sha256sum -c -
IMAGE="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"
[[ "$IMAGE" == sha256:* ]]
TMP="$(mktemp "$BASE/reports/.directional.XXXXXXXX")"
trap 'rm -f "$TMP"' EXIT
docker run --rm --pull never --log-driver none \
  --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 80 --cpus=0.75 --memory=2g --memory-swap=2g \
  --user 10001:10001 \
  --tmpfs /tmp:rw,nosuid,nodev,size=128m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/strategy:/work/services/api \
  -v "$SOURCE:/work:ro" -v "$ARCH:/research:ro" \
  -w /work/services/api "$IMAGE" \
  python -m app.research.v6hbr_directional_development --root /research > "$TMP"
python3 -m json.tool "$TMP" >/dev/null
mv -f "$TMP" "$REPORT"
trap - EXIT
echo "Complete offline directional research report: $REPORT"
BASH
```

The container has no network and no production DB/Telegram mounts, makes no orders, uses at most 0.75 CPU and 2GB of RAM, reads frozen code and source data read-only, and writes ONLY the output report through host shell redirection. If a source archive has not been collected or is incomplete, the job fails instead of substituting estimated data. Do not restart V4 to address research data gaps.

The operator can inspect the report's `directional_accuracy.overall` and `directional_accuracy.predeclared_predecision_filter_slices` JSON objects. For a smaller smoke run, add `--symbols BTCUSDT` to the Python command **inside** Docker, and clearly label it as single-symbol only.

## Interpretation and next gate

Direction percentages alone can rise when a filter throws away most opportunities. Every comparison must include rejected counts, net returns AFTER actual execution costs, portfolio risk and false-negative missed opportunities. A fixed hypothesis is only worth further study if it simultaneously improves conditional downside and candidate-level directional correctness without severe coverage loss. The strategy choice cannot be decided from these April–May development results and described as independently accurate: use June–July validation and keep August–September holdout sealed until the protocol has been frozen.

**No signal-rule changes or live publication are included in this work.**
