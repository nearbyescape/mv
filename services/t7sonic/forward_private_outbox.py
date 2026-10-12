"""V7Sonic durable INTERNAL Telegram-style dry-run outbox, NO SEND capability.

No HTTP, bot token, Telegram client library, scheduler, account credentials,
production tables or user publication. This lives ONLY inside the separate
PrivatePaperLedger sqlite database, with explicit opt-in, and uses mock
acknowledgments. Never claim mocked sends reached Telegram.

A claimed/ambiguous send is left permanently blocked from automatic retries.
A confirmed fake ack is only "SIMULATED_ACK_NOT_SENT".
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
import sqlite3

from app.research.t7sonic_release_preview import format_explicit_test_message
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_paper_ledger import (
    PrivatePaperLedger, _PAPER, _canonical, validate_internal_batch,
)

OUTBOX_SCHEMA = """
CREATE TABLE IF NOT EXISTS private_test_outbox (
    candidate_id TEXT PRIMARY KEY,
    decision_boundary_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    text TEXT NOT NULL,
    recipient_fingerprint TEXT NOT NULL,
    expires_at_ms INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN ('PREPARED_SIMULATION_ONLY',
                  'SIMULATED_ATTEMPT_RESERVED',
                  'SIMULATED_ACK_NOT_SENT',
                  'AMBIGUOUS_BLOCKED_NO_RETRY',
                  'EXPIRED_UNSENT')
    ),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    transition_ms INTEGER NOT NULL,
    fake_message_id TEXT,
    FOREIGN KEY (decision_boundary_ms, symbol)
        REFERENCES paper_decisions(decision_boundary_ms, symbol)
);
CREATE INDEX IF NOT EXISTS idx_private_outbox_expiry
ON private_test_outbox(state,expires_at_ms);
"""
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_CHAT_ID = re.compile(r"-?[1-9][0-9]{0,15}\Z")
_STATES = ("PREPARED_SIMULATION_ONLY",)


def _chat_fingerprint(test_chat: str, production_chat: str) -> str:
    if (not isinstance(test_chat,str) or not isinstance(production_chat,str)
            or not _CHAT_ID.fullmatch(test_chat)
            or not _CHAT_ID.fullmatch(production_chat)
            or test_chat == production_chat):
        raise PermissionError(
            "Explicit, distinct private-test and production chat IDs required"
        )
    return sha256(test_chat.encode("ascii")).hexdigest()


class PaperTestOutbox:
    """Only for a separately opened/approved PrivatePaperLedger."""

    def __init__(self, ledger: PrivatePaperLedger, *,
                 private_test_chat_id: str, production_chat_id: str):
        if not isinstance(ledger,PrivatePaperLedger) or not hasattr(ledger,"db"):
            raise TypeError("PrivatePaperLedger instance required")
        self.db = ledger.db
        self.test_fingerprint = _chat_fingerprint(
            private_test_chat_id, production_chat_id
        )
        self.db.executescript(OUTBOX_SCHEMA)

    def prepare(self, batch: dict, *, now_ms: int) -> dict:
        proof = validate_internal_batch(batch)
        boundary=proof["boundary"]
        if (type(now_ms) is not int or
                now_ms < boundary or now_ms > boundary + 30_000):
            raise ValueError("Cannot prepare stale or future paper batch")
        verified = self.db.execute(
            "SELECT batch_sha256,body_json FROM paper_cycles "
            "WHERE decision_boundary_ms=?", (boundary,)
        ).fetchone()
        if verified != (proof["digest"],_canonical(batch)):
            raise ValueError("Exact complete batch must already be persisted")
        actionable = {
            x["candidate_id"]: x for x in batch["indicative_candidates"]
            if x["delivery_status"] == "PREVIEW_ONLY_NEVER_QUEUED"
        }
        # A conflict or expired plan must fail the whole transaction.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            queued=0
            for decision in proof["records"]:
                if decision["status"] != _PAPER:
                    continue
                candidate_id=decision["candidate_id"]
                if candidate_id not in actionable:
                    continue
                expiration=decision["expires_at_ms"]
                if now_ms >= expiration:
                    raise ValueError("Paper candidate already expired")
                lifecycle=self.db.execute(
                    "SELECT lifecycle FROM paper_decisions WHERE "
                    "decision_boundary_ms=? AND symbol=?",
                    (boundary,decision["symbol"]),
                ).fetchone()
                if lifecycle != ("INTERNAL_PAPER_ONLY",):
                    raise ValueError("Only unexpired internal candidates")
                text=format_explicit_test_message(actionable[candidate_id])
                if ("DO NOT TRADE" not in text or
                        "Not authorized for client publication" not in text):
                    raise ValueError("Internal-only warning is mandatory")
                before=self.db.execute(
                    "SELECT decision_boundary_ms,symbol,text,"
                    "recipient_fingerprint,expires_at_ms FROM private_test_outbox "
                    "WHERE candidate_id=?", (candidate_id,)
                ).fetchone()
                expected=(boundary,decision["symbol"],text,
                          self.test_fingerprint,expiration)
                if before:
                    if before != expected:
                        raise ValueError("Duplicate candidate collides with previous destination")
                    continue
                self.db.execute(
                    "INSERT INTO private_test_outbox "
                    "(candidate_id,decision_boundary_ms,symbol,text,"
                    "recipient_fingerprint,expires_at_ms,state,attempt_count,"
                    "transition_ms,fake_message_id) "
                    "VALUES(?,?,?,?,?,?,'PREPARED_SIMULATION_ONLY',0,?,NULL)",
                    (candidate_id,*expected,now_ms),
                )
                queued+=1
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return {
            "status": "INTERNAL_TEST_OUTBOX_PREPARED_NOT_SENT",
            "newly_prepared": queued,
            "private_test_chat_hash_only": self.test_fingerprint,
            "real_telegram_request_implemented": False,
            "telegram_messages_sent": 0,
            "client_publication_authorized": False,
        }

    def claim_simulated_attempt(self, candidate_id: str, *,
                                now_ms: int) -> dict:
        """Reserve ONCE before an imagined send; no actual network callback."""
        if (not isinstance(candidate_id,str) or
                not _SHA64.fullmatch(candidate_id) or type(now_ms) is not int):
            raise ValueError("Malformed attempt identity/time")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute(
                "SELECT text,expires_at_ms,state,recipient_fingerprint "
                "FROM private_test_outbox WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if row is None or row[2] not in _STATES or row[3] != self.test_fingerprint:
                raise PermissionError("Candidate not prepared or already attempted")
            if now_ms >= row[1]:
                self.db.execute(
                    "UPDATE private_test_outbox SET state='EXPIRED_UNSENT',"
                    "transition_ms=? WHERE candidate_id=?",
                    (now_ms,candidate_id),
                )
                self.db.execute("COMMIT")
                raise ValueError("Candidate expired without a simulated send")
            self.db.execute(
                "UPDATE private_test_outbox SET state='SIMULATED_ATTEMPT_RESERVED',"
                "attempt_count=1,transition_ms=? WHERE candidate_id=?",
                (now_ms,candidate_id),
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise
        return {
            "status": "SIMULATED_ATTEMPT_RESERVED_NO_NETWORK",
            "candidate_id": candidate_id,
            "text": row[0],
            "actual_recipient_id_exposed": False,
            "actual_telegram_sender_available": False,
            "messages_sent": 0,
        }

    def mark_simulated_ack(self,candidate_id: str, *,
                           now_ms: int, simulated_message_id: str) -> dict:
        if (not isinstance(candidate_id,str) or
                not _SHA64.fullmatch(candidate_id) or
                type(now_ms) is not int or now_ms < 0 or
                not isinstance(simulated_message_id,str) or
                not re.fullmatch(r"FAKE-[A-Za-z0-9_-]{1,80}",simulated_message_id)):
            raise ValueError("Only explicit fake acknowledgment accepted")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute(
                "SELECT state,transition_ms,recipient_fingerprint FROM "
                "private_test_outbox WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
            if (row is None or row[0] != "SIMULATED_ATTEMPT_RESERVED" or
                    row[2] != self.test_fingerprint or now_ms < row[1]):
                raise PermissionError("Cannot confirm unreserved simulated attempt")
            self.db.execute(
                "UPDATE private_test_outbox SET state='SIMULATED_ACK_NOT_SENT',"
                "transition_ms=?,fake_message_id=? WHERE candidate_id=?",
                (now_ms,simulated_message_id,candidate_id),
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return {
            "status":"SIMULATED_ACK_NOT_SENT",
            "telegram_messages_sent":0,
            "client_publication_authorized":False,
        }

    def block_ambiguous(self, candidate_id: str, *, now_ms: int) -> None:
        if not isinstance(candidate_id,str) or not _SHA64.fullmatch(candidate_id) or (
            type(now_ms) is not int or now_ms < 0
        ):
            raise ValueError("Invalid ambiguity marker")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row=self.db.execute(
                "SELECT state,transition_ms FROM private_test_outbox "
                "WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
            if not row or row[0] != "SIMULATED_ATTEMPT_RESERVED" or now_ms < row[1]:
                raise PermissionError("Only attempted messages can be marked ambiguous")
            self.db.execute(
                "UPDATE private_test_outbox SET state='AMBIGUOUS_BLOCKED_NO_RETRY',"
                "transition_ms=? WHERE candidate_id=?", (now_ms,candidate_id)
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def fail_closed_after_restart(self, *, now_ms: int) -> int:
        """Any orphaned attempt -> ambiguous, NEVER automatic retry."""
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Bad restart clock")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            cur=self.db.execute(
                "UPDATE private_test_outbox SET state='AMBIGUOUS_BLOCKED_NO_RETRY',"
                "transition_ms=? WHERE state='SIMULATED_ATTEMPT_RESERVED' "
                "AND transition_ms<=?",
                (now_ms,now_ms),
            )
            self.db.execute("COMMIT")
            return cur.rowcount
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def counts(self) -> dict:
        rows=self.db.execute(
            "SELECT state,COUNT(*) FROM private_test_outbox GROUP BY state"
        ).fetchall()
        return {
            "by_state":dict(rows),
            "real_telegram_messages_sent":0,
            "production_client_messages_sent":0,
            "simulated_store_only":True,
        }
