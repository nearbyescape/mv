"""V7Sonic signed-client-release outbox, independent of V4 and private paper.

THIS MODULE HAS NO AUTOMATIC RELEASE PRODUCER OR STARTUP ENTRYPOINT.
A journaled PAPER candidate cannot be sent merely by existing in SQL.
To stage a client message an independent reviewer must first:
  1) complete a separately verified V7 release-certification workflow,
  2) mark that decision cycle V7_RELEASE_CERTIFIED,
  3) create a separately HMAC-signed V7ClientApproval with risk and
     position attestations and the exact final destination, and
  4) explicitly pass enabled=True and the private signing secret.

Until all these conditions exist, it is impossible to stage/send a client
message through this module. No Telegram token is read here. A future
standalone sender must hold the v7-client-delivery database singleton.
Crashes/ambiguous sends become UNKNOWN_NO_AUTO_RETRY, not duplicate posts.
"""
from __future__ import annotations

from hashlib import sha256
import hmac
import json
import re

from sqlalchemy import select, func

from app.models import (
    V7ClientApproval, V7ClientDelivery, V7DecisionCycle,
    V7DecisionRecord, V7DeliveryDraft, SignalSlot,
)
from app.v7sonic_store import inspect_private_cycle
from app.v7sonic_release import STRATEGY_ID, format_private_rehearsal, _ist_open
from app.telegram.provider import send, DeliveryError

