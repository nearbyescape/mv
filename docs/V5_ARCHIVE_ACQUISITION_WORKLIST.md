# V5 historical archive worklist — no production changes

**Status: research-only implementation; new tests not yet VPS-executed.**

The frozen V5 spec contains 30 symbols × 4 timeframes × 9 months =
**1,080 independent Binance USD-M monthly archive cells**. The 10 October
offline inventory on the isolated VPS found **21 BTCUSDT ZIP/manifest pairs**
and **1,059 missing cells**; those 21 were labeled
`PRESENT_UNVERIFIED` because this inventory did not re-hash/parse them.

`app.research.v5_archive_worklist` makes a strictly offline and
**read-only** prioritized acquisition plan. It **never downloads**, modifies
ZIPs, edits the ledger, queries Binance, opens PostgreSQL, or emits Telegram
messages. It emits a maximum of three **one-symbol / one-timeframe / up-to-six
months** jobs, each with commands for the already-tested bounded
`v5_archive_batch plan` and `v5_archive_batch fetch` tools. The fetch
command must be run separately by the operator, after checking the
published source, the expected disk/network budget and data eligibility.

## Which stages to acquire

| Stage | Source frames | Reason |
| --- | --- | --- |
| `foundation` (default) | 1h, 4h | Complete 500-bar trend warmup, V4 context and 4h source parity |
| `trigger` | 15m | Evaluate future completed 15m rescue triggers |
| `execution` | 1m | Execution-reference candles for later conservative fill research; not tick data |

Phases are `pilot` (Jan–Jun 2026; default),
`development` (March–May), `validation` (June–July),
`holdout` (August–September) and `full` (Jan–September).
**Historical indicator reconstruction requires January's fixed origin.**
Therefore development-only archive fetches without January warmup do
**not** authorize replay. `holdout` in this tool is **data-presence only**,
never performance evaluation; retain August–September trading outcomes
untouched until policy freeze.

All plan sizes, archive source identities and dates remain pinned to
`v5-history-v1.json`. The first new foundation suggestion after the
present 21-archive BTC pilot should ordinarily be an explicitly reviewed
ETHUSDT/1h January–June job, but the tool is the authority for the actual
queue, not this prose.

## 1. Read-only VPS plan — safe first invocation

Work from the already-used isolated VPS checkout. Do not run tools from
`/opt/mv-signal/app` or use `docker compose up`:

```bash
set -euo pipefail
WT=/tmp/mv-v5-history-pilot
BR=codex/mv-v5-historical-archive-pilot

test -z "$(git -C "$WT" status --porcelain)"
test "$(git -C "$WT" branch --show-current)" = "$BR"
git -C "$WT" fetch origin "$BR"
git -C "$WT" merge --ff-only FETCH_HEAD

IMG="$(docker inspect -f '{{.Image}}' mv-signal-api-1)"

docker run --rm --network none --read-only --pull never \
  --cap-drop ALL --security-opt no-new-privileges \
  --user 10001:10001 --cpus=0.5 --memory=768m \
  --tmpfs /tmp:rw,nosuid,nodev,size=64m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/strategy:/work/services/api \
  -v "$WT":/work:ro \
  -v /var/tmp/mv-v5-history-archives:/research:ro \
  -w /work/services/api "$IMG" \
  sh -eu -c '
    python -m pytest -q -p no:cacheprovider \
      tests/test_v5_archive_worklist.py \
      tests/test_v5_archive_inventory.py

    python -m app.research.v5_archive_worklist \
      --root /research --stage foundation --phase pilot \
      --max-jobs 2 --max-months-per-job 6
  '
```

The planner reports all inspected source-cell statuses; it emits
`proposed_jobs` containing `plan_command` and `fetch_command`.
`PRESENT_UNVERIFIED` means only pinned metadata passed inspection; a
separate full ZIP verification is still required before replay.
`REVIEW_REQUIRED` produces **no acquisition jobs** and exits 3.

