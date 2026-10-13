# V7Sonic release integration — guarded engineering boundary

**Status: DRAFT / NOT DEPLOYED / NO CLIENT PUBLICATION AUTHORIZED.**

This branch adds five-minute public source capture, immutable original 31-body receipts,
six-market V7 research decision replay, isolated paper SQLite persistence,
versioned PostgreSQL tables and a *separately sealed* Telegram outbox.
An application or CI pass alone is not proof of profitable signals.

## Immutable separation

- Production release is still `mv-signal-0.14.0`. Do not restart its V4
  `app.signals.worker` or V4 `app.telegram.worker` in lieu of V7.
- `v7_decision_cycles`, `v7_decision_records`, and
  `v7_delivery_drafts` store **blocked paper only**. They NEVER generate
  Telegram sends. Only a separately reviewed certification workflow can
  authorize the isolated `v7_client_approvals` and `v7_client_deliveries`
  lane. **That certification producer does not exist yet.** V7 client writes
  now require a real PostgreSQL singleton fence; unresolved V4 held/reserved
  slots in any market block new V7 release until reconciled.
- No production Compose service enables the private paper SQL worker or
  client sender. These are explicitly opt-in modules, not startup jobs.
- `v7_client_approvals` requires an independently signed, exact-source,
  exact-destination, risk-reviewed authorization tied to an already certified
  `V7_RELEASE_CERTIFIED` cycle. Paper cycles remain
  `PRIVATE_PAPER_ONLY_NEVER_SEND`. No automatic promotion is implemented.
- The existing V4 `signal_plans`, `signal_events`,
  `telegram_deliveries`, historical outcomes, and website data do not
  become V7 messages through the above migrations.

## Release prerequisites (all mandatory)

1. Approve and merge frozen research changes and the isolated V7 integration
   branch in order, after exact-SHA full CI + VPS test results. Never silently
   bring the retired V4 daemon back.
2. Take independently verified, off-VPS production database and release
   backups, retaining checksum manifests and a tested restore path.
3. Prove migrations `0009` and `0010` are additive in a clone of the
   production PostgreSQL database, including upgrade/downgrade/reupgrade
   and V4 application compatibility. On live production prefer forward
   correction over a blind schema downgrade.
4. Certify real market source completeness (all 31 HTTP bodies, native vs
   minute OHLCV, local receipt clock, 30-second freshness limit); reject
   any mismatch, late capture, off-session boundary or missing market.
5. Build an *actual* independently reviewed release authority:
   verify the source and venue rules, obtain fresh authoritative portfolio
   exposure and 0.5%-per-trade/2%-aggregate risk, four-slot limits, margin,
   funding and cost allowances, and record named operator approval with
   tamper-evident signing and exact target chat. The new signed operator
   risk packet is bound to a canonical hash and checked for 0.5% risk,
   2% aggregate risk, 2x gross notional, four slots, venue quantity/step,
   fee/slippage/funding buffer and 5-second freshness. It remains marked
   `OPERATOR_RECONCILED_UNATTESTED`, not real exchange authentication.
   **Independent account/venue certification is not implemented yet.**
6. Before publishing any clients: test signed authorization failure,
   stale or corrupted plans, cross-V4 and V7 active-slot conflicts,
   concurrent DB claims, interruption immediately before/after HTTP,
   Telegram provider 429/5xx/timeouts, ambiguous sends and
   destination verification in a private **non-client** test chat.
7. Complete read-only website/API V7 presentation, observability, alarms,
   retention and audit logging; establish operational decision-gap budget.
8. Prepare a versioned, side-by-side V7 release with explicit per-service
   enablement. Stop the V4 workers and any conflicting old Telegram worker
   first; execute preflight; only then do a reviewed controlled cutover.

## Separate no-send deployment rehearsal (safe to test before V7 is certified)

A dedicated `compose.v7sonic-isolated.yml` uses Compose project
`mv-v7sonic-isolated`, one `v7-preflight` container, `network_mode: none`,
a read-only filesystem, no ports, no secrets, no mounted production volumes,
no Docker socket, no database credentials, and `restart: no`.