_RELEASE_STATUS = "V7_RELEASE_ELIGIBLE_REVIEWED"
_CHAT = re.compile(r"-?[1-9][0-9]{0,15}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
RELEASE_WINDOW_MS = 30_000
CLAIM_GAP_MS = 4_000


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _digest(obj) -> str:
    return sha256(_canonical(obj)).hexdigest()


def _verify_authenticity(approval, key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise PermissionError("Dedicated release signing secret required")
    if not isinstance(approval.approval_json, dict):
        raise PermissionError("Malformed signed release authorization")
    expected = hmac.new(key, _canonical(approval.approval_json), "sha256").hexdigest()
    if not isinstance(approval.signature_hmac, str) or not hmac.compare_digest(
        expected, approval.signature_hmac
    ):
        raise PermissionError("Invalid independent V7 release signature")


def _validate_release(session, approval, *, now_ms: int, chat_id: str,
                      signing_key: bytes) -> dict:
    if type(now_ms) is not int or not isinstance(chat_id, str) or not _CHAT.fullmatch(chat_id):
        raise PermissionError("Explicit exact Telegram destination and clock required")
    _verify_authenticity(approval, signing_key)
    if (approval.state != "APPROVED" or
            approval.destination_chat_id != chat_id or
            not approval.approved_at_ms <= now_ms < approval.expires_at_ms or
            not _ist_open(approval.decision_boundary_ms) or
            not _ist_open(now_ms) or
            now_ms > approval.decision_boundary_ms + RELEASE_WINDOW_MS):
        raise PermissionError("V7 approval expired, session closed or destination changed")
    packet = approval.approval_json
    keys = {
        "schema", "status", "candidate_id", "decision_boundary_ms",
        "batch_sha256", "destination_chat_id", "approved_at_ms",
        "expires_at_ms", "release_operator_id", "risk_review_sha256",
        "portfolio_positions_independently_reviewed", "source_quality_reviewed",
        "client_publication_authorized", "orders_authorized",
    }
    if (set(packet) != keys or
            packet["schema"] != 1 or packet["status"] != _RELEASE_STATUS or
            packet["candidate_id"] != approval.candidate_id or
            packet["decision_boundary_ms"] != approval.decision_boundary_ms or
            packet["batch_sha256"] != approval.batch_sha256 or
            packet["destination_chat_id"] != approval.destination_chat_id or
            packet["approved_at_ms"] != approval.approved_at_ms or
            packet["expires_at_ms"] != approval.expires_at_ms or
            not isinstance(packet["release_operator_id"], str) or
            not 6 <= len(packet["release_operator_id"]) <= 80 or
            not isinstance(packet["risk_review_sha256"], str) or
            not _HEX.fullmatch(packet["risk_review_sha256"]) or
            packet["portfolio_positions_independently_reviewed"] is not True or
            packet["source_quality_reviewed"] is not True or
            packet["client_publication_authorized"] is not True or
            packet["orders_authorized"] is not False):
        raise PermissionError("Complete signed V7 release authority required")
    cycle = session.get(V7DecisionCycle, approval.decision_boundary_ms)
    decision = session.scalar(select(V7DecisionRecord).where(
        V7DecisionRecord.candidate_id == approval.candidate_id
    ))
    if (cycle is None or cycle.state != "V7_RELEASE_CERTIFIED" or
            cycle.strategy != STRATEGY_ID or
            cycle.batch_sha256 != approval.batch_sha256 or
            decision is None or
            decision.boundary_ms != approval.decision_boundary_ms or
            decision.candidate_id != approval.candidate_id):
        raise PermissionError("Uncertified or mismatched original V7 source")
    # The independent approval may authorize delivery, not trade execution.
    # Validate the paper journal's immutable six-market source and the exact
    # candidate again, even though the certification state is distinct.
    if not isinstance(cycle.batch_json, dict):
        raise PermissionError("Missing sealed original six-market batch")
    # Private-cycle audit currently requires private status, so verify the
    # certified batch using the same exact internal batch verifier.
    from services.t7sonic.forward_paper_ledger import validate_internal_batch
    proof = validate_internal_batch(cycle.batch_json)
    if proof["digest"] != approval.batch_sha256:
        raise PermissionError("Original batch evidence changed")
    items = [x for x in proof["records"]
             if x.get("candidate_id") == approval.candidate_id]
    if len(items) != 1 or items[0] != decision.decision_json:
        raise PermissionError("Original candidate content changed")
    underlying = items[0]
    if underlying.get("expires_at_ms") != approval.expires_at_ms:
        raise PermissionError("Release time differs from underlying candidate")
    draft = session.get(V7DeliveryDraft, approval.candidate_id)
    if (draft is None or draft.state != "BLOCKED_NOT_FOR_CLIENTS" or
            draft.destination_type != "INTERNAL_PRIVATE_ONLY" or
            draft.text != format_private_rehearsal(underlying) or
            draft.text_sha256 != sha256(draft.text.encode()).hexdigest()):
        raise PermissionError("Private V7 candidate draft is not sealed")
    return underlying


def _cross_strategy_lock_check(session, *, candidate_id: str, symbol: str) -> None:
    """Block held V4 slots and outstanding/uncertain V7 client ideas.

    This checks operator-reported positions, NOT authenticated Binance
    account inventory. Future release requires an authoritative position
    feed or equally explicit operator review attestation.
    """
    legacy = list(session.scalars(
        select(SignalSlot).where(
            SignalSlot.symbol == symbol,
            SignalSlot.state.in_(("reserved", "held")),
        ).with_for_update()
    ))
    if legacy:
        raise PermissionError("Legacy held/reserved symbol lock blocks V7 release")
    occupied = list(session.scalars(
        select(V7ClientDelivery)
        .where(V7ClientDelivery.status.in_((
            "pending", "inflight", "delivered", "unknown",
        )))
        .with_for_update()
    ))
    if len([x for x in occupied if x.candidate_id != candidate_id]) >= 4:
        raise PermissionError("V7 portfolio cap of four unreleased slots reached")
    for row in occupied:
        if row.candidate_id == candidate_id:
            continue
        decision = session.scalar(select(V7DecisionRecord).where(
            V7DecisionRecord.candidate_id == row.candidate_id,
        ))
        if decision is None or decision.symbol == symbol:
            raise PermissionError("Existing/unknown V7 client signal locks symbol")


def _message(plan: dict, identifier: str) -> str:
    from datetime import datetime, timedelta, timezone
    boundary = plan["decision_boundary_ms"]
    stamp = datetime.fromtimestamp(
        boundary / 1000, tz=timezone(timedelta(minutes=330))
    ).strftime("%d %b %Y %I:%M %p IST")
    return (
        "MV Intelligent Model V7Sonic | "
        + plan["direction"] + " " + plan["symbol"] + "\n"
        + "Conditional futures trading idea (not an executed order)\n"
        + "Decision: " + stamp + "\n"
        + "Expert: " + plan["expert"] + "\n"
        + "Indicative entry: " + plan["entry"] + "\n"
        + "Stop loss: " + plan["stop_loss"] + "\n"
        + "TP1 (50%): " + plan["take_profit_1"] + "\n"
        + "TP2 (50%): " + plan["take_profit_2"] + "\n"
        + "After TP1: remaining stop to entry\n"
        + "Expires 30 seconds after decision. Execution and fills not verified.\n"
        + "Signal ID: " + identifier[:12]
    )


def enqueue_approved(
    session, candidate_id: str, *, now_ms: int, chat_id: str,
    signing_key: bytes, client_release_enabled: bool = False,
) -> dict:
    """Explicitly authorized one-client-signal staging, never paper auto-publish.

    Runs entirely inside caller's SQL transaction. None of the private
    paper, collector or scheduler code invokes this method.
    """
    if client_release_enabled is not True:
        raise PermissionError("V7 client publication global switch is OFF")
    approval = session.get(V7ClientApproval, candidate_id, with_for_update=True)
    if approval is None:
        raise PermissionError("No separate V7 publication approval")
    decision = _validate_release(
        session, approval, now_ms=now_ms,
        chat_id=chat_id, signing_key=signing_key,
    )
    _cross_strategy_lock_check(session, candidate_id=candidate_id,
                               symbol=decision["symbol"])
    text = _message(decision, candidate_id)
    if len(text) > 4096:
        raise ValueError("V7 Telegram message exceeds limit")
    payload = {"chat_id": chat_id, "text": text,
               "link_preview_options": {"is_disabled": True}}
    old = session.get(V7ClientDelivery, candidate_id, with_for_update=True)
    if old is not None:
        if (old.destination_chat_id != chat_id or
                old.payload_sha256 != _digest(payload) or
                old.payload_json != payload):
            raise PermissionError("Conflicting duplicate V7 Telegram payload")
        return {"status": "EXACT_V7_DELIVERY_ALREADY_STAGED",
                "delivery_status": old.status}
    session.add(V7ClientDelivery(
        candidate_id=candidate_id, destination_chat_id=chat_id,
        status="pending", attempts=0, expires_at_ms=approval.expires_at_ms,
        payload_json=payload, payload_sha256=_digest(payload),
    ))
    session.flush()
    return {"status": "V7_APPROVED_CLIENT_DELIVERY_STAGED",
            "candidate_id": candidate_id, "telegram_sent": False}


def claim_one(
    session, candidate_id: str, *, now_ms: int, chat_id: str,
    signing_key: bytes, client_release_enabled: bool = False,
):
    """Reserve before the irreversible network call. Caller commits FIRST."""
    if client_release_enabled is not True:
        raise PermissionError("V7 client release remains disabled")
    row = session.get(V7ClientDelivery, candidate_id, with_for_update=True)
    if row is None or row.status != "pending":
        return None
    approval = session.get(V7ClientApproval, candidate_id, with_for_update=True)
    if approval is None:
        raise PermissionError("Missing V7 approval at final send")
    try:
        plan = _validate_release(
            session, approval, now_ms=now_ms,
            chat_id=chat_id, signing_key=signing_key,
        )
        _cross_strategy_lock_check(session, candidate_id=candidate_id,
                                   symbol=plan["symbol"])
        if (row.destination_chat_id != chat_id or
                row.expires_at_ms <= now_ms or
                row.payload_json.get("chat_id") != chat_id or
                row.payload_sha256 != _digest(row.payload_json)):
            raise PermissionError("Tampered, expired or destination-changed V7 outbox")
    except (PermissionError, ValueError):
        row.status, row.error_code = "skipped", "FINAL_PUBLICATION_GATE_REJECTED"
        return None
    # A crashed/unacknowledged send is UNKNOWN and fences all later sends.
    unknown = session.scalar(select(V7ClientDelivery.candidate_id).where(
        V7ClientDelivery.status.in_(("inflight", "unknown")),
        V7ClientDelivery.candidate_id != candidate_id,
    ).limit(1))
    last_claim = session.scalar(select(func.max(V7ClientDelivery.claimed_at_ms)))
    if unknown is not None or (last_claim is not None and
                               now_ms < last_claim + CLAIM_GAP_MS):
        return None
    # Never automatically retry or send again after a claim.
    row.status = "inflight"
    row.attempts += 1
    row.claimed_at_ms = now_ms
    session.flush()
    return row.candidate_id, dict(row.payload_json)


def finish(session, candidate_id: str, *, now_ms: int,
           message_id: int | None = None, error_code: str | None = None):
    row = session.get(V7ClientDelivery, candidate_id, with_for_update=True)
    if row is None or row.status != "inflight":
        return
    if message_id is not None and type(message_id) is int and message_id > 0 and error_code is None:
        row.status = "delivered"
        row.message_id = message_id
        row.sent_at_ms = now_ms
        row.error_code = None
    else:
        row.status = "unknown"
        row.error_code = error_code or "AMBIGUOUS_SEND"
    session.flush()


def recover_interrupted(session):
    """At-least-once HTTP is NOT safe; failed acknowledgement is UNKNOWN."""
    rows = list(session.scalars(select(V7ClientDelivery).where(
        V7ClientDelivery.status == "inflight"
    ).with_for_update()))
    for row in rows:
        row.status = "unknown"
        row.error_code = "INTERRUPTED_OR_UNCERTAIN"
    session.flush()
    return len(rows)


async def dispatch_once(
    session_factory, candidate_id: str, *, now_ms: int,
    settings, signing_key: bytes, client_release_enabled: bool = False,
    http_client,
):
    """One-shot dispatch; no automatic retries or daemon/entrypoint.

    Caller must hold an external PostgreSQL v7-client-delivery singleton.
    """
    with session_factory.begin() as session:
        claimed = claim_one(
            session, candidate_id, now_ms=now_ms,
            chat_id=settings.telegram_chat_id,
            signing_key=signing_key,
            client_release_enabled=client_release_enabled,
        )
    if claimed is None:
        return {"status": "V7_NOT_DISPATCHED"}
    # Claim has committed BEFORE sending. Delivery crash is UNKNOWN.
    try:
        message_id = await send(http_client, settings, claimed[1])
        error_code = None
    except DeliveryError as exc:
        message_id, error_code = None, exc.code
    except Exception:
        message_id, error_code = None, "UNEXPECTED_PROVIDER_ERROR"
    with session_factory.begin() as session:
        finish(session, candidate_id, now_ms=now_ms,
               message_id=message_id, error_code=error_code)
    return {"status": "V7_DELIVERED" if message_id is not None else "V7_UNKNOWN_NO_RETRY",
            "message_id": message_id}
