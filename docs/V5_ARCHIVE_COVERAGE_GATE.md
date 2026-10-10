# V5 archive coverage gate — research only

This supplement to [V5_HISTORICAL_ARCHIVES.md](V5_HISTORICAL_ARCHIVES.md)
introduces `app.research.v5_archive_inventory`. No production Compose
service, runtime, database, Telegram, or signal policy is modified.

## Why this gate exists

The frozen V5 proposal includes **30 symbols**, **4 independent kline
timeframes** (1m, 15m, 1h, 4h) and **9 completed months** (January–September
2026). At full scope this is **1,080 separate monthly archive cells**.
Even one physically present ZIP and manifest **cannot** be called freshly
verified without reading and hashing its complete contents. Conversely,
a missing monthly ZIP does not establish symbol inception, delisting,
or a zero-signal month.

Coverage statuses:

* `MISSING` — neither source ZIP nor its pinned manifest is present.
* `PRESENT_UNVERIFIED` — ZIP plus correctly structured pinned manifest are
  present, but this inventory pass did not hash/parse the ZIP; not eligible
  to claim data-integrity PASS.
* `VERIFIED` — explicitly requested full-content verification passed
  (manifest spec, pinned SHA-256 and every expected candle).
* `REVIEW_REQUIRED` — an orphan ZIP/manifest, incorrect manifest,
  invalid archive, or other detected failure. Stop before replay.

`MISSING` and `PRESENT_UNVERIFIED` remain `INCOMPLETE`; do not
translate them into strategy decisions or trading statistics.

## Offline safety-first VPS run

Use **only** the isolated research worktree and already provisioned
`/var/tmp/mv-v5-history-archives` volume. Sync the research branch
fast-forward only if its worktree is clean; never reset or touch
`/opt/mv-signal/app`:

```sh
cd /tmp/mv-v5-history-pilot
test -z "$(git status --porcelain)" || { echo "STOP: research worktree dirty"; exit 1; }
test "$(git branch --show-current)" = "codex/mv-v5-historical-archive-pilot" || {
  echo "STOP: incorrect research branch"; exit 1;
}
git fetch origin codex/mv-v5-historical-archive-pilot
git merge --ff-only FETCH_HEAD
```

Inventory every frozen cell, **without network access** and with
archives and code mounted read-only:

```sh
docker run --rm --network none --read-only --pull never \
  --user 10001:10001 --cpus=0.5 --memory=768m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/strategy:/work/services/api \
  -v /tmp/mv-v5-history-pilot:/work:ro \
  -v /var/tmp/mv-v5-history-archives:/research:ro \
  -w /work/services/api \
  "$(docker inspect -f '{{.Image}}' mv-signal-api-1)" \
  python -m app.research.v5_archive_inventory --root /research
```

The JSON summary should show the same `expected_archive_cells=1080`
regardless of downloaded data, plus per-symbol status counts and up
to 30 actionable missing/review examples. An ordinary incomplete
inventory returns success so users can inspect it; discovered invalid
source state exits 3. `--require-complete` exits 3 unless every
selected cell was fully reverified, never merely manifest-present.

To **deep verify** just BTCUSDT/1h over April–June before any replay,
add:

```sh
python -m app.research.v5_archive_inventory \
  --root /research --symbol BTCUSDT --timeframe 1h \
  --start-month 2026-04 --end-month 2026-06 \
  --deep-verify --require-complete
```

Use that inner command with the exact disposable container invocation
above, not directly within a production container. Deep verification
permits **one symbol and at most three months per run**, so a single
operator action cannot launch 1,080 archive parses. `--include-cells`
adds the full cell-level report. No HTTP, source archive edits,
audit-ledger writes, DB writes, or Telegram messages are performed.

## Controlled advancement after the inventory

1. Complete January–June 1h and 4h pilot batches **one symbol/timeframe
   at a time**, never the full universe unattended; then 15m sources
   for historical trigger reconstruction.
2. For each symbol, verify all archive manifests and independent
   15m→1h→4h exact OHLCV reconciliation. Treat any published 404,
   symbol-inception ambiguity or checksum revision as
   `REVIEW_REQUIRED`; resolve the historical eligibility ledger before
   using the symbol in that period.
3. Expand 1m execution reference data under separate disk/network
   budgets. 1m source equivalence does not establish actual spread,
   funding, fees or Lighter execution.
4. Build chronological, all-symbol V4/V5 replay using the *same*
   completed-candle policy and 500-closed-4h warmup. Reserve
   August–September for one final, policy-frozen performance test.
5. Keep V4 production active until the full evaluation passes and
   deployment is explicitly approved.

**This tool supplies source inventory evidence only; it is not the
30-coin replay engine or a return/profitability assessment.**


## Stage 3 operator pilot — BTC-only historical decision replay

The checked-in shell entry point `tools/v5-btc-replay-pilot.sh`
runs a *read-only*, *network-disabled*, BTC-specific smoke chain. It
refuses a dirty checkout or an unexpected branch/location. The command
executes the two focused test modules, full independently pinned
15m→1h and 1h→4h January–June source reconciliation, then the
`v5_decision_replay` evaluator **only on January–May inputs**, with
March–May classified as development and the initial 500-bar warmup
honored. Reading June candles for the **source-integrity-only** audits
is not June strategy evaluation.

After explicitly verifying the isolated worktree is clean, fast-forward
the research branch and invoke:

```sh
cd /tmp/mv-v5-history-pilot
test -z "$(git status --porcelain)" || exit 2
test "$(git branch --show-current)" = "codex/mv-v5-historical-archive-pilot" || exit 2
git fetch origin codex/mv-v5-historical-archive-pilot
git merge --ff-only FETCH_HEAD
bash tools/v5-btc-replay-pilot.sh
```

No production Compose mutation, collector/backfill, funding, trade
simulation or holdout performance examination takes place.
The command prints the source reconciliation and decision-only JSON;
it ends in `V5_BTC_DEVELOPMENT_DECISION_PILOT: PASS` only if each
prior stage exited successfully. Exit failures require inspection
without skipping checks. Do **not** interpret the result as production
signal totals or profitability; portfolio safety and executable fills
have not been modeled. The script and its execution have **not yet been
independently verified on the operator VPS** as of its addition.