From a clean, detached, exact-SHA V7 worktree on the VPS, while the original
`/opt/mv-signal/app` symlink still points to `mv-signal-0.14.0` and V4's
engine/Telegram/report/AI workers are stopped:

```bash
V7_EXPECTED_SHA=<the-reviewed-40-character-branch-head> \
  bash deploy/v7sonic-verify-isolated.sh
```

The script builds only a separately tagged local V7 image and executes the
offline preflight. A separate guard parses normalized Docker Compose JSON
and rejects merged V4/DB/Telegram services, accidental production project
names, mounted secrets, networks, root/privileged users, or restart policies.

**This is NOT a production dry run against live market data or PostgreSQL,**
nor does it constitute approval to apply database migrations `0009/0010`.
A clean preflight verifies packaging/Compose isolation only. To stop, no
persistent V7 worker has been started; keep production V4 workers stopped.
No client bot credentials should be placed in this isolated manifest.

## Optional one-boundary *real* Binance evidence rehearsal (NO SEND)

A separate `deploy/v7sonic-capture-one-live-boundary.sh` can capture
**one future five-minute boundary** during 09:00–23:00 IST, using only public
Binance Futures REST GETs (24 closed kline histories, six bookTicker quotes,
one exchangeInfo response). It requires **explicit**
`V7_PUBLIC_MARKET_CAPTURE_APPROVED=YES` and a pinned exact Git SHA.
It is not enabled by the preflight and does not start a continuous service.

The container runs as UID `10001` with a read-only image, no production
secrets, no Telegram credentials, no production DB/Compose mounts, and a
dedicated persistent `/var/tmp/v7sonic-live-receipts-<sha>` evidence directory.
It has outbound public-network access *only for the acquisition*, unlike
the fully offline Compose preflight. Code pins the Binance HTTPS URLs;
the container's bridge network is **not** a host-firewall egress allowlist.

```bash
V7_EXPECTED_SHA=<exact reviewed branch SHA> \
V7_PUBLIC_MARKET_CAPTURE_APPROVED=YES \
  bash deploy/v7sonic-capture-one-live-boundary.sh
```

Each completed eligible boundary preserves original HTTP bodies, hashes,
cross-resolution checks and a six-market private SQLite paper ledger. If a
request times out or no full batch arrives, the runner retains a dedicated
`v7sonic-private-acquisition-gap-*.json` rejection: a gap is NOT a
`NO_CANDIDATE` or a signal. A real valid cycle may still produce **zero**
candidates, which cannot be treated as trading-performance certification.
The script refuses off-session runs, non-pinned source trees or a resumed
V4 engine/Telegram service. No database migration, account access, trading
orders, or client message publication takes place.

## Completed one-shot source/ledger forensic review

For an already completed, quiescent one-boundary paper capture,
`python -m app.v7sonic_readonly_audit` validates the original receipt and
all 31 body hashes, six sealed market decisions, source-reconciliation
details and ledger row consistency. It must run in a non-root, no-network
container with the original UID10001 evidence folder mounted `:ro`.
The three full SHA256 values from the original capture are mandatory.

**SQLite WAL safeguard:** The one-shot writer normally closes and
checkpoints its WAL before the process exits. A normal SQLite `mode=ro`
connection may attempt to create a `-shm` file and fail on a strictly
read-only evidence mount. This historical auditor now uses
`mode=ro&immutable=1` **only if** both WAL and SHM sidecar paths are
absent. Immutable SQLite can ignore *uncheckpointed* WAL changes; therefore
an existing `-wal` or `-shm` is a **hard failure**, not an invitation to
remove those files or silently report stale results. Do not modify, remove,
checkpoint, chmod, or replace original evidence merely to pass an audit.

The forensic output describes **expired paper-only** candidate entries and
rejection reasons. It cannot authorize retroactive client messages, prove
executions, or establish a predictive edge.

## First real candidate outcomes — read-only reference path (not fills)

