"""V7Sonic operator-approved one-boundary PRIVATE paper-cycle runner.

This is a real public Binance 31-response acquisition path, but explicitly
NOT a client publisher or production replacement. A durable create-only claim
is acquired before waiting for the future five-minute boundary. Crashes,
conflicting retries and missed closes are gaps, never fabricated NO_SETUPs.

Execution requires separate --capture-once --public-network-approved and
--paper-only-acknowledged flags. All market data are public; no order,
account, Telegram, production PostgreSQL, or website APIs are accessed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlencode

from app import v7sonic_release as release
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.early_live_smoke import (
    FRAMES, STEP, _get, _save_original_responses,
    _write_immutable_file, next_boundary, url_for,
)
from services.t7sonic.forward_paper_ledger import PrivatePaperLedger
from services.t7sonic.replay_original_capture import _read_private_file

_MAX_ATTEMPTS = 3
_MAX_LAG_MS = 30_000
_RETRY_DELAY_S = 1.5
_MIN_RETRY_BUDGET_MS = 4_500
_LEDGER_NAME = "v7sonic-paper-release.sqlite3"


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _private_directory(path: str | Path) -> Path:
    folder = Path(path)
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise PermissionError("Existing real absolute private state folder required")
    st = folder.stat()
    if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or
            st.st_mode & 0o077):
        raise PermissionError("Release paper state folder must be owner-only")
    return folder


def _capture_all_31(boundary: int, *, getter) -> tuple:
    """Full independent REST request batch; quotes collected after candles."""
    candles = {sym: {} for sym in MARKETS}
    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {
            pool.submit(getter, url_for(symbol, frame, boundary), 256_000):
            (symbol, frame)
            for symbol in MARKETS for frame in FRAMES
        }
        info_job = pool.submit(
            getter, "https://fapi.binance.com/fapi/v1/exchangeInfo", 2_000_000
        )
        for future in as_completed(jobs):
            symbol, frame = jobs[future]
            candles[symbol][frame] = future.result()[0]
        info = info_job.result()[0]

    books, receipts = {}, {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        jobs = {
            pool.submit(
                getter, "https://fapi.binance.com/fapi/v1/ticker/bookTicker?"
                + urlencode({"symbol": symbol}), 8192
            ): symbol
            for symbol in MARKETS
        }
        for future in as_completed(jobs):
            symbol = jobs[future]
            books[symbol], receipts[symbol], _elapsed = future.result()
    return candles, books, info, receipts


def capture_one_private_cycle(
    state_dir: str, *,
    public_network_approved: bool = False,
    paper_only_acknowledged: bool = False,
    active_symbols: tuple[str, ...] = (),
    previously_seen_candidate_ids: tuple[str, ...] = (),
    clock_ms=None,
    sleeper=None,
    getter=None,
) -> dict:
    """Attempt a single future completed 5m boundary, without any delivery.

    The caller-supplied position/duplicate snapshots are NOT authenticated.
    They are only suitable for internal rehearsal; clients remain disabled.
    """
    if public_network_approved is not True or paper_only_acknowledged is not True:
        raise PermissionError("Both public-network and paper-only approvals required")
    folder = _private_directory(state_dir)
    clock = clock_ms if clock_ms is not None else _clock_ms
    sleep = sleeper if sleeper is not None else time.sleep
    fetch = getter if getter is not None else _get
    active_symbols = release._as_market_tuple(active_symbols, name="active symbols")
    previously_seen_candidate_ids = release._seen_ids(previously_seen_candidate_ids)
    now = clock()
    boundary = next_boundary(now)
    if not release._ist_open(boundary):
        raise ValueError("V7 private release rehearsal outside IST client session")

    # Create-only, fsynced claim BEFORE the wait/HTTP. A crashed or concurrent
    # worker can never generate a second decision for the same boundary.
    claim = folder / f"v7sonic-private-claim-{boundary}.json"
    blob = (
        json.dumps({
            "schema": 1, "decision_boundary_ms": boundary,
            "claimed_ms_local_clock_unattested": now,
            "status": "PRIVATE_PAPER_BOUNDARY_CLAIMED",
            "client_publication_authorized": False,
            "telegram_enqueued": False, "orders_authorized": False,
        }, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    _write_immutable_file(folder, claim, blob)

    sleep(max(0.0, (boundary - clock()) / 1_000))
    began = clock()
    if not boundary <= began <= boundary + 4_000:
        raise ValueError("Missed initial five-minute boundary; not backfilling")

    attempts = []
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            candles, books, info, receipts = _capture_all_31(
                boundary, getter=fetch
            )
        except Exception as exc:
            # No complete 31-body batch exists. Preserve a distinct GAP,
            # not a synthetic NO_CANDIDATE or partially inferred source.
            # Never retry an unknown/incomplete HTTP batch in this lane.
            _write_immutable_file(
                folder,
                folder / f"v7sonic-private-acquisition-gap-{boundary}-{attempt}.json",
                (json.dumps({
                    "schema": 1,
                    "status": "PRIVATE_PAPER_ACQUISITION_FAILED_NO_SETUP_NOT_INFERRED",
                    "decision_boundary_ms": boundary,
                    "attempt": attempt,
                    "exception_class": type(exc).__name__,
                    "original_http_responses_complete": False,
                    "client_publication_authorized": False,
                    "telegram_messages_sent": 0,
                    "orders_submitted": 0,
                }, sort_keys=True) + "\\n").encode(),
            )
            raise
        completed = clock()

        # Capture ORIGINAL 31 bodies before any analysis, even if all plans
        # fail. No pre-existing receipt is overwritten.
        raw_path, raw_hash = _save_original_responses(
            folder, boundary, candles, books, info, receipts, completed,
            attempt=attempt
        )
        attempts.append({
            "attempt": attempt,
            "original_http_file": raw_path,
            "original_http_sha256": raw_hash,
        })
        receipt = _read_private_file(raw_path)
        try:
            report = release.rehearse_original_capture(
                receipt, observed_now_ms=clock(),
                active_symbols=active_symbols,
                previously_seen_candidate_ids=previously_seen_candidate_ids,
            )
        except Exception as exc:
            # The strict fieldwise historical-vs-native check stays exact.
            # Only a verified 31-body cross-resolution disagreement can
            # trigger a new, complete 31-request batch before the deadline.
            retryable = (
                type(exc) is ValueError and
                str(exc) == "Original market-source reconciliation failed"
            )
            retry = (
                retryable and attempt < _MAX_ATTEMPTS and
                clock() + int(_RETRY_DELAY_S*1000) + _MIN_RETRY_BUDGET_MS
                <= boundary + _MAX_LAG_MS
            )
            _write_immutable_file(
                folder,
                folder / f"v7sonic-private-rejected-{boundary}-{attempt}.json",
                (json.dumps({
                    "status": "PRIVATE_PAPER_ANALYSIS_REJECTED",
                    "attempt": attempt, "reason": str(exc)[:240],
                    "retry_eligible": retry,
                    "original_http_sha256": raw_hash,
                    "client_publication_authorized": False,
                    "telegram_enqueued": False, "orders_authorized": False,
                }, sort_keys=True) + "\n").encode()
            )
            if retry:
                sleep(_RETRY_DELAY_S)
                continue
            raise

        finished = clock()
        if finished > boundary + _MAX_LAG_MS:
            raise ValueError("Decision completed after 30-second deadline")
        if not release._ist_open(finished):
            raise ValueError("Source close or decision outside IST session")

        paper_batch = report["sealed_internal_paper_batch"]
        with PrivatePaperLedger(
            folder / _LEDGER_NAME, local_write_approved=True
        ) as ledger:
            stored = ledger.record(paper_batch, observed_at_ms=finished)
            audited = ledger.audit(boundary)
        if (audited["six_decisions_verified"] is not True or
                audited["batch_sha256"] != report["source_batch_sha256"]):
            raise ValueError("Durable batch audit rejected")

        summary = {
            "schema": 1,
            "status": "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND",
            "boundary_ms": boundary,
            "attempt_count": attempt,
            "source_attempts": attempts,
            "last_original_http_sha256": raw_hash,
            "market_count": report["markets_evaluated"],
            "candidate_count": report["candidate_count"],
            "new_rehearsals": report["new_rehearsals"],
            "paper_batch_sha256": paper_batch["batch_sha256"],
            "ledger_status": stored["status"],
            "ledger_audit_status": audited["status"],
            "position_state_authenticated": False,
            "production_database_written": False,
            "client_publication_authorized": False,
            "telegram_messages_sent": 0,
            "orders_submitted": 0,
        }
        encoded = (json.dumps(summary, sort_keys=True, indent=2) + "\n").encode()
        output = folder / f"v7sonic-private-paper-cycle-{boundary}.json"
        _write_immutable_file(folder, output, encoded)
        return {
            "status": summary["status"],
            "decision_boundary_ms": boundary,
            "attempt_count": attempt,
            "market_count": summary["market_count"],
            "candidate_count": summary["candidate_count"],
            "original_http_sha256": raw_hash,
            "paper_batch_sha256": paper_batch["batch_sha256"],
            "ledger_audit_status": audited["status"],
            "receipt_path": str(output),
            "receipt_sha256": sha256(encoded).hexdigest(),
            "production_database_written": False,
            "client_publication_authorized": False,
            "telegram_messages_sent": 0,
            "orders_submitted": 0,
        }
    raise AssertionError("Unreachable retry exhaustion")


def main():
    parser = argparse.ArgumentParser(
        description="V7Sonic one-boundary PRIVATE paper capture; NO SEND"
    )
    parser.add_argument("--capture-once", action="store_true")
    parser.add_argument("--public-network-approved", action="store_true")
    parser.add_argument("--paper-only-acknowledged", action="store_true")
    parser.add_argument("--state-dir")
    args = parser.parse_args()
    if not args.capture_once:
        if args.public_network_approved or args.paper_only_acknowledged or args.state_dir:
            parser.error("Capture flags require --capture-once")
        result = {
            "status": "PREFLIGHT_OFFLINE_NO_NETWORK",
            "next_boundary_ms_local_claim": next_boundary(_clock_ms()),
            "client_publication_authorized": False,
            "telegram_messages_sent": 0, "orders_submitted": 0,
        }
    else:
        if not args.state_dir:
            parser.error("Explicit private --state-dir required")
        result = capture_one_private_cycle(
            args.state_dir,
            public_network_approved=args.public_network_approved,
            paper_only_acknowledged=args.paper_only_acknowledged,
        )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