Every `SOURCE_HTTP_404_REQUIRES_REVIEW` event from the existing
append-only batch ledger quarantines the still-missing archive in
subsequent planning. Never classify a 404 as 'prelisting' or silently
drop that market. Invalid sidecars, partial ZIP/manifest publication,
corrupt ledger entries and changing publisher checksums require
operator investigation and provenance-preserving resolution.

## 2. Operator-approved example — ONE small source batch

Only after reviewing the preceding plan, check the exact proposed
symbol/months and available disk. The command below is an
**illustrative ETHUSDT 1h January–June batch**, not authorization for
bulk acquisition or a claim that these archives exist:

```bash
# Plan first, no HTTP/no writes, with the code and archive mount read-only:
python -m app.research.v5_archive_batch plan \
  --root /research --symbol ETHUSDT --timeframe 1h \
  --start-month 2026-01 --end-month 2026-06
```

If separately approved and run in a **disposable research container with
outbound network access but no production environment secrets or Compose
network, and only /research mounted writable**, the corresponding
explicit source fetch is:

```bash
python -m app.research.v5_archive_batch fetch \
  --root /research --symbol ETHUSDT --timeframe 1h \
  --start-month 2026-01 --end-month 2026-06 \
  --max-new-mib 64 --min-free-mib 2048 --confirm-fetch
```

Those two example inner commands are **not** meant to be run in the VPS
host namespace with an undefined `/research` mount. Follow the
isolated Docker procedure in [V5 historical archives](V5_HISTORICAL_ARCHIVES.md).
No source downloads are started by the read-only planner.

## 3. Evidence required to advance

For each new symbol, acquire and separately verify source ZIPs and
manifest hashes, reconcile 1h/4h and 15m/1h exact OHLCV, and reconstruct
the same indicators from the fixed January source origin. Any
unavailable prelisting period must have independently reviewed
historical eligibility evidence before a replay may skip it.
The V4/V5 strategy candidate replay, exchange-specific price filters,
BTC-veto, position/dedupe/circuit state, slippage, fees, funding,
conservative 1m execution and untouched holdout evaluation remain
distinct later gates. Even **1,080 present ZIPs are not proof of
1,080 source-valid archives**.

Production V4 continues unchanged. This planner commits neither
execution logic nor a deployable V5 trading release.


## 10 October 2026 — ETHUSDT foundation operator pilot

The source-only, non-production entry point
`tools/v5-eth-foundation-pilot.sh` uses one fixed symbol (**ETHUSDT**),
the independent `1h` and `4h` frames, and only January–June 2026.
Run **plan** first (default):

```bash
cd /tmp/mv-v5-history-pilot
test -z "$(git status --porcelain)" || exit 2
test "$(git branch --show-current)" = "codex/mv-v5-historical-archive-pilot" || exit 2
git fetch origin codex/mv-v5-historical-archive-pilot
git merge --ff-only FETCH_HEAD
bash tools/v5-eth-foundation-pilot.sh plan
```

`plan` and `verify` use `--network none`, and mount code and
research archives read-only. The source fetch only runs if the operator
explicitly invokes the distinct mode:

```bash
bash tools/v5-eth-foundation-pilot.sh fetch --confirm-fetch
```

That action **does access the internet and write the research archive
volume**, but only in a disposable Docker container: existing API
image pinned by digest, no Compose or DB credentials, read-only code,
no elevated capabilities, 0.5 CPU / 768 MiB RAM, strictly bounded
64 MiB new ZIPs per frame invocation, publisher SHA-256 checks,
2 GiB free-space reserve, immutable manifests and append-only audit
ledgers. It runs 1h then 4h batches separately and attempts immediate
offline verification plus native 1h→4h cross-source reconciliation.
Publisher 404, checksum correction, data gap, or free-space failure
**stops**; the tool does not invent inception history or retry
indefinitely. Fetch is not a dry run. The initial source-only
`plan` is the default for safe inspection.

If the source fetch was previously completed, repeat the fully
offline check without downloading:

```bash
bash tools/v5-eth-foundation-pilot.sh verify
```

No ETH candidate counts, V4/V5 replay, intraday signals, fills or
profitability are claimed at this stage. This shell pilot and its
focused safety tests are authored in PR #12 but must be run on the
operator VPS before reporting a PASS.
