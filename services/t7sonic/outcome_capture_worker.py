"""Operator-approved HISTORICAL (120m) Binance market-data outcome probe.

This is NOT a live trade, a publisher, a private-account query, or a proof
that the 30-second conditional entry was filled. Requires two new public
Binance klines HTTP GETs, one for each previously pinned paper candidate.
Saves original received bytes BEFORE evaluating price outcomes.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import time
from urllib.parse import urlencode

from app.v7sonic_readonly_audit import audit_one_stored_cycle
from services.t7sonic.early_live_smoke import _get, _write_immutable_file
from services.t7sonic.outcome_reference import (
    WINDOW_BARS, STEP_MS, full_post_decision_minute_bars,
    score_reference_path,
)

BOUNDARY = 1791862500000  # frozen 13 Oct 2026 09:05 IST, real 31-body capture
ORIGINAL_SHA256 = "ecd05a021de07a853157b143d882ac472a42e85bfe72826c87c3cee5520caadb"
SUMMARY_SHA256 = "03d6d4156de61b145156a2d3004ae46e26a80be6f5b79d18d6fa7209a743b2ab"
BATCH_SHA256 = "0cc8e8c97aaee3caad24269c78918aa7d5c64571cd2ecb3318f42907f44d2e11"


def _private_outcome_dir(path: str | Path) -> Path:
    p = Path(path)
    if p.is_symlink() or not p.is_absolute() or not p.is_dir():
        raise PermissionError("Existing standalone private outcome directory required")
    s = p.stat()
    if (not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid()
            or s.st_mode & 0o077):
        raise PermissionError("Private outcome directory must be owned, 0700")
    return p


def _canonical(obj: dict) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def historic_one_shot_outcome(
    state_dir: str, outcome_dir: str, *,
    public_network_approved: bool = False,
    paper_only_acknowledged: bool = False,
    clock_ms=None,
    getter=None,
) -> dict:
    if public_network_approved is not True or paper_only_acknowledged is not True:
        raise PermissionError("Public market-data and paper-only acknowledgments required")
    now = clock_ms if clock_ms is not None else lambda: time.time_ns() // 1_000_000
    getter = getter if getter is not None else _get
    folder = _private_outcome_dir(outcome_dir)
    # The last fully closed 1m candle runs 11:05:00-11:05:59 IST.
    if now() < BOUNDARY + (WINDOW_BARS + 1) * STEP_MS:
        raise ValueError("120 fully closed 1m bars not available; refuse early outcome claim")

    original = audit_one_stored_cycle(
        state_dir,
        boundary_ms=BOUNDARY, summary_sha256=SUMMARY_SHA256,
        original_sha256=ORIGINAL_SHA256, batch_sha256=BATCH_SHA256,
    )
    candidates = original["candidates"]
    if (original["status"] !=
            "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS" or
            len(candidates) != 2 or
            [x["symbol"] for x in candidates] != ["SOLUSDT", "DOGEUSDT"] or
            any(x["direction"] != "LONG" for x in candidates)):
        raise ValueError("Unexpected changed historical original candidate evidence")

    claim_path = folder / f"v7sonic-outcome-claim-{BOUNDARY}.json"
    _write_immutable_file(folder, claim_path, _canonical({
        "status": "PRIVATE_HISTORICAL_OUTCOME_CAPTURE_CLAIMED",
        "boundary_ms": BOUNDARY,
        "original_source_sha256": ORIGINAL_SHA256,
        "original_six_market_batch_sha256": BATCH_SHA256,
        "not_live_trading": True,
        "client_publication_authorized": False,
        "orders_submitted": 0,
    }))
    collected = {}
    try:
        for candidate in candidates:
            sym = candidate["symbol"]
            start = BOUNDARY + STEP_MS
            last = BOUNDARY + WINDOW_BARS * STEP_MS
            url = ("https://fapi.binance.com/fapi/v1/klines?" + urlencode({
                "symbol": sym, "interval": "1m", "startTime": start,
                "endTime": last + STEP_MS - 1, "limit": WINDOW_BARS,
            }))
            data, received, elapsed = getter(url, 256_000)
            if not isinstance(data, bytes):
                raise ValueError("Binance outcome GET must return unmodified bytes")
            collected[sym] = {
                "http_path_and_query": url,
                "original_body_base64": base64.b64encode(data).decode("ascii"),
                "original_body_sha256": sha256(data).hexdigest(),
                "local_receipt_ms_unattested": received,
                "elapsed_ms_unattested": elapsed,
            }
    except Exception as exc:
        _write_immutable_file(folder,
            folder / f"v7sonic-outcome-acquisition-gap-{BOUNDARY}.json",
            _canonical({
                "status": "INCOMPLETE_HISTORICAL_OUTCOME_GET_NOT_SCORED",
                "boundary_ms": BOUNDARY, "exception_class": type(exc).__name__,
                "response_count_complete": 0,
                "client_publication_authorized": False,
                "orders_submitted": 0,
            }))
        raise

    packet = {
        "schema": 1,
        "status": "ORIGINAL_TWO_PUBLIC_FUTURES_KLINE_RESPONSES_UNATTESTED",
        "boundary_ms": BOUNDARY,
        "observed_ms_local_clock_unattested": now(),
        "original_31_body_sha256": ORIGINAL_SHA256,
        "original_six_market_batch_sha256": BATCH_SHA256,
        "response_count": 2,
        "outcome_bodies": collected,
        "client_publication_authorized": False,
        "orders_submitted": 0,
    }
    original_path = folder / f"v7sonic-outcome-original-http-{BOUNDARY}.json"
    original_blob = _canonical(packet)
    _write_immutable_file(folder, original_path, original_blob)

    try:
        results = []
        for candidate in candidates:
            sym = candidate["symbol"]
            raw = base64.b64decode(collected[sym]["original_body_base64"],
                                   validate=True)
            if sha256(raw).hexdigest() != collected[sym]["original_body_sha256"]:
                raise ValueError("Outcome HTTP source hash changed")
            bars = full_post_decision_minute_bars(sym, BOUNDARY, raw)
            results.append(score_reference_path(candidate, bars))
    except Exception as exc:
        _write_immutable_file(folder,
            folder / f"v7sonic-outcome-analysis-rejected-{BOUNDARY}.json",
            _canonical({
                "status": "HISTORICAL_OUTCOME_SOURCE_REJECTED_NOT_SCORED",
                "exception_class": type(exc).__name__,
                "original_outcome_http_sha256": sha256(original_blob).hexdigest(),
                "client_publication_authorized": False,
                "orders_submitted": 0,
            }))
        raise

    report = {
        "schema": 1,
        "status": "TWO_HISTORICAL_PAPER_OUTCOMES_REFERENCE_ONLY_NOT_EXECUTIONS",
        "decision_boundary_ms": BOUNDARY,
        "original_decision_http_sha256": ORIGINAL_SHA256,
        "original_decision_batch_sha256": BATCH_SHA256,
        "original_outcome_http_sha256": sha256(original_blob).hexdigest(),
        "market_count": 2,
        "reference_results": results,
        "entry_fills_proven": 0,
        "realized_net_pnl_verified": False,
        "original_exchange_price_source_independently_attested": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }
    _write_immutable_file(folder,
        folder / f"v7sonic-outcome-reference-{BOUNDARY}.json",
        _canonical(report))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="PRIVATE post-signal paper outcomes; NO SEND")
    parser.add_argument("--capture-once", action="store_true")
    parser.add_argument("--public-network-approved", action="store_true")
    parser.add_argument("--paper-only-acknowledged", action="store_true")
    parser.add_argument("--state-dir")
    parser.add_argument("--outcome-dir")
    args = parser.parse_args()
    if not args.capture_once:
        if (args.public_network_approved or args.paper_only_acknowledged or
                args.state_dir or args.outcome_dir):
            parser.error("Capture parameters require --capture-once")
        print(json.dumps({
            "status": "OFFLINE_HISTORICAL_OUTCOME_PREFLIGHT_NO_NETWORK",
            "clients_notified": 0, "orders_submitted": 0,
        }, sort_keys=True))
        return
    if not args.state_dir or not args.outcome_dir:
        parser.error("Both explicit private directories required")
    print(json.dumps(historic_one_shot_outcome(
        args.state_dir, args.outcome_dir,
        public_network_approved=args.public_network_approved,
        paper_only_acknowledged=args.paper_only_acknowledged,
    ), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
