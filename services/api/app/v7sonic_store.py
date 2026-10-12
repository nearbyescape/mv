"""V7Sonic additive SQL journal + V7-specific NONSEND delivery drafts.

This module deliberately never mutates V4 SignalDecision, SignalPlan,
SignalSlot, SignalEvent or TelegramDelivery records. Only the separate V7
tables are used. Every complete six-market cycle, including abstentions,
is stored as one database transaction by the caller.

Client publication is NOT implemented. These are durable INTERNAL rehearsal
drafts, not active outbox messages; there is no send/claim method.
"""
from __future__ import annotations

from hashlib import sha256
import json

from sqlalchemy import select

from app.models import (
    V7DecisionCycle, V7DecisionRecord, V7DeliveryDraft,
)
from app.v7sonic_release import (
    STRATEGY_ID, format_private_rehearsal,
)
from services.t7sonic.forward_paper_ledger import validate_internal_batch
from app.research.t7sonic_validation_plan import MARKETS


def _sha(obj: bytes) -> str:
    return sha256(obj).hexdigest()


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hex(value) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and
        all(char in "0123456789abcdef" for char in value)
    )


def _decision_identity(boundary: int, symbol: str) -> str:
    return _sha(f"{STRATEGY_ID}|{boundary}|{symbol}".encode())


def store_private_cycle(
    session, *,
    report: dict,
    original_http_sha256: str,
    recorded_at_ms: int,
) -> dict:
    """Store full reconciled paper batch inside caller's transaction.

    The caller is responsible for a DB transaction with locking/fencing.
    This function makes NO commitment; a caller crash rolls all three tables
    back together. Replays must match byte-for-byte canonical decisions.
    """
    if (not isinstance(report, dict) or
            report.get("client_publication_authorized") is not False or
            report.get("telegram_enqueued") is not False or
            report.get("orders_authorized") is not False or
            report.get("persisted_outbox_implemented") is not False or
            report.get("live_worker_integrated") is not False or
            not _hex(original_http_sha256)):
        raise ValueError("Only explicitly disabled V7 private cycles can persist")

    batch = report.get("sealed_internal_paper_batch")
    proof = validate_internal_batch(batch)
    boundary = proof["boundary"]
    digest = proof["digest"]

    if (report.get("strategy_id") != STRATEGY_ID or
            report.get("decision_boundary_ms") != boundary or
            report.get("source_batch_sha256") != digest or
            report.get("markets_evaluated") != len(MARKETS) or
            report.get("candidate_count") != proof["candidate_count"] or
            report.get("original_http_responses_verified") != 31 or
            type(recorded_at_ms) is not int or
            not boundary <= recorded_at_ms <= boundary + 30_000):
        raise ValueError("Missing audited original source or invalid release timestamp")

    proposed = {
        c["candidate_id"]: c for c in batch["indicative_candidates"]
    }
    drafts = report.get("new_rehearsals")
    if not isinstance(drafts, list):
        raise ValueError("Missing V7 private release rehearsals")
    expected = {
        ident: {
            "candidate_id": ident, "symbol": c["symbol"],
            "direction": c["direction"], "expert": c["expert"],
            "expires_at_ms": c["expires_at_ms"],
            "rehearsal_text": format_private_rehearsal(c),
        }
        for ident, c in proposed.items()
        if c["delivery_status"] == "PREVIEW_ONLY_NEVER_QUEUED"
    }
    if (len(drafts) != len(expected) or
            any(not isinstance(d, dict) or set(d) != set(expected[d.get("candidate_id")])
                or d != expected[d["candidate_id"]]
                for d in drafts if isinstance(d, dict)) or
            any(not isinstance(d, dict) for d in drafts)):
        raise ValueError("Private V7 release drafts do not match sealed six-market batch")

    exists = session.get(V7DecisionCycle, boundary)
    if exists is not None:
        if (exists.strategy != STRATEGY_ID or
                exists.batch_sha256 != digest or
                exists.original_http_sha256 != original_http_sha256 or
                _canonical(exists.batch_json) != _canonical(batch)):
            raise ValueError("Conflicting immutable V7 decision cycle")
        return {
            "status": "EXACT_V7_CYCLE_REPLAY_UNMODIFIED",
            "six_market_records": 6,
            "private_drafts": len(expected),
            "client_publication_authorized": False,
            "telegram_messages_sent": 0,
        }

    session.add(V7DecisionCycle(
        boundary_ms=boundary, strategy=STRATEGY_ID,
        batch_sha256=digest, original_http_sha256=original_http_sha256,
        receipt_recorded_at_ms=recorded_at_ms,
        state="PRIVATE_PAPER_ONLY_NEVER_SEND", batch_json=batch,
    ))
    for decision in proof["records"]:
        candidate = decision.get("candidate_id")
        session.add(V7DecisionRecord(
            id=_decision_identity(boundary, decision["symbol"]),
            boundary_ms=boundary, symbol=decision["symbol"],
            outcome=decision["status"],
            candidate_id=candidate,
            expires_at_ms=decision.get("expires_at_ms"),
            source_sha256=decision["source_sha256"],
            decision_json=decision,
        ))
    for draft in drafts:
        body = draft["rehearsal_text"]
        session.add(V7DeliveryDraft(
            candidate_id=draft["candidate_id"],
            boundary_ms=boundary, symbol=draft["symbol"],
            destination_type="INTERNAL_PRIVATE_ONLY",
            state="BLOCKED_NOT_FOR_CLIENTS",
            text_sha256=_sha(body.encode("utf-8")),
            text=body,
            created_at_ms=recorded_at_ms,
        ))
    session.flush()
    return {
        "status": "V7_PRIVATE_SQL_BATCH_STORED_UNPUBLISHED",
        "six_market_records": 6,
        "private_drafts": len(drafts),
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
    }


