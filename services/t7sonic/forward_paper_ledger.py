"""V7Sonic paper-only SQLite decision ledger; no production schema or Telegram.

An isolated operator-owned private SQLite database preserves all SIX
decision outcomes and complete batch fingerprints, with crash-safe,
transactional idempotence. This is NOT a dispatch queue: no sends,
orders, user messages, network operations, or worker daemon exist.

Opening a ledger is an explicit opt-in local write (disabled by default).
Never use the MV production database or any path outside a private
standalone paper-test directory.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sqlite3
from stat import S_ISDIR
from typing import Any

from app.research.t7sonic_release_candidate import POLICY
from app.research.t7sonic_release_preview import DRY_RUN_STATUS
from app.research.t7sonic_validation_plan import MARKETS

_ALLOWED_STATUSES = frozenset({
    DRY_RUN_STATUS,
    "24_RAW_RESPONSE_OFFLINE_PAPER_PLANS_UNATTESTED",
    "OFFLINE_24_CANDLE_SOURCES_PLUS_6_BOOK_QUOTES_UNATTESTED",
    "INTERNAL_ONLY_PUBLIC_REST_CYCLE_UNATTESTED",
})
_PAPER = "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FILENAME = re.compile(r"v7sonic-paper-[A-Za-z0-9_-]{1,60}\.sqlite3\Z")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_cycles (
    decision_boundary_ms INTEGER PRIMARY KEY,
    batch_sha256 TEXT NOT NULL UNIQUE,
    body_json TEXT NOT NULL,
    inserted_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_decisions (
    decision_boundary_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    status TEXT NOT NULL,
    body_json TEXT NOT NULL,
    candidate_id TEXT UNIQUE,
    expires_at_ms INTEGER,
    lifecycle TEXT NOT NULL,
    PRIMARY KEY (decision_boundary_ms, symbol),
    FOREIGN KEY (decision_boundary_ms) REFERENCES paper_cycles(decision_boundary_ms)
);
"""


def _canonical(obj: Any) -> str:
    return json.dumps(
        obj, separators=(",", ":"), sort_keys=True, allow_nan=False
    )


def _sha(obj: Any) -> str:
    return sha256(_canonical(obj).encode("utf-8")).hexdigest()


