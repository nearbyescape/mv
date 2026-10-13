"""Explicitly approved one-shot public Binance 30s trade-print inspection.

NOT a test of whether an unsent client order filled. Twelve bounded
5-second historical compressed trade-list GETs; immutable per-response
bytes retained before scoring. Source/DB original mounted read-only.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from app.v7sonic_readonly_audit import audit_one_stored_cycle
from services.t7sonic.early_live_smoke import _get, _write_immutable_file
from services.t7sonic.entry_tape_reference import (
    BOUNDARY, WINDOW_END, SLICE_MS, SYMBOLS,
    LIMIT, decode_slice, score_entry_window,
)
from services.t7sonic.outcome_capture_worker import (
    ORIGINAL_SHA256, SUMMARY_SHA256, BATCH_SHA256,
    _private_outcome_dir, _canonical,
)

_MAX_SOURCE_AGE_MS = 40 * 60 * 60 * 1000


def capture_entry_tape(
    state_dir: str, output_dir: str, *,
    public_network_approved: bool = False,
    paper_only_acknowledged: bool = False,
    clock_ms=None, getter=None,
) -> dict:
    if public_network_approved is not True or paper_only_acknowledged is not True:
        raise PermissionError("Public-data research and no-client acknowledgments required")
    now = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000
    get = getter if getter is not None else _get
    t = now()
    if not WINDOW_END + 1000 <= t < BOUNDARY + _MAX_SOURCE_AGE_MS:
        raise ValueError("Entry tape is not yet closed or outside 40h API retention guard")
    folder = _private_outcome_dir(output_dir)
    audited = audit_one_stored_cycle(
        state_dir, boundary_ms=BOUNDARY, original_sha256=ORIGINAL_SHA256,
        summary_sha256=SUMMARY_SHA256, batch_sha256=BATCH_SHA256,
    )
    candidates = audited["candidates"]
    decision_written = audited["decision_paper_journal_inserted_ms_local_unattested"]
    if (audited["status"] !=
            "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS" or
            [x["symbol"] for x in candidates] != list(SYMBOLS) or
            any(x.get("direction") != "LONG" for x in candidates) or
            not BOUNDARY <= decision_written < WINDOW_END):
        raise ValueError("Unexpected source decisions or no valid post-decision clock")

    _write_immutable_file(
        folder, folder / f"v7sonic-entry-tape-claim-{BOUNDARY}.json",
        _canonical({
            "schema": 1,
            "status": "PRIVATE_ENTRY_TAPE_REQUEST_CLAIMED_NO_SEND",
            "boundary_ms": BOUNDARY,
            "recorded_paper_decision_ms_local_unattested": decision_written,
            "original_source_sha256": ORIGINAL_SHA256,
            "client_publication_authorized": False, "orders_submitted": 0,
        })
    )
    results = []
    manifest = []
    try:
        for candidate in candidates:
            slices = []
            for idx in range(6):
                start = BOUNDARY + idx * SLICE_MS
                end = start + SLICE_MS
                url = "https://fapi.binance.com/fapi/v1/aggTrades?" + urlencode({
                    "symbol": candidate["symbol"], "startTime": start,
                    "endTime": end - 1, "limit": LIMIT,
                })
                raw, receipt_ms, elapsed_ms = get(url, 256_000)
                if not isinstance(raw, bytes) or not raw:
                    raise ValueError("Source must provide original nonempty bytes")
                digest = sha256(raw).hexdigest()
                # Every ORIGINAL response is saved BEFORE parsing or scoring.
                _write_immutable_file(
                    folder,
                    folder / (
                        f"v7sonic-entry-tape-original-{BOUNDARY}-"
                        f"{candidate['symbol']}-{idx}.json"
                    ),
                    _canonical({
                        "schema": 1,
                        "source": "PUBLIC_BINANCE_USDM_COMPRESSED_AGGREGATE_TRADES",
                        "url": url,
                        "original_body_base64": base64.b64encode(raw).decode("ascii"),
                        "original_body_sha256": digest,
                        "received_ms_local_unattested": receipt_ms,
                        "elapsed_ms_local_unattested": elapsed_ms,
                        "client_publication_authorized": False,
                        "orders_submitted": 0,
                    }),
                )
                manifest.append({
                    "symbol": candidate["symbol"], "slice": idx,
                    "original_body_sha256": digest,
                })
                slices.append(decode_slice(
                    raw, start_ms=start, end_ms=end
                ))
            results.append(score_entry_window(
                candidate, journal_inserted_ms=decision_written,
                trade_slices=slices,
            ))
    except Exception as exc:
        _write_immutable_file(
            folder,
            folder / f"v7sonic-entry-tape-incomplete-{BOUNDARY}.json",
            _canonical({
                "schema": 1,
                "status": "INCOMPLETE_OR_INVALID_ENTRY_TAPE_NO_CONCLUSION",
                "exception_class": type(exc).__name__,
                "original_response_slices_retained": len(manifest),
                "client_publication_authorized": False,
                "orders_submitted": 0,
            }),
        )
        raise

    report = {
        "schema": 1,
        "status": "TWO_HISTORICAL_30S_TRADE_PRINT_CHECKS_NOT_ORDER_FILLS",
        "decision_boundary_ms": BOUNDARY,
        "decision_journal_inserted_ms_local_unattested": decision_written,
        "original_decision_http_sha256": ORIGINAL_SHA256,
        "original_decision_batch_sha256": BATCH_SHA256,
        "original_http_response_count_saved": len(manifest),
        "response_sha256_manifest": manifest,
        "observations": results,
        "source_independently_authenticated": False,
        "actual_quotes_or_client_order_fills_verified": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }
    _write_immutable_file(
        folder, folder / f"v7sonic-entry-tape-report-{BOUNDARY}.json",
        _canonical(report),
    )
    return report


def main() -> None:
    p = argparse.ArgumentParser(description="Paper-only 30s compressed trade print check")
    p.add_argument("--capture-once", action="store_true")
    p.add_argument("--public-network-approved", action="store_true")
    p.add_argument("--paper-only-acknowledged", action="store_true")
    p.add_argument("--state-dir")
    p.add_argument("--output-dir")
    a = p.parse_args()
    if not a.capture_once:
        if (a.public_network_approved or a.paper_only_acknowledged or
                a.state_dir or a.output_dir):
            p.error("Capture parameters require --capture-once")
        print(json.dumps({"status": "ENTRY_TAPE_NO_NETWORK_DEFAULT",
                          "client_publication_authorized": False,
                          "orders_submitted": 0}, sort_keys=True))
        return
    if not a.state_dir or not a.output_dir:
        p.error("Explicit paper state and new evidence folder required")
    print(json.dumps(
        capture_entry_tape(
            a.state_dir, a.output_dir,
            public_network_approved=a.public_network_approved,
            paper_only_acknowledged=a.paper_only_acknowledged,
        ), indent=2, sort_keys=True,
    ))


if __name__ == "__main__":
    main()
