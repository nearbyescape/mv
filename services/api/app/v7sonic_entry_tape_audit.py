"""Offline, immutable original-byte audit of the October 13 V7 entry tape.

No network, no V4 restart, no Telegram, no exchange orders and no writes.
The reference print observations NEVER certify actual client entry fills.
"""
from __future__ import annotations

import argparse
import base64
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from urllib.parse import urlencode

from app.v7sonic_readonly_audit import audit_one_stored_cycle
from services.t7sonic.entry_tape_reference import (
    BOUNDARY, WINDOW_END, SLICE_MS, LIMIT, SYMBOLS,
    decode_slice, score_entry_window,
)
from services.t7sonic.outcome_capture_worker import (
    ORIGINAL_SHA256, SUMMARY_SHA256, BATCH_SHA256, _canonical,
)

MAX_FILE_BYTES = 450_000
MAX_REPORT_BYTES = 160_000

# OUT-OF-BAND manifest from the 2026-10-13 operator's immutable VPS
# output. These MUST NOT be inferred from the stored JSON envelopes;
# doing so would permit tampered raw bytes + matching forged hashes.
PINNED_ORIGINAL_TAPE_BODY_SHA256 = {
    ("SOLUSDT", 0): "78f235f007ae49630978acc1f342507c840323e04d92b1b9ecdd44a30b7ecc21",
    ("SOLUSDT", 1): "def2fafbf72e21a308a335fc85d8f8151ab7820242e9603c738109b59396a702",
    ("SOLUSDT", 2): "39f84732097629da769510420ba12df3debf4c4c99b62c8dd3f5ffd35f3f10e4",
    ("SOLUSDT", 3): "143518d1ae023cbb21577d1e2a92a37e98e8f5ce0c892307d129dd3105924a07",
    ("SOLUSDT", 4): "5a4feab20dbd1d0df60bd070834a96c94e07856835937b06b4b463403b2d22dc",
    ("SOLUSDT", 5): "bff30e2afe74760b08b980848a893d29eb673e8cfe4434116345f9cc8674fe05",
    ("DOGEUSDT", 0): "9271719938f3aadb297aa2b0acbe40de0f447ae7de89109ecc8b8e1fb5fd10ab",
    ("DOGEUSDT", 1): "267842dba9c4c21d05f3360832e9263cd3af30b946b30983840a75670e08b84b",
    ("DOGEUSDT", 2): "6402d64c9b2154c723e86f6011b0601e1778b4a7c51cf014cf8bdde8838ab186",
    ("DOGEUSDT", 3): "e601fb0dcb34df1eb112038cdacd967e8e4d302e7b1b41707d4306a2fbf2ba0a",
    ("DOGEUSDT", 4): "68e56b680235c0513e743bacb0f5c96ab7e256a8fa4c1a85b3153848df8ec312",
    ("DOGEUSDT", 5): "bd7ac23918a2606c2aae60fee10cc35ab631f43e95fd017f3121545db3519574",
}


def _safe_folder(path):
    folder = Path(path)
    if not folder.is_absolute() or folder.is_symlink() or not folder.is_dir():
        raise PermissionError("Existing absolute non-symlink private folder required")
    mode = folder.stat()
    if (mode.st_uid != os.getuid() or not stat.S_ISDIR(mode.st_mode)
            or mode.st_mode & 0o077):
        raise PermissionError("Owner-only original evidence folder required")
    return folder


def _read(folder: Path, name: str, max_bytes=MAX_FILE_BYTES):
    target = folder / name
    if (target.parent != folder or target.is_symlink() or
            not target.is_file() or
            not stat.S_ISREG(target.stat().st_mode) or
            not 1 <= target.stat().st_size <= max_bytes):
        raise PermissionError("Original regular bounded evidence file required")
    return target.read_bytes()


