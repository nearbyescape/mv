"""Read/verify exact original HTTP bodies from an early live V7Sonic capture.

No HTTP, trading, Telegram, production database or altered source data.
Checks the local SHA256 of EACH 31 response and computes fieldwise
1m-vs-15m/1h/4h discrepancy details from the first persisted bytes.
No source signatures or independent receipt timestamps are claimed.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.early_live_smoke import FRAMES
from services.t7sonic.forensic_cross_resolution import forensic_compare


def _decode(item):
    if not isinstance(item,dict) or set(item)!={"body_base64","original_body_sha256"}:
        raise ValueError("Malformed raw source item")
    if (not isinstance(item["body_base64"],str) or
            not isinstance(item["original_body_sha256"],str)):
        raise ValueError("Invalid source evidence types")
    try:
        body=base64.b64decode(item["body_base64"],validate=True)
    except (ValueError,base64.binascii.Error):
        raise ValueError("Bad original-source base64")
    if not body or sha256(body).hexdigest()!=item["original_body_sha256"]:
        raise ValueError("Original source body mismatch: reject")
    return body


def replay_original(receipt):
    if (not isinstance(receipt,dict) or receipt.get("schema")!=1 or
            receipt.get("status")!="ORIGINAL_PUBLIC_REST_INPUTS_LOCAL_UNATTESTED" or
            receipt.get("original_public_rest_responses_retained")!=31 or
            receipt.get("client_publication_authorized") is not False or
            receipt.get("telegram_enqueued") is not False or
            receipt.get("orders_submitted") is not False or
            receipt.get("exchange_data_signed") is not False or
            receipt.get("independent_timestamp_verified") is not False or
            receipt.get("markets")!=list(MARKETS)):
        raise ValueError("Not an intact unapproved early live source capture")
    minute=receipt.get("kline_bodies")
    books=receipt.get("quote_bodies")
    times=receipt.get("quote_received_ms_local_clock_claim")
    if (not isinstance(minute,dict) or set(minute)!=set(MARKETS) or
            not isinstance(books,dict) or set(books)!=set(MARKETS) or
            not isinstance(times,dict) or set(times)!=set(MARKETS)):
        raise ValueError("Full six-market source proof required")
    originals={}
    for symbol in MARKETS:
        if not isinstance(minute[symbol],dict) or set(minute[symbol])!=set(FRAMES):
            raise ValueError("One of 24 kline bodies missing")
        originals[symbol]={frame:_decode(minute[symbol][frame]) for frame in FRAMES}
        _decode(books[symbol])
        if type(times[symbol]) is not int:
            raise ValueError("Invalid local quote receipt")
    _decode(receipt.get("exchange_info_body"))
    comparison=forensic_compare(receipt.get("decision_boundary_ms"),originals)
    return {
        "status":"ORIGINAL_HTTP_BYTES_OFFLINE_FIELD_REPLAY_NO_CLIENT_SIGNALS",
        "decision_boundary_ms":receipt["decision_boundary_ms"],
        "original_http_responses_hash_checked":31,
        "exact_reconciliation_passed":comparison["exact_reconciliation_passed"],
        "price_field_discrepancies":comparison["price_field_discrepancies"],
        "volume_field_discrepancies":comparison["volume_field_discrepancies"],
        "markets":comparison["markets"],
        "original_instant_fully_captured":True,
        "independent_exchange_source_attestation":False,
        "client_publication_authorized":False,
        "telegram_messages_sent":0,
        "orders_submitted":0,
    }


def replay_full_original_paper_analysis(receipt):
    """Re-run the unchanged six-market decision engine on ORIGINAL saved bytes.

    The original HTTP bodies and receipt timestamp are verified, then reused
    exactly as they were received on the VPS. This is a delayed offline
    diagnostic, NOT a newly generated live actionable signal. Every field
    remains fail-closed. No network, trading, accounts or Telegram.
    """
    hash_proof=replay_original(receipt)
    boundary=receipt["decision_boundary_ms"]
    source={
        symbol:{
            frame:_decode(receipt["kline_bodies"][symbol][frame])
            for frame in FRAMES
        }
        for symbol in MARKETS
    }
    books={
        symbol:_decode(receipt["quote_bodies"][symbol])
        for symbol in MARKETS
    }
    metadata=_decode(receipt["exchange_info_body"])
    receipts=receipt["quote_received_ms_local_clock_claim"]
    evaluated=receipt.get("recorded_ms_local_clock_claim")
    if type(evaluated) is not int:
        raise ValueError("Saved source evaluation receipt time is mandatory")
    from services.t7sonic.early_live_smoke import analyze
    decision=analyze(boundary,source,books,metadata,receipts,evaluated)
    if (decision["market_count"] != len(MARKETS) or
            decision["client_publication_authorized"] is not False or
            decision["telegram_enqueued"] is not False or
            decision["orders_submitted"] is not False):
        raise ValueError("Unexpected post-replay publication permission")
    return {
        "status":"ORIGINAL_SIX_MARKET_OFFLINE_PAPER_REPLAY_DO_NOT_TRADE",
        "decision_boundary_ms":boundary,
        "original_http_sha256_verified_count":
            hash_proof["original_http_responses_hash_checked"],
        "exact_candle_reconciliation_passed":
            hash_proof["exact_reconciliation_passed"],
        "price_field_discrepancies":hash_proof["price_field_discrepancies"],
        "volume_field_discrepancies":hash_proof["volume_field_discrepancies"],
        "paper_market_count":decision["market_count"],
        "paper_candidate_count":decision["paper_candidate_count"],
        "paper_decisions":decision["decisions"],
        "per_market_quote_ages_ms":{
            symbol:decision["source_proofs"][symbol]["quote_age_ms"]
            for symbol in MARKETS
        },
        "historical_offline_replay_only":True,
        "not_forward_performance_validation":True,
        "original_exchange_bodies_unmodified":True,
        "client_publication_authorized":False,
        "telegram_messages_sent":0,
        "orders_submitted":0,
    }


def _read_private_file(value):
    path=Path(value)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PermissionError("Explicit absolute non-symlink receipt required")
    parent=path.parent.stat()
    info=path.stat()
    if (parent.st_uid!=os.getuid() or parent.st_mode & 0o077 or
            info.st_uid!=os.getuid() or not stat.S_ISREG(info.st_mode) or
            info.st_mode & 0o077):
        raise PermissionError("Owner-private source receipt required")
    if not 32<=info.st_size<=8_000_000:
        raise ValueError("Original-source receipt size exceeds bounds")
    return json.loads(path.read_bytes())


def main():
    parser=argparse.ArgumentParser(
        description="Replay original captured Binance OHLCV; NO NETWORK")
    parser.add_argument("--original-evidence",required=True)
    parser.add_argument("--paper-decisions",action="store_true",
                        help="OFFLINE replay six-market paper logic; never publish")
    args=parser.parse_args()
    receipt=_read_private_file(args.original_evidence)
    proof=(replay_full_original_paper_analysis(receipt)
           if args.paper_decisions else replay_original(receipt))
    print(json.dumps(proof,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
