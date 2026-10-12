"""Operator-invoked ONE-SHOT V7Sonic public paper capture CLI.

DEFAULT preflight is completely offline. A real capture requires the operator
to explicitly supply three switches and an owner-private output directory.
It waits for at most one next five-minute UTC boundary, performs ONLY public
Binance USD-M HTTP GETs, and writes one atomic local JSON preview. No daemon,
recurrence, client Telegram messages, trades, exchange keys, user accounts,
or modification of MV production services.

The frozen October 15–December 29 2026 research window remains unchanged.
A local clock and TLS-transport response are not an independent witness.
Paper candidate levels and order quantities are NOT customer signals.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from app.research.t7sonic_forward_protocol import START_MS, END_MS, STEP_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_one_shot import optional_public_paper_capture

MAX_WAIT_MS = STEP_MS
_MAX_REPORT_BYTES = 4_000_000
_PREFIX = "v7sonic-public-paper-"


def next_boundary(now_ms: int) -> int:
    if type(now_ms) is not int or now_ms <= 0:
        raise ValueError("Exact UTC epoch milliseconds required")
    return (now_ms//STEP_MS + 1)*STEP_MS


def offline_preflight(*, now_ms: int) -> dict:
    """No imports of any HTTP client, no file I/O, no automatic scheduling."""
    next_ms = next_boundary(now_ms)
    return {
        "status": "OFFLINE_PREFLIGHT_NO_MARKET_REQUESTS",
        "utc_clock_local_claim": datetime.fromtimestamp(
            now_ms/1000, tz=timezone.utc
        ).isoformat(),
        "next_five_minute_boundary_utc": datetime.fromtimestamp(
            next_ms/1000, tz=timezone.utc
        ).isoformat(),
        "next_boundary_ms": next_ms,
        "frozen_window_starts_utc": datetime.fromtimestamp(
            START_MS/1000, tz=timezone.utc
        ).isoformat(),
        "frozen_window_ends_exclusive_utc": datetime.fromtimestamp(
            END_MS/1000, tz=timezone.utc
        ).isoformat(),
        "next_boundary_eligible": START_MS <= next_ms < END_MS,
        "frozen_six_markets": list(MARKETS),
        "real_market_requests_per_capture": 31,
        "external_requests_made": 0,
        "production_engine_changed": False,
        "telegram_enqueued": False,
        "client_publication_authorized": False,
        "real_money_orders_authorized": False,
    }


def _private_output_directory(directory: str) -> Path:
    if not isinstance(directory, str) or not directory:
        raise PermissionError("Explicit standalone private output directory required")
    target = Path(directory)
    if not target.is_absolute() or not target.is_dir() or target.is_symlink():
        raise PermissionError("Existing nonsymlink absolute output directory required")
    info = target.stat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("Paper output directory must be owned and mode 0700")
    return target


def _write_atomic_report(target_dir: Path, boundary_ms: int, report: dict) -> dict:
    """No overwrite of same boundary; fsync then hardlink atomically."""
    if (report.get("decision_boundary_ms") != boundary_ms or
            report.get("status") != "INTERNAL_ONLY_PUBLIC_REST_CYCLE_UNATTESTED" or
            report.get("markets_evaluated") != len(MARKETS) or
            report.get("source_http_responses") != 31 or
            report.get("telegram_enqueued") is not False or
            report.get("client_publication_authorized") is not False or
            report.get("real_money_orders_authorized") is not False or
            report.get("quotes_fresh_at_return_local_clock_claim") is not True or
            report.get("complete_cycle_returned_before_deadline_local_clock_claim") is not True):
        raise ValueError("Not a valid complete nonpublishable public paper batch")
    encoded = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False)
               + "\n").encode("utf-8")
    if not 2 <= len(encoded) <= _MAX_REPORT_BYTES:
        raise ValueError("Unbounded live paper preview report")
    destination = target_dir/(_PREFIX + str(boundary_ms)+".json")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Observation already recorded; do not replace or backfill")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=target_dir, prefix=".v7sonic-tmp-",
            delete=False
        ) as stream:
            temp_path=Path(stream.name)
            os.chmod(stream.name, 0o600)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp_path, destination, follow_symlinks=False)
        dirfd=os.open(str(target_dir), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return {
        "status": "LOCAL_PRIVATE_PAPER_CAPTURE_RECORDED_NOT_PUBLISHED",
        "report_path": str(destination),
        "report_sha256": sha256(encoded).hexdigest(),
        "decision_boundary_ms": boundary_ms,
        "markets_evaluated": len(MARKETS),
        "candidate_count": report["candidate_count"],
        "source_http_responses": 31,
        "complete_source_bodies_saved": False,
        "off_vps_evidence_replication_verified": False,
        "independent_timestamp_verified": False,
        "actual_exchange_execution_verified": False,
        "telegram_messages_sent": 0,
        "production_engine_changed": False,
        "client_publication_authorized": False,
        "real_money_orders_authorized": False,
    }


def capture_once(*, output_dir: str,
                 capture_approved: bool = False,
                 public_network_approved: bool = False,
                 paper_only_acknowledged: bool = False) -> dict:
    """Wait for at most one boundary, fetch public data once, store paper preview.

    NO network is possible without all three opt-ins and directory checks.
    The final report is a local receipt claim, never independent attestation.
    """
    if (capture_approved is not True or
            public_network_approved is not True or
            paper_only_acknowledged is not True):
        raise PermissionError("Explicit capture, network and PAPER-only approvals required")
    target_dir=_private_output_directory(output_dir)
    now_ms=time.time_ns()//1_000_000
    boundary=next_boundary(now_ms)
    if not START_MS <= boundary < END_MS:
        raise ValueError("Next completed boundary outside frozen prospective window")
    output=target_dir/(_PREFIX+str(boundary)+".json")
    if output.exists() or output.is_symlink():
        raise FileExistsError("A report already exists for that boundary")
    delay_ms=boundary-now_ms
    if not 0 < delay_ms <= MAX_WAIT_MS:
        raise ValueError("Impossible waiting interval")
    time.sleep(delay_ms/1000)
    arrived=time.time_ns()//1_000_000
    if not boundary <= arrived <= boundary+4_000:
        raise ValueError("UTC clock advanced beyond permitted observation start")
    report=optional_public_paper_capture(
        boundary, network_approved=True
    )
    # When the one-shot worker fails, NO success report is written. A failure
    # must be treated as a GAP, not an abstaining or published signal.
    return _write_atomic_report(target_dir,boundary,report)


def main():
    parser=argparse.ArgumentParser(
        description="V7Sonic public one-shot PAPER observer: offline default"
    )
    parser.add_argument("--capture-next-boundary",action="store_true")
    parser.add_argument("--network-approved",action="store_true")
    parser.add_argument("--paper-only-acknowledged",action="store_true")
    parser.add_argument("--output-dir")
    args=parser.parse_args()
    if not args.capture_next_boundary:
        if args.network_approved or args.paper_only_acknowledged or args.output_dir:
            parser.error("Capture flags require --capture-next-boundary")
        response=offline_preflight(now_ms=time.time_ns()//1_000_000)
    else:
        response=capture_once(
            output_dir=args.output_dir,
            capture_approved=True,
            public_network_approved=args.network_approved,
            paper_only_acknowledged=args.paper_only_acknowledged,
        )
    print(json.dumps(response,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
