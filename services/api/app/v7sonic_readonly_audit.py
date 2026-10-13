"""Read-only forensic examination of ONE completed original V7 paper cycle.

No market network, Telegram, exchange account, production DB or writes.
Use inside the original UID 10001 container with the existing evidence folder
mounted :ro, and pin the three SHA256 receipts taken from the operator log.
This is an historical paper decision audit, not a tradable signal.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import quote

from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_paper_ledger import validate_internal_batch, _canonical
from services.t7sonic.replay_original_capture import replay_original

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SUMMARY_BYTES_MAX = 100_000
_ORIGINAL_BYTES_MAX = 8_000_000
_BATCH_BYTES_MAX = 1_000_000
_PAPER = "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION"


def _read_regular(folder: Path, path: Path, *, bound: int) -> bytes:
    if (path.parent != folder or path.is_symlink() or
            not path.is_file() or
            not stat.S_ISREG(path.stat().st_mode) or
            not 1 <= path.stat().st_size <= bound):
        raise PermissionError("Owner-controlled regular bounded evidence file required")
    return path.read_bytes()


def audit_one_stored_cycle(
    folder: str | Path, *, boundary_ms: int,
    summary_sha256: str, original_sha256: str, batch_sha256: str,
) -> dict:
    if (type(boundary_ms) is not int or boundary_ms <= 0 or
            boundary_ms % 300_000 or
            any(not isinstance(s, str) or not _HEX.fullmatch(s)
                for s in (summary_sha256, original_sha256, batch_sha256))):
        raise ValueError("Exact boundary and three full lower-case SHA256 values required")
    root = Path(folder)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir() or
            root.stat().st_mode & 0o077):
        raise PermissionError("Existing owner-private evidence directory required")

    summary_path = root / f"v7sonic-private-paper-cycle-{boundary_ms}.json"
    raw_summary = _read_regular(root, summary_path, bound=_SUMMARY_BYTES_MAX)
    if sha256(raw_summary).hexdigest() != summary_sha256:
        raise ValueError("Historical cycle summary SHA256 mismatch")
    summary = json.loads(raw_summary)
    if (not isinstance(summary, dict) or
            summary.get("status") != "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND" or
            summary.get("boundary_ms") != boundary_ms or
            summary.get("market_count") != len(MARKETS) or
            summary.get("paper_batch_sha256") != batch_sha256 or
            summary.get("last_original_http_sha256") != original_sha256 or
            summary.get("production_database_written") is not False or
            summary.get("client_publication_authorized") is not False or
            summary.get("telegram_messages_sent") != 0 or
            summary.get("orders_submitted") != 0):
        raise ValueError("Original six-market private receipt failed validation")
    attempts = summary.get("source_attempts")
    if (not isinstance(attempts, list) or not attempts or
            len(attempts) != summary.get("attempt_count") or
            not isinstance(attempts[-1], dict) or
            attempts[-1].get("original_http_sha256") != original_sha256):
        raise ValueError("Missing original acquisition attempt evidence")
    original_path = Path(attempts[-1].get("original_http_file", ""))
    if (not original_path.is_absolute() or
            original_path.parent != root or
            not original_path.name.startswith("v7sonic-original-http-")):
        raise PermissionError("Original evidence path not in expected private directory")
    raw_original = _read_regular(root, original_path, bound=_ORIGINAL_BYTES_MAX)
    if sha256(raw_original).hexdigest() != original_sha256:
        raise ValueError("Original retained HTTP source SHA256 mismatch")
    source = json.loads(raw_original)
    cross = replay_original(source)
    if (cross.get("original_http_responses_hash_checked") != 31 or
            cross.get("exact_reconciliation_passed") is not True or
            cross.get("decision_boundary_ms") != boundary_ms or
            cross.get("price_field_discrepancies") != 0 or
            cross.get("volume_field_discrepancies") != 0 or
            cross.get("client_publication_authorized") is not False):
        raise ValueError("Original source hashes or timeframe reconciliation failed")

    ledger = root / "v7sonic-paper-release.sqlite3"
    if (ledger.is_symlink() or not ledger.is_file() or
            not stat.S_ISREG(ledger.stat().st_mode)):
        raise PermissionError("Missing immutable-path paper ledger")
    # Open existing SQLite WITHOUT create/write rights, including at the
    # filesystem level when the caller bind-mounts /state :ro.
    uri = "file:" + quote(str(ledger), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3.0) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA foreign_keys=ON")
        cycle = db.execute(
            "SELECT batch_sha256,body_json FROM paper_cycles WHERE decision_boundary_ms=?",
            (boundary_ms,),
        ).fetchone()
        if cycle is None or cycle[0] != batch_sha256 or len(cycle[1]) > _BATCH_BYTES_MAX:
            raise ValueError("No matching complete persisted paper batch")
        batch = json.loads(cycle[1])
        proof = validate_internal_batch(batch)
        if (proof["digest"] != batch_sha256 or
                _canonical(batch) != cycle[1] or
                proof["boundary"] != boundary_ms or
                proof["candidate_count"] != summary["candidate_count"]):
            raise ValueError("Tampered sealed six-market batch")
        rows = db.execute(
            "SELECT symbol,status,body_json,candidate_id,lifecycle "
            "FROM paper_decisions WHERE decision_boundary_ms=? ORDER BY symbol",
            (boundary_ms,),
        ).fetchall()

    if len(rows) != 6 or set(x[0] for x in rows) != set(MARKETS):
        raise ValueError("Incomplete recorded market decisions")
    by_symbol = {x["symbol"]: x for x in proof["records"]}
    for symbol, status, body, candidate_id, lifecycle in rows:
        original = by_symbol[symbol]
        if (status != original["status"] or body != _canonical(original) or
                candidate_id != original.get("candidate_id") or
                lifecycle not in (("INTERNAL_PAPER_ONLY", "EXPIRED_UNSENT")
                                  if status == _PAPER else ("NO_SETUP",))):
            raise ValueError("Persisted per-market decision tampered")

    candidates = []
    rejected = []
    for rec in proof["records"]:
        if rec["status"] == "NO_CANDIDATE":
            rejected.append({"symbol": rec["symbol"], "reason": rec["reason"]})
        else:
            candidates.append({
                "symbol": rec["symbol"],
                "direction": rec["direction"],
                "expert": rec["expert"],
                "entry": rec["entry"],
                "stop_loss": rec["stop_loss"],
                "take_profit_1": rec["take_profit_1"],
                "take_profit_2": rec["take_profit_2"],
                "estimated_net_rr_50_50_if_both_tps_filled":
                    rec.get("estimated_net_rr_50_50_if_both_tps_filled"),
                "status": "EXPIRED_INTERNAL_PAPER_IDEA_DO_NOT_TRADE",
            })
    if len(candidates) != summary["candidate_count"] or (
            len(candidates) + len(rejected) != 6):
        raise ValueError("Candidate and noncandidate counts mismatch")
    return {
        "status": "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS",
        "boundary_ms": boundary_ms,
        "original_http_responses_verified": 31,
        "markets_verified": len(MARKETS),
        "candidates": candidates,
        "noncandidates": rejected,
        "source_sha256": original_sha256,
        "batch_sha256": batch_sha256,
        "local_source_independently_authenticated": False,
        "live_account_or_positions_authenticated": False,
        "clients_notified": 0,
        "orders_submitted": 0,
        "historical_only_do_not_trade": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only V7 source and paper-ledger audit; NEVER send"
    )
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--boundary-ms", type=int, required=True)
    parser.add_argument("--summary-sha256", required=True)
    parser.add_argument("--original-sha256", required=True)
    parser.add_argument("--batch-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(audit_one_stored_cycle(
        args.state_dir, boundary_ms=args.boundary_ms,
        summary_sha256=args.summary_sha256,
        original_sha256=args.original_sha256,
        batch_sha256=args.batch_sha256,
    ), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
