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