First real market-source capture at **13 Oct 2026 09:05 IST** yielded
two historical, expired LONG breakout ideas: SOLUSDT entry 107.69,
SL 106.80, TP1 108.58, TP2 109.92; DOGEUSDT entry 0.08443,
SL 0.08381, TP1 0.08505, TP2 0.08598. BTC, ETH, XRP and BNB
were rejected for `INSUFFICIENT_AFTER_COST_REWARD`. This is an
**n=2 paper-candidate observation**, not a profitable trading record.

The optional `deploy/v7sonic-compare-first-outcomes.sh` is disabled
unless `V7_HISTORICAL_PUBLIC_GET_APPROVED=YES` and the exact source
Git SHA is pinned. It operates **no earlier than 11:06 IST**,
when 120 entire 1m candles starting at **09:06** have closed. It
independently reaudits the original 31 Binance response bytes and all
six SQLite paper decisions, reads the original folder `:ro`, and makes
two public Binance Futures historical kline GETs for SOL and DOGE. It
preserves the exact new HTTP bodies and hashes in a *different* owner-only
evidence folder before calculating post-decision reference excursions.
There is no Telegram, account, production PostgreSQL, or order API.

The audit reports 15/30/60/120-full-minute closing prices and their
risk-normalized direction, maximum favorable/adverse one-minute OHLC
excursions, and first observed SL or TP1 reference touch. If a minute's
high touches TP1 and low touches SL, **event ordering is ambiguous**.
It explicitly does not estimate realized trade PnL or count winners:
the original conditional signal expired at 09:05:30 and the 09:05
partial candle is excluded to prevent mixing pre-decision prices
with the decision itself. Therefore **entry/fill status is unproven**;
an entry cannot be inferred from the later one-minute candles. The
outcome scoring is observational reference evidence only.

Do not convert these historical results into retrospective live
signals, certified strategy accuracy, or claims that TP orders filled.

## First historical outcome capture — operator VPS evidence, 13 Oct 2026

One-shot original-byte price-outcome study at commit
`dea04b406a580ddc40731dbf95c952afb5aa5de2` completed **PASS**,
with zero client messages or exchange orders and V4 engine remaining
stopped. Original decision capture: 09:05 IST, 6/6 markets, two paper
LONG breakout candidates. Historical reference source: **two** public
Binance Futures 1-minute kline responses, 120 fully closed one-minute
candles per market, starting 09:06 IST. Retained source packet SHA256:
`728f05349cf2a5bccbbee038e17133166082cf91290c5f045419f45fe211830c`.
Operator evidence folder:
`/var/tmp/v7sonic-outcome-evidence-dea04b406a58`.
This is a local un-attested observational series, not broker executions.

| Market | 15m close (R) | 30m close (R) | 60m close (R) | 120m close (R) | Max favorable | Max adverse | First TP1 reference touch | SL touch | TP2 touch |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| SOLUSDT | -0.382 | -0.034 | +0.528 | +0.461 | +1.225R | 0.640R | Post-decision full minute #108, 10:53 IST | No | No |
| DOGEUSDT | -0.258 | 0.000 | +0.419 | +0.194 | +1.113R | 0.452R | Post-decision full minute #108, 10:53 IST | No | No |

**Interpretation:** Both price series first touched their respective TP1
reference levels in the **same minute (#108, 10:53 IST)**, with no stop
reference touched and neither TP2 touched in the complete 120-minute
evaluation. Both had negative 15-minute price-relative performance
and their first TP1 touches came **~108 minutes after decision**.
This is evidence of eventual directional recovery/continuation in two
correlated assets, not two statistically independent wins.

The original **09:05:00–09:05:30** conditional entry window is not
observable in this study; 09:05 partial-candle prices were intentionally
excluded. Therefore entry touch, order acceptance, executable
bid/ask, fills, slippage, fees and realized net PnL **remain unproven**.
Do NOT label the two ideas as winning trades or conclude that V7 has a
positive forecasting edge from n=2 outcomes.

Next evidence gates: establish conditional-entry executability on
appropriately timestamped source data without lookahead, validate
market-wide correlated movement and near-term versus long-horizon
behavior over additional truly forward paper decisions, then certify
authoritative account/portfolio limits and private Telegram failure modes
before any client publication.

## Explicit first 30-second *trade-print* entry diagnostic — NO FILLS

To investigate whether the two historical paper entry prices were at
least **observed in the market's executed trade prints** during the
original `09:05:00–09:05:30 IST` expiry interval, the guarded
`deploy/v7sonic-entry-tape-30s.sh` collects **twelve** public Binance
USDT-M `GET /fapi/v1/aggTrades` responses — six disjoint 5-second
slices each for SOLUSDT and DOGEUSDT. Binance caps responses at
1,000 aggregate trades; any 5-second slice returning the full 1,000
records is rejected as **possibly truncated**. Historical aggregate
trade coverage is subject to the exchange's time-retention policy, so
the operator script refuses attempts more than 40h after the original
boundary. This is deliberately NOT part of the active V7 worker.

The collector requires clean exact-SHA source, an explicit
`V7_PUBLIC_ENTRY_TAPE_APPROVED=YES`, suspended V4 + Telegram
workers, the original audited 31-response/6-market source `:ro`,
nonroot UID10001, a separate private immutable evidence directory,
and no trading/API/Telegram secrets. Each HTTP response's raw bytes
and SHA256 are preserved **before** parsing. Bad timestamps, duplicate
IDs, malformed prices, incomplete/limited response slices, timeout, or
changed original journal source lead to an incomplete, **no conclusion**
record. This lane must not signal or create an order.

The causal lower bound is the original **private paper journal's local
`inserted_ms` timestamp**, rather than the 09:05:00 boundary: price
prints occurring before the original decision was at least persisted
cannot count as evidence for an actionable post-decision entry. That
clock is explicitly **not** independently exchange-attested or proof
of when a real client received a signal.

**Critical non-equivalence:** A public executed market trade at,
above or below the model entry does NOT prove an executable
limit/stop-market price, available bid/ask liquidity, order acceptance,
latency, fees/slippage, or that a nonexistent client order filled.
`aggTrades` are compressed executed market prints, not full-depth
historical order-book quotes. The result can only say whether market
prints occurred around the original reference entry after the paper
journal was written. It cannot turn either historical paper idea
into a realized winner or loss. < 2 independently observed price
references cannot establish statistical model accuracy.

## First real 30-second printed-price evidence — 13 Oct 2026

Operator one-shot paper-only entry-tape study **PASS** at
`1367afb0e8994d25ea02a6b1fc60af9d05d0c168`.
Original 09:05:00 IST V7 paper decision journal was inserted at
`1791862502385` = **09:05:02.385 IST** (local, not independently
exchange-attested). Twelve Binance Futures `aggTrades` JSON bodies
were retained under
`/var/tmp/v7sonic-entry-tape-1367afb0e899`, six disjoint 5-second
slices for each coin; reported status
`TWO_HISTORICAL_30S_TRADE_PRINT_CHECKS_NOT_ORDER_FILLS`.

| Historical observation within 09:05:02.385–09:05:29.999 IST | SOLUSDT | DOGEUSDT |
|---|---:|---:|
| Conditional entry price | 107.69 | 0.08443 |
| First executed market print **at/below** entry | 09:05:02.495 | 09:05:02.603 |
| First executed market print **at/above** entry | 09:05:03.831 | 09:05:03.971 |
| Minimum trade price in post-journal window | 107.65 | 0.08440 |
| Maximum trade price in post-journal window | 107.92 | 0.08465 |
| Aggregate trade prints in full 30 seconds | 446 | 218 |
| Aggregate trade prints after journal before expiry | 407 | 206 |

Both reference entry levels were observed on both sides shortly
**after** the model's local paper decision and before the 30-second
expiry. However, the first actual event times are exchange trade
timestamps and the local decision journal timestamp is NOT
independently clock-attested; execution ordering cannot be promoted
into a client-order claim. These executed trade prints are NOT historical
bid/ask depth or a verified opportunity to fill a specific type/size of
conditional order. Neither a client Telegram signal nor an exchange
order was ever placed. Recorded fills: **zero proven**; returns:
**no realized PnL verified**. Observed future TP1 touches occur at
10:53 IST, **not** necessarily any filled trade.

A separate `python -m app.v7sonic_entry_tape_audit` command is provided
to reproduce the 12 source-body SHA checks, six original source
decisions, journal time, request URLs/slice boundaries, decoded
trade-print order, and exact reported results under strictly
read-only, no-network UID10001 mounts. Missing/corrupted/incomplete
evidence must fail closed. Historical price observations still do not
establish statistical edge at n=2, particularly as both candidates
had highly correlated price development and simultaneous TP1 touches.

## First actual 30-second entry-tape independent re-audit — PASS

Operator replay on the VPS of immutable evidence from the first **13 Oct
2026, 09:05 IST** paper boundary succeeded:

`ORIGINAL_12_RESPONSE_30S_TAPE_REPLAY_AUDIT_PASS_NO_FILLS`

Exact audited code SHA
`4e54b320ff96e316eb9c4d0c20c4494b6ded6a6d`;
original paper source hash
`ecd05a021de07a853157b143d882ac472a42e85bfe72826c87c3cee5520caadb`;
sealed six-market batch hash
`0cc8e8c97aaee3caad24269c78918aa7d5c64571cd2ecb3318f42907f44d2e11`;
source paper journal insertion claim
`1791862502385` (unattested local clock). A new independent, **zero
network**, non-root auditor replayed all 12 saved Binance Futures
aggregate-trade response bytes against the SHA256 digests copied
out-of-band from the original operator transcript; checked precise
symbol/5s slice and request URLs, compared all decoded observations
with the saved report, and cross-checked the original 31-body source
and 6-record paper ledger. Final tape report SHA256:
`9a845b48c5c08e557866576cd49b22c37b30a123fc6331cf6fd7d526b1332c10`.

All saved evidence was mounted `:ro`; V4 was checked suspended,
no client publication was authorized and no orders were submitted.
**None of this proves executable orders or fills.** Original client
signals transmitted = zero, verified fills = zero, realized net
P&L = unverified. This is a technical integrity/reproducibility
milestone, NOT live production release certification.

## Next standalone operator-approved four-cycle forward pilot

A **separate bounded** operator script
`deploy/v7sonic-four-cycle-paper-pilot.sh` can evaluate exactly
four FUTURE five-minute boundaries in the approved 09:00–23:00 IST
market session, never retrospectively backfilling missed boundaries.
Run it only from a reviewed/clean/pinned V7 worktree with the explicit
`V7_FOUR_CYCLE_PUBLIC_PAPER_APPROVED=YES` environment approval.
It builds a distinct research Docker image and performs a NO NETWORK
preflight before using public market GETs. It runs in the foreground
with an upper runtime limit, UID10001, a read-only root, no mounted
secrets/production volumes, no Telegram client/outbox, and no exchange
account/order endpoints. It checks that V4 engine and ancillary
Telegram/AI workers remain stopped, with the engine restart policy
still `no`, including on error.

Each successful future five-minute boundary must have exactly:
31 original response bodies (24 native candles, 6 book quotes,
1 exchangeInfo), one create-only claim, six paper-market decisions
(including NO_CANDIDATE rows), its own independently retained
SHA256s and an auditable private SQLite journal. The pilot permits
**zero or more** actual candidate setups; a zero count is NOT failure
and cannot be interpreted as a trading win-rate denominator.
If any capture fails or crosses its freshness deadline, retain an
explicit GAP, stop the pilot, do not silently backfill or publish.

The pilot must run on a different owner-private evidence path from
the already-certified 09:05 historical evidence. It is an
**operational repeatability** test, not an independent strategy
edge evaluation: results across adjacent boundaries and correlated
assets are not independent trials, and outcome labels collected
after the fact must not be used as if they were precommitted
executions. Production publication still requires separate
source/account attestations, portfolio risk, sign-off, delivery
fault-injection tests, migrations and explicit cutover approval.

## 13 Oct 2026, 21:30 IST simultaneous-timeframe close incident

An operator-run, four-future-boundary paper-only pilot using exact SHA
`c607b59430a2c62a6d001fe0a95a450b3d3ef0b6` generated:
- 21:20 IST: six-market private paper journal PASS, 0 candidates;
- 21:25 IST: six-market private paper journal PASS, 0 candidates;
- 21:30 IST: attempt #1 preserved 31 exact original responses
  (`ba03a20331da53b4b1c95e529eeffa7b412f2497d7f9ff18a4f5940fcfee0cdc`)
  but cross-resolution OHLCV check rejected; attempt #2 suffered a
  Binance public HTTPS `TimeoutError: The read operation timed out`;
  the scheduler persisted a GAP, halted and did NOT generate a signal;
- 21:35 IST was never attempted. **Pilot FAILED, 2/4 completed.**

The **offline** replay of the original 21:30 attempt verified all
31 individual response hashes and reported **9 OHLC price discrepancies
and 13 volume discrepancies**. Every shown disagreement belongs to a
higher-timeframe bar that closed at exactly **16:00 UTC / 21:30 IST**:
15m opened 15:45 UTC; 1h opened 15:00 UTC; 4h opened 12:00 UTC.
For example, BTC 1h close 83393.00 native vs 83393.10 1m-derived;
ETH 1h close 2515.39 native vs 2515.38 1m-derived; SOL 15m volume
295449.47 native vs 295098.20 derived. Independent public REST
requests can be unsynchronized immediately after the close;
the saved evidence supports a **closing-boundary synchronization
hypothesis** but does not establish Binance's internal reason.
Do NOT relabel these data gaps as NO_CANDIDATE or weaken the
price/volume equality contract.

An isolated research-only change in `release_capture_worker.py`
adds a **2,500 ms post-close first-fetch settling window only at
15-minute boundaries**, which include every simultaneous hourly and
four-hourly close. Every source body must still pass exact 1m/
15m/1h/4h OHLCV reconciliation; the existing up-to-30s decision
expiry, bounded complete-retry rules, quote freshness and fail-closed
behavior remain unchanged. This is an empirically motivated mitigation,
**not** proof that future market-source inconsistencies or timeouts
will disappear. It must pass forward-paper repeatability checks before
any client publication.

The previous four-cycle wrapper ran as a *foreground SSH child*,
and Python stdout was pipe-buffered; loss of the SSH connection
destroyed stderr diagnostics and left a zero-byte console log.
The corrective `deploy/v7sonic-four-cycle-systemd-launch.sh`
launches a one-time **transient systemd unit**, bounded with explicit
no-restart and journal stdout/stderr, carrying operator approval only
into the isolated four-cycle script. Four fresh future boundaries are
evaluated in a **new** owner-private state folder for the pinned
commit, with the pre-existing 21:20/21:25 successes and 21:30 failure
preserved. The private scheduler also flushes each completed-cycle
checkpoint to stderr for durable journal progress. The unit is
not installed or started by CI or deployment; the operator must
separately opt in after reviewing the exact source. V4 stays stopped;
no client messages or exchange orders are authorized.

## Cutover / rollback safety

- Never use `docker compose up -d` without a fixed reviewed Compose file
  list: it can unintentionally restore stopped V4 worker restart policies.
- Before switching on a V7 publisher, verify: exact release SHA, correct
  signed authorization, correct Telegram destination, database migration,
  lease/fence ownership, no duplicate worker, complete historical/audit
  journal, and the official 09:00–23:00 IST source/publication session.
- A Telegram send claim MUST commit before the HTTPS POST. Inflight work
  after crash becomes UNKNOWN and is never blindly resent. Unknown deliveries
  halt later sends until explicit operator reconciliation.
- On failure **stop only V7 client publication** first, freeze the V7
  approval gate and leave the audit/outbox tables intact. Keep the
  working web/API/database online if healthy. Do not restart V4 as an
  automatic rollback, since that could resurrect the failed signal engine.
- Rollback of the application release pointer must be a separately reviewed
  manual action with verified release/archive SHA and environment snapshot.
  Production schema downgrade is not a routine rollback; preserve evidence.

## User-facing limitations

The engine calculates **conditional informational trade ideas** only. There
are no exchange orders, no verified fills, no authenticated live account
balances and no statistically demonstrated future profitability. Current
research candidates explicitly say nonpublishable and are **not** client
signals until all release-certification checks above have genuinely passed.
