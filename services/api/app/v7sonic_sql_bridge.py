"""Isolated V7 private paper capture -> fenced PostgreSQL-compatible journal.

Takes a complete locally preserved 31-response receipt and one database
transaction. Recomputes all six V7 decisions while checking cross-strategy
active/reserved slots, prior candidate IDs, and the existing worker fence.

This is NOT a live trading publisher: no V4 signal/event/outbox inserts,
Telegram HTTP calls, execution endpoints, migrations or daemon activation.
The caller must hold the distinct 'v7-paper-journal' lease on PostgreSQL.

The format intentionally cannot transition V7DeliveryDraft to a sendable
state; separate future production-authorized plans require different
contracts and explicit release acceptance.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import stat

from sqlalchemy import select

from app.models import SignalSlot, V7DecisionRecord, V7DecisionCycle
from app.operations.lease import assert_fence
from app.research.t7sonic_validation_plan import MARKETS
from app.v7sonic_release import rehearse_original_capture
from app.v7sonic_store import store_private_cycle, inspect_private_cycle
from services.t7sonic.replay_original_capture import _read_private_file


JOURNAL_LEASE_NAME = "v7-paper-journal"
_MAX_ORIGINAL_FILE_BYTES = 8_000_000


def _original_source(path: str | Path, expected_sha256: str):
    """Require an owner-private, unchanged original source file.

    SHA256 proves equality to an operator-pinned local byte digest only,
    not Binance's signature or an externally witnessed collection time.
    """
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha256)
    ):
        raise ValueError("Exact private source digest required")
    item = Path(path)
    if (
        not item.is_absolute()
        or item.is_symlink()
        or not item.is_file()
        or item.parent.is_symlink()
    ):
        raise PermissionError("Private regular original evidence file required")
    st = item.stat()
    parent = item.parent.stat()
    if (
        st.st_uid != os.getuid() or st.st_mode & 0o077
        or parent.st_uid != os.getuid() or parent.st_mode & 0o077
        or not stat.S_ISREG(st.st_mode)
        or not 100 <= st.st_size <= _MAX_ORIGINAL_FILE_BYTES
    ):
        raise PermissionError("Original evidence must be size-bounded and owner-only")

    # The file is create-only in the collector. Refuse a stale/tampered path.
    with item.open("rb") as source:
        raw = source.read(_MAX_ORIGINAL_FILE_BYTES + 1)
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Original 31-body receipt digest mismatch")
    return _read_private_file(str(item))


def stage_private_original_sql_cycle(
    session, *,
    original_path: str | Path,
    original_http_sha256: str,
    observed_now_ms: int,
) -> dict:
    """Stage one fully sealed five-minute V7 PAPER cycle in caller's DB TX.

    On PostgreSQL, ownership of the v7-paper-journal lease must be fenced.
    A concurrent old/legacy reservation blocks its symbol (fail closed).
    The entire V7 six-market cycle + blocked rehearsal drafts are added
    atomically by the surrounding SQLAlchemy transaction.
    """
    assert_fence(session, JOURNAL_LEASE_NAME)
    receipt = _original_source(original_path, original_http_sha256)

    if type(observed_now_ms) is not int:
        raise ValueError("Exact observation clock required")

    existing = session.get(V7DecisionCycle, receipt["decision_boundary_ms"])
    if existing is not None:
        if existing.original_http_sha256 != original_http_sha256:
            raise ValueError("Conflicting original HTTP receipt for stored V7 boundary")
        prior_audit = inspect_private_cycle(session, receipt["decision_boundary_ms"])
        return {
            "schema": 1,
            "status": "FENCED_V7_PRIVATE_SQL_EXACT_REPLAY_NO_CLIENT_SEND",
            "decision_boundary_ms": receipt["decision_boundary_ms"],
            "source_sha256": original_http_sha256,
            "batch_sha256": existing.batch_sha256,
            "legacy_locked_markets": [],
            "markets_evaluated": prior_audit["market_records"],
            "candidate_count": len([
                x for x in existing.batch_json["indicative_candidates"]
            ]),
            "private_drafts_blocked": prior_audit["drafts_blocked"],
            "sql_journal_result": "EXACT_V7_CYCLE_REPLAY_UNMODIFIED",
            "production_strategy_switched": False,
            "client_publication_authorized": False,
            "telegram_messages_sent": 0,
            "orders_submitted": 0,
        }

    # Within the same transaction, fence against reserved or held V4
    # positions. A stale/uncertain legacy slot still blocks publication.
    legacy_slots = list(session.scalars(
        select(SignalSlot)
        .where(
            SignalSlot.symbol.in_(MARKETS),
            SignalSlot.state.in_(("reserved", "held")),
        )
        .order_by(SignalSlot.symbol)
        .with_for_update()
    ))
    active_symbols = tuple(sorted({row.symbol for row in legacy_slots}))
    previous = tuple(sorted(set(session.scalars(
        select(V7DecisionRecord.candidate_id)
        .where(V7DecisionRecord.candidate_id.is_not(None))
        .order_by(V7DecisionRecord.candidate_id)
    ))))

    report = rehearse_original_capture(
        receipt,
        observed_now_ms=observed_now_ms,
        active_symbols=active_symbols,
        previously_seen_candidate_ids=previous,
    )
    result = store_private_cycle(
        session,
        report=report,
        original_http_sha256=original_http_sha256,
        recorded_at_ms=observed_now_ms,
    )
    # Ensure pending SQL writes are read back and checked before commit.
    session.flush()
    check = inspect_private_cycle(
        session,
        receipt["decision_boundary_ms"],
    )
    if (
        check["market_records"] != 6
        or check["status"] != "V7_PRIVATE_SQL_AUDIT_OK_NO_SEND"
        or check["client_publication_authorized"] is not False
        or check["telegram_messages_sent"] != 0
    ):
        raise ValueError("V7 private journal audit not complete")

    return {
        "schema": 1,
        "status": "FENCED_V7_PRIVATE_SQL_CYCLE_NO_CLIENT_SEND",
        "decision_boundary_ms": receipt["decision_boundary_ms"],
        "source_sha256": original_http_sha256,
        "batch_sha256": report["source_batch_sha256"],
        "legacy_locked_markets": list(active_symbols),
        "markets_evaluated": report["markets_evaluated"],
        "candidate_count": report["candidate_count"],
        "private_drafts_blocked": check["drafts_blocked"],
        "sql_journal_result": result["status"],
        "production_strategy_switched": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }
