"""Standalone opt-in V7 five-minute capture -> fenced SQL PAPER writer.

Not part of production Compose: this module does not auto-run or grant
Telegram/client publication. The V4 signal engine, V4 delivery queue and
website are deliberately untouched.

Operator execution requires FOUR explicit flags and a private owned folder:
  --run-private-sql-paper --public-network-approved
  --paper-only-acknowledged --sql-paper-write-approved --state-dir ...
The production database is never accessed in default preflight mode.

On the approved path the worker establishes a distinct PostgreSQL advisory
singleton, checks Alembic revision 0009 before any market request, and
retains ownership for every subsequent atomic six-market transaction.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import time

from sqlalchemy import text

from app.database import Session, engine
from app.operations.lease import singleton, worker_transaction
from app.v7sonic_sql_bridge import (
    JOURNAL_LEASE_NAME, stage_private_original_sql_cycle,
)
from services.t7sonic.release_scheduler import (
    preflight, run_private_paper_loop,
)

_MAX_SUMMARY_BYTES = 100_000


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _check_private_sql_ready(session) -> None:
    """Explicitly prevent accidental SQLite/local or premature migration use."""
    if session.get_bind().dialect.name != "postgresql":
        raise RuntimeError("V7 private SQL worker requires an isolated PostgreSQL lease")
    revision = session.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != "0009":
        raise RuntimeError("V7 private journal requires exact applied migration 0009")
    for table in (
        "v7_decision_cycles", "v7_decision_records", "v7_delivery_drafts",
        "signal_slots", "service_leases",
    ):
        if session.scalar(text("SELECT to_regclass(:table)"), {"table": table}) is None:
            raise RuntimeError("V7 required database table absent: " + table)


def _completed_capture_source(summary: dict) -> tuple[str, str]:
    """Resolve the final 31-body immutable receipt, never trust a loose path."""
    if (
        not isinstance(summary, dict) or
        summary.get("status") != "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND"
        or summary.get("client_publication_authorized") is not False
        or summary.get("telegram_messages_sent") != 0
        or summary.get("orders_submitted") != 0
        or summary.get("market_count") != 6
    ):
        raise ValueError("Unapproved or incomplete V7 private capture")

    path = Path(summary["receipt_path"])
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PermissionError("Explicit existing private V7 summary required")
    if path.stat().st_size > _MAX_SUMMARY_BYTES:
        raise ValueError("Private cycle summary exceeds strict size")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != summary["receipt_sha256"]:
        raise ValueError("Altered private cycle summary digest")
    obj = json.loads(raw)
    if (
        obj.get("status") != summary["status"]
        or obj.get("boundary_ms") != summary["decision_boundary_ms"]
        or obj.get("market_count") != 6
        or obj.get("client_publication_authorized") is not False
        or obj.get("telegram_messages_sent") != 0
        or obj.get("orders_submitted") != 0
        or obj.get("last_original_http_sha256") != summary["original_http_sha256"]
        or obj.get("paper_batch_sha256") != summary["paper_batch_sha256"]
    ):
        raise ValueError("Private capture receipt/summary mismatch")
    attempts = obj.get("source_attempts")
    if (
        not isinstance(attempts, list)
        or len(attempts) != obj.get("attempt_count")
        or not 1 <= len(attempts) <= 3
        or attempts[-1].get("original_http_sha256") != summary["original_http_sha256"]
    ):
        raise ValueError("Incomplete final source evidence chain")
    return attempts[-1]["original_http_file"], summary["original_http_sha256"]


def _stage_final_capture(summary: dict, *, clock_ms=_now_ms) -> dict:
    path, source_digest = _completed_capture_source(summary)
    # A 30-second deadline is checked independently by the V7 SQL bridge,
    # including after any scheduler/SQLite persistence overhead.
    with worker_transaction(JOURNAL_LEASE_NAME, Session) as session:
        stored = stage_private_original_sql_cycle(
            session,
            original_path=path,
            original_http_sha256=source_digest,
            observed_now_ms=clock_ms(),
        )
    if (
        stored["decision_boundary_ms"] != summary["decision_boundary_ms"]
        or stored["batch_sha256"] != summary["paper_batch_sha256"]
        or stored["client_publication_authorized"] is not False
        or stored["telegram_messages_sent"] != 0
        or stored["orders_submitted"] != 0
    ):
        raise ValueError("Fenced SQL/private capture batch mismatch")
    return stored


def run_private_sql_paper(
    state_dir: str, *,
    public_network_approved: bool = False,
    paper_only_acknowledged: bool = False,
    sql_paper_write_approved: bool = False,
    max_cycles: int | None = None,
    capture=None,
) -> dict:
    """A standalone opt-in V7 paper worker; deliberately no Telegram secrets."""
    if (
        public_network_approved is not True
        or paper_only_acknowledged is not True
        or sql_paper_write_approved is not True
    ):
        raise PermissionError("Three explicit V7 private SQL capture approvals required")
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Non-PostgreSQL database forbidden for real V7 SQL worker")

    with singleton(JOURNAL_LEASE_NAME):
        with worker_transaction(JOURNAL_LEASE_NAME, Session) as session:
            _check_private_sql_ready(session)
        result = run_private_paper_loop(
            state_dir,
            public_network_approved=True,
            paper_only_acknowledged=True,
            durable_sql_sink=_stage_final_capture,
            sql_journal_approved=True,
            max_cycles=max_cycles,
            capture=capture,
        )
    if (
        result["client_publication_authorized"] is not False
        or result["telegram_messages_sent"] != 0
        or result["orders_submitted"] != 0
    ):
        raise ValueError("Unexpected V7 SQL worker publication")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="V7 standalone private SQL paper journal, no client sending"
    )
    parser.add_argument("--run-private-sql-paper", action="store_true")
    parser.add_argument("--public-network-approved", action="store_true")
    parser.add_argument("--paper-only-acknowledged", action="store_true")
    parser.add_argument("--sql-paper-write-approved", action="store_true")
    parser.add_argument("--state-dir")
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args()

    if not args.run_private_sql_paper:
        if any((
            args.public_network_approved,
            args.paper_only_acknowledged,
            args.sql_paper_write_approved,
            args.max_cycles is not None,
        )):
            parser.error("Approval flags require explicit --run-private-sql-paper")
        result = preflight(_now_ms(), state_dir=args.state_dir)
        result["postgresql_contacted"] = False
    else:
        if not args.state_dir:
            parser.error("Explicit --state-dir is mandatory")
        result = run_private_sql_paper(
            args.state_dir,
            public_network_approved=args.public_network_approved,
            paper_only_acknowledged=args.paper_only_acknowledged,
            sql_paper_write_approved=args.sql_paper_write_approved,
            max_cycles=args.max_cycles,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
