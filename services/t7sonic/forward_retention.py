"""Phase 2Y: portable OFFLINE evidence bundle; no off-server replication.

Freeze a complete six-market WATCH decision, its unsigned witness request
and all 24 *raw* source-response bodies into a canonical ZIP_STORED archive.
GAP decisions have NO raw source bodies; they are never NO_WATCH.

A local ZIP/SHA digest is NOT off-server retention, independent timing,
exchange provenance, Binance authenticity, or paper-trial certification.
No transport, cloud SDK, network, signing key, scheduler, model, Telegram
or order API exists here.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import re
from zipfile import BadZipFile, ZipFile, ZipInfo, ZIP_STORED

from app.research.t7sonic_forward_coverage import (
    GAP_STATUS, WATCH_STATUS, validate_synthetic_packet,
)
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_witness import (
    FRAMES, validate_unsigned_witness_request,
)

MAX_BLOB_BYTES = 256_000
MAX_ARCHIVE_BYTES = len(MARKETS) * len(FRAMES) * MAX_BLOB_BYTES + 160_000
CANONICAL_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
PACKET_FILE = "decision.json"
WITNESS_FILE = "unsigned-witness.json"


def _canonical(item: dict) -> bytes:
    return json.dumps(
        item, separators=(",", ":"), sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def _receipt_entries(packet: dict, witness: dict) -> list[dict]:
    # Verify the contained packet's self-consistency. Its previous-link
    # existence still needs an external complete journal audit.
    digest, boundary, kind = validate_synthetic_packet(
        packet, packet.get("previous_batch_sha256"),
        packet.get("previous_boundary_ms"),
    )
    validate_unsigned_witness_request(witness)
    expected_kind = (
        "WATCH_CYCLE_COMPLETE" if packet["status"] == WATCH_STATUS
        else "MISSING_DATA_CYCLE" if packet["status"] == GAP_STATUS else None
    )
    if (expected_kind != kind or
            witness.get("event_type") != expected_kind or
            witness.get("precommit_batch_sha256") != digest or
            witness.get("boundary_ms") != boundary or
            witness.get("protocol_sha256") != packet.get("protocol_sha256") or
            witness.get("all_six_markets_accounted_for") is not True):
        raise ValueError("Evidence witness/decision binding mismatch")
    receipts = witness.get("source_receipts")
    if not isinstance(receipts, list):
        raise ValueError("Source evidence list must be explicit")
    expected_pairs = [
        (symbol, frame) for symbol in MARKETS for frame in FRAMES
    ] if kind == "WATCH_CYCLE_COMPLETE" else []
    actual_pairs = []
    for entry in receipts:
        if (not isinstance(entry, dict) or
                set(entry) != {
                    "symbol", "frame", "raw_response_sha256",
                    "local_receipt_claim_ms", "request_plan_sha256"
                } or
                not isinstance(entry["symbol"], str) or
                not isinstance(entry["frame"], str)):
            raise ValueError("Source receipt schema invalid")
        actual_pairs.append((entry["symbol"], entry["frame"]))
        digest_text = entry["raw_response_sha256"]
        if (not isinstance(digest_text, str) or
                not re.fullmatch(r"[0-9a-f]{64}", digest_text)):
            raise ValueError("Malformed raw response SHA")
    if (actual_pairs != expected_pairs or
            witness.get("source_receipt_count") != len(expected_pairs)):
        raise ValueError("Missing, reordered or extra source frames")
    return receipts


def _payloads(packet: dict, witness: dict, raw_sources: dict) -> dict[str, bytes]:
    receipts = _receipt_entries(packet, witness)
    expected_markets = set(MARKETS) if receipts else set()
    if not isinstance(raw_sources, dict) or set(raw_sources) != expected_markets:
        raise ValueError("Exact all-market source payloads required")
    expected_frames = set(FRAMES)
    payloads = {
        PACKET_FILE: _canonical(packet),
        WITNESS_FILE: _canonical(witness),
    }
    for entry in receipts:
        symbol, frame = entry["symbol"], entry["frame"]
        group = raw_sources[symbol]
        if not isinstance(group, dict) or set(group) != expected_frames:
            raise ValueError("Incomplete raw source frames for market")
        raw = group[frame]
        if (not isinstance(raw, bytes) or
                not 2 <= len(raw) <= MAX_BLOB_BYTES or
                sha256(raw).hexdigest() != entry["raw_response_sha256"]):
            raise ValueError("Raw exchange body missing, altered or too large")
        payloads[f"source/{symbol}/{frame}.bin"] = raw
    if len(payloads) != 2+len(receipts):
        raise ValueError("Evidence manifest/objects incomplete")
    return payloads


def _zipinfo(name: str) -> ZipInfo:
    item = ZipInfo(filename=name, date_time=CANONICAL_TIMESTAMP)
    item.compress_type = ZIP_STORED
    item.create_system = 3
    item.external_attr = 0o600 << 16
    return item


def make_offline_bundle(packet: dict, witness: dict, raw_sources: dict) -> bytes:
    """Deterministic portable bundle; caller must not call it real remote proof."""
    contents = _payloads(packet, witness, raw_sources)
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_STORED, allowZip64=False) as output:
        for path, raw in contents.items():
            output.writestr(_zipinfo(path), raw)
    blob = stream.getvalue()
    if len(blob) > MAX_ARCHIVE_BYTES:
        raise ValueError("Oversized offline bundle")
    return blob


def inspect_offline_bundle(blob: bytes) -> dict:
    """Byte-for-byte verify every member; zero writes/network and no extraction."""
    if not isinstance(blob, bytes) or not 100 <= len(blob) <= MAX_ARCHIVE_BYTES:
        raise ValueError("Invalid or unbounded portable evidence archive")
    try:
        with ZipFile(BytesIO(blob), "r") as archive:
            members = archive.infolist()
            names = [i.filename for i in members]
            if len(set(names)) != len(names) or len(names) < 2 or len(names) > 26:
                raise ValueError("Duplicate or excessive archive members")
            if names[:2] != [PACKET_FILE, WITNESS_FILE]:
                raise ValueError("Noncanonical evidence manifest order")
            if any(
                i.compress_type != ZIP_STORED or
                i.file_size > (
                    65_536 if i.filename in (PACKET_FILE, WITNESS_FILE)
                    else MAX_BLOB_BYTES
                ) or (i.flag_bits & 0x1)
                for i in members
            ):
                raise ValueError("Unsafe compression or oversized source member")
            # Bound the sum before any reads to prevent archive memory abuse.
            if sum(i.file_size for i in members) > MAX_ARCHIVE_BYTES:
                raise ValueError("Oversize declared archive payload")
            packet_bytes = archive.read(PACKET_FILE)
            witness_bytes = archive.read(WITNESS_FILE)
            packet = json.loads(packet_bytes)
            witness = json.loads(witness_bytes)
            if (_canonical(packet) != packet_bytes or
                    _canonical(witness) != witness_bytes):
                raise ValueError("Noncanonical serialized evidence data")
            receipts = _receipt_entries(packet, witness)
            expected = (
                [PACKET_FILE, WITNESS_FILE] +
                [f"source/{e['symbol']}/{e['frame']}.bin" for e in receipts]
            )
            if names != expected:
                raise ValueError("Missing, extra or reordered archive data objects")
            raw = {sym: {} for sym in MARKETS} if receipts else {}
            for entry in receipts:
                sym, frame = entry["symbol"], entry["frame"]
                raw[sym][frame] = archive.read(f"source/{sym}/{frame}.bin")
            _payloads(packet, witness, raw)
    except (OSError, EOFError, KeyError, BadZipFile, RuntimeError, json.JSONDecodeError) as exc:
        raise ValueError("Corrupt offline evidence archive") from exc
    return {
        "status": "OFFLINE_BUNDLE_INTEGRITY_PASS_NOT_REMOTE_EVIDENCE",
        "archive_sha256": sha256(blob).hexdigest(),
        "precommit_sha256": packet["batch_sha256"],
        "witness_imprint_sha256": witness["witness_content_sha256"],
        "source_response_count": len(receipts),
        "gap_record": len(receipts) == 0,
        "independent_timestamp_verified": False,
        "remote_storage_verified": False,
        "external_witness_approved": False,
        "paper_study_certified": False,
        "trading_authorized": False,
    }