def inspect_private_cycle(session, boundary: int) -> dict:
    """Independently re-validate persisted six-market decisions and drafts."""
    if type(boundary) is not int or boundary <= 0:
        raise ValueError("Positive exact boundary required")
    cycle = session.get(V7DecisionCycle, boundary)
    if cycle is None or cycle.state != "PRIVATE_PAPER_ONLY_NEVER_SEND":
        raise ValueError("Missing or unapproved V7 paper cycle")
    proof = validate_internal_batch(cycle.batch_json)
    if (proof["boundary"] != boundary or
            proof["digest"] != cycle.batch_sha256 or
            not _hex(cycle.original_http_sha256)):
        raise ValueError("Persisted V7 cycle hash mismatch")
    rows = list(session.scalars(select(V7DecisionRecord).where(
        V7DecisionRecord.boundary_ms == boundary
    )))
    if len(rows) != 6 or set(r.symbol for r in rows) != set(MARKETS):
        raise ValueError("Incomplete stored six-market cycle")
    by_symbol = {r["symbol"]: r for r in proof["records"]}
    for row in rows:
        original = by_symbol[row.symbol]
        if (row.id != _decision_identity(boundary, row.symbol) or
                row.outcome != original["status"] or
                row.candidate_id != original.get("candidate_id") or
                row.expires_at_ms != original.get("expires_at_ms") or
                row.source_sha256 != original["source_sha256"] or
                _canonical(row.decision_json) != _canonical(original)):
            raise ValueError("Persisted V7 decision modified")
    drafts = list(session.scalars(select(V7DeliveryDraft).where(
        V7DeliveryDraft.boundary_ms == boundary
    )))
    expected = {
        c["candidate_id"]: c for c in cycle.batch_json["indicative_candidates"]
        if c["delivery_status"] == "PREVIEW_ONLY_NEVER_QUEUED"
    }
    if len(drafts) != len(expected):
        raise ValueError("Missing or extra private V7 drafts")
    for draft in drafts:
        cand = expected.get(draft.candidate_id)
        if (cand is None or draft.symbol != cand["symbol"] or
                draft.destination_type != "INTERNAL_PRIVATE_ONLY" or
                draft.state != "BLOCKED_NOT_FOR_CLIENTS" or
                draft.text != format_private_rehearsal(cand) or
                draft.text_sha256 != _sha(draft.text.encode("utf-8"))):
            raise ValueError("Altered private V7 draft")
    return {
        "status": "V7_PRIVATE_SQL_AUDIT_OK_NO_SEND",
        "market_records": 6,
        "drafts_blocked": len(drafts),
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
    }
