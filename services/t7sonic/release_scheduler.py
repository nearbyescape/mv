"""V7Sonic standalone five-minute PRIVATE paper runner (NO CLIENT DELIVERY).

The background loop schedules future 5-minute boundaries during the
09:00–23:00 IST session. Each boundary invokes the complete, audited 31-source
live capture and isolated SQLite paper journal exactly once.

This code does NOT write the MV production PostgreSQL DB, enqueue/send
Telegram, place Binance orders, or resume the V4 engine.

Safety:
  * all public-network and paper-only opt-ins required at startup;
  * wall-clock reversal or missed opportunity never becomes NO_SETUP;
  * a failed capture is written as an operator-visible gap, and the loop
    fails closed rather than retrying stale decisions;
  * an operator pause file suppresses future boundaries;
  * no auto-start or restart flags in production Compose;
  * enough local disk space is mandatory before every complete capture.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import stat
import time

from app import v7sonic_release as release
from services.t7sonic.early_live_smoke import (
    STEP, _write_immutable_file, next_boundary,
)
from services.t7sonic.release_capture_worker import (
    _private_directory, capture_one_private_cycle,
)

SESSION_RECHECK_SECONDS = 10.0
MIN_FREE_BYTES = 2 * 1024**3
PAUSE_NAME = "v7sonic-operator-pause"
GAP_PREFIX = "v7sonic-private-gap-"


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def preflight(now_ms: int, *, state_dir: str | None = None) -> dict:
    if type(now_ms) is not int or now_ms <= 0:
        raise ValueError("Invalid clock")
    if state_dir is not None:
        _private_directory(state_dir)
    target = next_boundary(now_ms)
    return {
        "status": "V7_PRIVATE_SCHEDULER_PREFLIGHT_NO_NETWORK",
        "next_boundary_ms_local_clock_claim": target,
        "session_eligible": release._ist_open(target),
        "five_minute_cadence_ms": STEP,
        "production_database_writes": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }


def _operator_pause(folder: Path) -> bool:
    marker = folder / PAUSE_NAME
    if marker.is_symlink():
        raise PermissionError("Symlinked operator pause marker prohibited")
    if not marker.exists():
        return False
    info = marker.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_mode & 0o077):
        raise PermissionError("Invalid operator pause-marker permissions")
    return True


def _check_capacity(folder: Path) -> None:
    disk = os.statvfs(folder)
    if disk.f_bavail * disk.f_frsize < MIN_FREE_BYTES:
        raise OSError("Paper evidence disk below two-gigabyte safety reserve")


def run_private_paper_loop(
    state_dir: str, *,
    public_network_approved: bool = False,
    paper_only_acknowledged: bool = False,
    clock_ms=None,
    sleep=None,
    capture=None,
    stop_requested=None,
    max_cycles: int | None = None,
) -> dict:
    """Runs a single process; never sends client signals.

    Captures are at most once per future boundary. A failed cycle stops the
    process with a create-only operator-visible failure receipt; no backfill.
    A quiet off-session or paused tick is NOT interpreted as NO_SETUP.
    """
    if public_network_approved is not True or paper_only_acknowledged is not True:
        raise PermissionError("Explicit real-network and paper-only approvals required")
    if max_cycles is not None and (
        type(max_cycles) is not int or not 1 <= max_cycles <= 288
    ):
        raise ValueError("Invalid bounded operator cycle count")
    folder = _private_directory(state_dir)
    now = clock_ms if clock_ms is not None else _clock_ms
    sleeper = sleep if sleep is not None else time.sleep
    acquire = capture if capture is not None else capture_one_private_cycle
    interrupted = stop_requested if stop_requested is not None else (lambda: False)
    previous_clock = now()
    attempted = 0
    stored = 0
    last_boundary = None

    while not interrupted():
        t = now()
        if t < previous_clock - 2_000:
            raise RuntimeError("Clock moved backwards; private runner stopped")
        previous_clock = t
        if _operator_pause(folder):
            sleeper(SESSION_RECHECK_SECONDS)
            continue
        upcoming = next_boundary(t)
        if upcoming == last_boundary:
            # A faulty wall clock must not create a duplicate cycle.
            sleeper(SESSION_RECHECK_SECONDS)
            continue
        if not release._ist_open(upcoming):
            sleeper(SESSION_RECHECK_SECONDS)
            continue
        _check_capacity(folder)
        last_boundary = upcoming
        try:
            receipt = acquire(
                str(folder),
                public_network_approved=True,
                paper_only_acknowledged=True,
            )
            if (receipt.get("decision_boundary_ms") != upcoming or
                    receipt.get("status") !=
                    "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND" or
                    receipt.get("market_count") != 6 or
                    receipt.get("client_publication_authorized") is not False or
                    receipt.get("telegram_messages_sent") != 0 or
                    receipt.get("orders_submitted") != 0):
                raise ValueError("Private runner returned unexpected publication or boundary")
            stored += 1
        except Exception as exc:
            # Each failed future boundary is a GAP, not an invented
            # zero-signal or retryable historic decision. Never suppress it.
            failure = {
                "schema": 1,
                "status": "V7_PRIVATE_CAPTURE_FAILED_NO_SIGNAL_OR_SEND",
                "decision_boundary_ms": upcoming,
                "exception_class": type(exc).__name__,
                "error_code": str(exc)[:180],
                "client_publication_authorized": False,
                "telegram_messages_sent": 0,
                "orders_submitted": 0,
            }
            _write_immutable_file(
                folder, folder / f"{GAP_PREFIX}{upcoming}.json",
                (json.dumps(failure, sort_keys=True) + "\n").encode(),
            )
            raise
        attempted += 1
        if max_cycles is not None and attempted >= max_cycles:
            break
    return {
        "status": "V7_PRIVATE_PAPER_SCHEDULER_STOPPED_NO_SEND",
        "completed_cycles": attempted,
        "durably_stored_cycles": stored,
        "production_database_writes": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }


def main():
    parser = argparse.ArgumentParser(
        description="V7 private five-minute PAPER scheduler, no production sends"
    )
    parser.add_argument("--run-private-paper-loop", action="store_true")
    parser.add_argument("--public-network-approved", action="store_true")
    parser.add_argument("--paper-only-acknowledged", action="store_true")
    parser.add_argument("--state-dir")
    parser.add_argument("--max-cycles", type=int)
    args = parser.parse_args()
    if not args.run_private_paper_loop:
        if (args.public_network_approved or args.paper_only_acknowledged or
                args.max_cycles is not None):
            parser.error("Approval/cycle flags require --run-private-paper-loop")
        result = preflight(_clock_ms(), state_dir=args.state_dir)
    else:
        if args.state_dir is None:
            parser.error("Explicit --state-dir mandatory")
        result = run_private_paper_loop(
            args.state_dir,
            public_network_approved=args.public_network_approved,
            paper_only_acknowledged=args.paper_only_acknowledged,
            max_cycles=args.max_cycles,
        )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