def validate_internal_batch(batch: dict) -> dict:
    """Reject false publication, tampered IDs, missing decisions or altered R."""
    if not isinstance(batch, dict) or batch.get("status") not in _ALLOWED_STATUSES:
        raise ValueError("Only unreleased paper batches can be stored")
    for flag in (
        "telegram_enqueued", "client_publication_authorized",
        "real_money_orders_authorized",
    ):
        if batch.get(flag) is not False:
            raise ValueError("Live publication or trading is not authorized")
    boundary = batch.get("decision_boundary_ms")
    if (type(boundary) is not int or boundary <= 0 or boundary % 300_000
            or batch.get("policy") != POLICY or
            batch.get("markets_evaluated") != len(MARKETS) or
            batch.get("markets_expected") != len(MARKETS)):
        raise ValueError("Invalid six-market decision boundary")
    records = batch.get("decision_records")
    if (not isinstance(records, list) or len(records) != len(MARKETS) or
            [r.get("symbol") for r in records if isinstance(r,dict)] !=
            list(MARKETS)):
        raise ValueError("All six ordered decision records are mandatory")
    proposals = batch.get("indicative_candidates")
    absent = batch.get("no_candidate")
    if (not isinstance(proposals, list) or not isinstance(absent, list)
            or batch.get("candidate_count") != len(proposals)):
        raise ValueError("Invalid proposed/abstained counts")
    expected_candidates = []
    expected_absent = []
    for rec in records:
        if (not isinstance(rec, dict) or
                rec.get("schema") != 1 or rec.get("policy") != POLICY or
                rec.get("decision_boundary_ms") != boundary or
                rec.get("publishable_signal") is not False or
                rec.get("executable_order") is not False or
                not isinstance(rec.get("source_sha256"), str) or
                not _DIGEST.fullmatch(rec["source_sha256"])):
            raise ValueError("Invalid/unsealed market decision")
        if rec.get("status") == "NO_CANDIDATE":
            if not isinstance(rec.get("reason"), str) or not rec["reason"]:
                raise ValueError("Explicit no-setup reason required")
            expected_absent.append({
                "symbol": rec["symbol"], "reason": rec["reason"]
            })
        elif rec.get("status") == _PAPER:
            candidate_hash = rec.get("candidate_sha256")
            candidate_id = rec.get("candidate_id")
            if (not isinstance(candidate_hash,str) or
                    not _DIGEST.fullmatch(candidate_hash) or
                    not isinstance(candidate_id,str) or
                    not _DIGEST.fullmatch(candidate_id) or
                    _sha({k:v for k,v in rec.items()
                          if k != "candidate_sha256"}) != candidate_hash or
                    type(rec.get("expires_at_ms")) is not int or
                    rec["expires_at_ms"] <= boundary):
                raise ValueError("Tampered or improperly expiring plan")
            expected_candidates.append(rec)
        else:
            raise ValueError("Unknown market decision state")
    if absent != expected_absent or len(proposals) != len(expected_candidates):
        raise ValueError("No-candidate/candidate reconciliation mismatch")
    for proposal, rec in zip(proposals, expected_candidates):
        if (not isinstance(proposal,dict) or
                proposal.get("delivery_status") not in (
                    "PREVIEW_ONLY_NEVER_QUEUED",
                    "SUPPRESSED_DUPLICATE_IN_OFFLINE_PREVIEW",
                ) or
                {k:v for k,v in proposal.items() if k != "delivery_status"} != rec):
            raise ValueError("Proposed paper candidate differs from sealed decision")
    identity = {
        "policy": POLICY,
        "decision_boundary_ms": boundary,
        "decision_records": records,
        "candidate_ids": [x["candidate_id"] for x in proposals],
    }
    if batch.get("batch_sha256") != _sha(identity):
        raise ValueError("Batch SHA mismatches complete six-market decision")
    return {
        "boundary": boundary, "digest": batch["batch_sha256"],
        "records": records, "candidate_count": len(expected_candidates),
    }