def audit_saved_entry_tape(state_dir, evidence_dir):
    evidence = _safe_folder(evidence_dir)
    claim_data = _read(
        evidence, f"v7sonic-entry-tape-claim-{BOUNDARY}.json", max_bytes=10000,
    )
    claim = json.loads(claim_data)
    if (claim.get("schema") != 1 or
            claim.get("status") != "PRIVATE_ENTRY_TAPE_REQUEST_CLAIMED_NO_SEND" or
            claim.get("boundary_ms") != BOUNDARY or
            claim.get("original_source_sha256") != ORIGINAL_SHA256 or
            claim.get("client_publication_authorized") is not False or
            claim.get("orders_submitted") != 0 or
            not isinstance(claim.get("recorded_paper_decision_ms_local_unattested"), int)):
        raise ValueError("Original public research claim fails provenance checks")
    if (evidence / f"v7sonic-entry-tape-incomplete-{BOUNDARY}.json").exists():
        raise ValueError("Original collection declared INCOMPLETE, cannot certify it")

    source = audit_one_stored_cycle(
        state_dir, boundary_ms=BOUNDARY,
        summary_sha256=SUMMARY_SHA256, original_sha256=ORIGINAL_SHA256,
        batch_sha256=BATCH_SHA256,
    )
    journal = source["decision_paper_journal_inserted_ms_local_unattested"]
    candidates = source["candidates"]
    if (source["status"] !=
            "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS" or
            [rec["symbol"] for rec in candidates] != list(SYMBOLS) or
            not BOUNDARY <= journal < WINDOW_END or
            claim["recorded_paper_decision_ms_local_unattested"] != journal):
        raise ValueError("Original paper journal and entry-tape claim mismatch")

    expected_manifest, observations, original_file_hashes = [], [], []
    for candidate in candidates:
        chunks = []
        symbol = candidate["symbol"]
        for idx in range(6):
            start = BOUNDARY + idx * SLICE_MS
            end = start + SLICE_MS
            name = f"v7sonic-entry-tape-original-{BOUNDARY}-{symbol}-{idx}.json"
            payload = _read(evidence, name)
            packet = json.loads(payload)
            expected_url = "https://fapi.binance.com/fapi/v1/aggTrades?" + urlencode({
                "symbol": symbol, "startTime": start, "endTime": end - 1,
                "limit": LIMIT,
            })
            if (packet.get("schema") != 1 or
                    packet.get("source") !=
                    "PUBLIC_BINANCE_USDM_COMPRESSED_AGGREGATE_TRADES" or
                    packet.get("url") != expected_url or
                    packet.get("client_publication_authorized") is not False or
                    packet.get("orders_submitted") != 0 or
                    not isinstance(packet.get("original_body_base64"), str) or
                    not isinstance(packet.get("original_body_sha256"), str)):
                raise ValueError("Original aggregate-trades HTTP request provenance mismatch")
            try:
                raw = base64.b64decode(packet["original_body_base64"], validate=True)
            except (ValueError, TypeError):
                raise ValueError("Original Binance body was not valid base64") from None
            digest = sha256(raw).hexdigest()
            if (digest != packet["original_body_sha256"] or
                    digest != PINNED_ORIGINAL_TAPE_BODY_SHA256[(symbol, idx)]):
                raise ValueError(
                    "Original aggregate-trades response SHA256 mismatch "
                    "against independently pinned operator manifest"
                )
            chunks.append(decode_slice(raw, start_ms=start, end_ms=end))
            expected_manifest.append({
                "symbol": symbol, "slice": idx, "original_body_sha256": digest,
            })
            original_file_hashes.append({
                "symbol": symbol, "slice": idx,
                "saved_evidence_envelope_sha256": sha256(payload).hexdigest(),
                "http_body_sha256": digest,
            })
        observations.append(score_entry_window(
            candidate, journal_inserted_ms=journal, trade_slices=chunks,
        ))

    report_raw = _read(
        evidence, f"v7sonic-entry-tape-report-{BOUNDARY}.json",
        max_bytes=MAX_REPORT_BYTES,
    )
    report = json.loads(report_raw)
    if (report.get("schema") != 1 or
            report.get("status") !=
            "TWO_HISTORICAL_30S_TRADE_PRINT_CHECKS_NOT_ORDER_FILLS" or
            report.get("decision_boundary_ms") != BOUNDARY or
            report.get("decision_journal_inserted_ms_local_unattested") != journal or
            report.get("original_decision_http_sha256") != ORIGINAL_SHA256 or
            report.get("original_decision_batch_sha256") != BATCH_SHA256 or
            report.get("original_http_response_count_saved") != 12 or
            report.get("response_sha256_manifest") != expected_manifest or
            report.get("observations") != observations or
            report.get("source_independently_authenticated") is not False or
            report.get("actual_quotes_or_client_order_fills_verified") is not False or
            report.get("client_publication_authorized") is not False or
            report.get("telegram_messages_sent") != 0 or
            report.get("orders_submitted") != 0):
        raise ValueError("Historical entry-tape reported results differ from saved sources")

    return {
        "status": "ORIGINAL_12_RESPONSE_30S_TAPE_REPLAY_AUDIT_PASS_NO_FILLS",
        "boundary_ms": BOUNDARY,
        "journal_inserted_ms_local_unattested": journal,
        "original_source_body_sha256": ORIGINAL_SHA256,
        "original_batch_sha256": BATCH_SHA256,
        "saved_tape_report_sha256": sha256(report_raw).hexdigest(),
        "tape_original_body_count_reverified": len(expected_manifest),
        "saved_evidence_file_hashes": original_file_hashes,
        "replayed_observations": observations,
        "client_publication_authorized": False,
        "entry_fills_verified": 0,
        "orders_submitted": 0,
        "historical_only_do_not_trade": True,
    }


def main():
    parser = argparse.ArgumentParser(description="NO NETWORK, NO SEND historical tape re-audit")
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--evidence-dir", required=True)
    a = parser.parse_args()
    print(json.dumps(audit_saved_entry_tape(
        a.state_dir, a.evidence_dir
    ), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