class PrivatePaperLedger:
    """Explicit opt-in paper-only ledger in a preexisting private directory.

    No DB path is inferred from production config; a caller must supply
    a new basename v7sonic-paper-*.sqlite3 inside an owner-only directory.
    """

    def __init__(self, path: str | Path, *, local_write_approved: bool = False):
        if local_write_approved is not True:
            raise PermissionError("Local paper ledger writes OFF by default")
        target = Path(path)
        if (not target.is_absolute() or
                not _FILENAME.fullmatch(target.name) or
                target.is_symlink() or not target.parent.is_dir() or
                target.parent.is_symlink()):
            raise ValueError("Require an explicit private standalone paper SQLite path")
        parent = target.parent
        stat = parent.stat()
        if (not S_ISDIR(stat.st_mode) or stat.st_uid != os.getuid() or
                (stat.st_mode & 0o077)):
            raise PermissionError("Paper journal parent must be owned and mode 0700")
        if target.exists():
            old = target.stat()
            if old.st_uid != os.getuid() or old.st_mode & 0o077:
                raise PermissionError("Existing paper journal must be owner-private")
            if not target.is_file():
                raise ValueError("Paper ledger must be regular file")
        else:
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            os.close(descriptor)
        self.path = target
        self.db = sqlite3.connect(
            str(target), isolation_level=None, timeout=8.0
        )
        self.db.execute("PRAGMA busy_timeout=8000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(_SCHEMA)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def record(self, batch: dict, *, observed_at_ms: int) -> dict:
        """Transactionally persist ALL decisions or none, no network/outbox."""
        verified = validate_internal_batch(batch)
        boundary, digest = verified["boundary"], verified["digest"]
        if (type(observed_at_ms) is not int or
                observed_at_ms < boundary or
                observed_at_ms > boundary + 60_000):
            raise ValueError("Untrusted claimed receipt outside paper window")
        body = _canonical(batch)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            exists = self.db.execute(
                "SELECT batch_sha256,body_json FROM paper_cycles "
                "WHERE decision_boundary_ms=?", (boundary,)
            ).fetchone()
            if exists is not None:
                if exists != (digest, body):
                    raise ValueError("Conflicting or tampered repeat decision cycle")
                result = "EXACT_REPLAY_NO_MUTATION"
            else:
                self.db.execute(
                    "INSERT INTO paper_cycles VALUES (?,?,?,?)",
                    (boundary,digest,body,observed_at_ms)
                )
                for rec in verified["records"]:
                    is_plan = rec["status"] == _PAPER
                    self.db.execute(
                        "INSERT INTO paper_decisions VALUES (?,?,?,?,?,?,?)",
                        (boundary,rec["symbol"],rec["status"],_canonical(rec),
                         rec["candidate_id"] if is_plan else None,
                         rec["expires_at_ms"] if is_plan else None,
                         "INTERNAL_PAPER_ONLY" if is_plan else "NO_SETUP"),
                    )
                result = "SIX_MARKET_CYCLE_STORED"
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return {
            "status": result,
            "batch_sha256": digest,
            "six_decisions_accounted_for": 6,
            "candidate_count": verified["candidate_count"],
            "durable_sqlite_writes_completed": True,
            "off_vps_storage_verified": False,
            "independent_timestamp_verified": False,
            "live_orders_authorized": False,
            "telegram_or_client_delivery": False,
        }

    def expire(self, *, now_ms: int) -> int:
        """Only mark internal paper candidates expired; never send or retry."""
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Explicit evaluation clock required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur = self.db.execute(
                "UPDATE paper_decisions SET lifecycle='EXPIRED_UNSENT' "
                "WHERE lifecycle='INTERNAL_PAPER_ONLY' "
                "AND expires_at_ms <= ?", (now_ms,),
            )
            self.db.execute("COMMIT")
            return cur.rowcount
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def audit(self, boundary_ms: int) -> dict:
        """Read/verify stored journal. Never reinterpret missing data as no setup."""
        if type(boundary_ms) is not int:
            raise ValueError("Boundary must be exact integer")
        row = self.db.execute(
            "SELECT body_json FROM paper_cycles WHERE decision_boundary_ms=?",
            (boundary_ms,),
        ).fetchone()
        if row is None:
            raise ValueError("Missing decision batch (GAP, not NO_SETUP)")
        batch = json.loads(row[0])
        proof = validate_internal_batch(batch)
        persisted = self.db.execute(
            "SELECT symbol,status,body_json,candidate_id,lifecycle "
            "FROM paper_decisions WHERE decision_boundary_ms=? ORDER BY symbol",
            (boundary_ms,),
        ).fetchall()
        if (len(persisted) != 6 or
                set(row[0] for row in persisted) != set(MARKETS)):
            raise ValueError("Incomplete persisted six-market batch")
        by_symbol = {rec["symbol"]: rec for rec in proof["records"]}
        for symbol, status, body_json, candidate_id, lifecycle in persisted:
            rec = by_symbol[symbol]
            if (status != rec["status"] or body_json != _canonical(rec) or
                    candidate_id != rec.get("candidate_id") or
                    lifecycle not in (
                        ("INTERNAL_PAPER_ONLY","EXPIRED_UNSENT")
                        if status == _PAPER else ("NO_SETUP",))):
                raise ValueError("Persisted decision differs from sealed source")
        return {
            "status": "AUDITED_PRIVATE_PAPER_LEDGER_NOT_CLIENT_READY",
            "six_decisions_verified": True,
            "batch_sha256": proof["digest"],
            "candidate_count": proof["candidate_count"],
            "published_messages": 0,
            "paper_only": True,
            "actual_exchange_source_authenticated": False,
            "client_publication_authorized": False,
        }
