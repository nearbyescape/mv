"""Phase 2V: offline witness submission manifest for complete six-market cycles.

Zero network or third-party access. The 24 raw-response digests and
pre-outcome model precommit SHA are bound in a canonical immutable
witness *request* to be independently timestamped elsewhere.

IMPORTANT: This does NOT implement RFC3161 or a signature verifier.
No local SHA, unsigned receipt, injected clock time or self-signed
certificate can prove independent real-time capture. A separately
reviewed off-VPS TSA and trust policy is needed before paper certification.
"""
from __future__ import annotations

from hashlib import sha256
import json

from app.research.t7sonic_forward_coverage import (
    GAP_STATUS, WATCH_STATUS, validate_synthetic_packet,
)
from app.research.t7sonic_forward_protocol import FIRST_PREVIOUS_SHA, RECEIPT_MAX_DELAY_MS
from app.research.t7sonic_validation_plan import MARKETS, STRATEGY_SHA
from services.t7sonic.forward_acquisition import request_plan

FRAMES = ("1m", "15m", "1h", "4h")
SOURCE_PROOF_STATUS = "UNATTESTED_TRANSPORT_GEOMETRY_ONLY"
MAX_SOURCES = 24


def _hex64(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64 and
            all(c in "0123456789abcdef" for c in value))


def _canonical(data: dict) -> bytes:
    return json.dumps(
        data, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def assemble_witness_request(
    packet: dict, source_records: dict,
    *, previous_sha256: str = FIRST_PREVIOUS_SHA,
    previous_boundary_ms: int | None = None,
) -> dict:
    """Create an unsigned SHA256 imprint for outside independent witnessing.

    WATCH events require exact 6x4 authenticated-by-parser (but NOT signed)
    source receipt metadata; GAP events deliberately have no source bundle.
    """
    digest, boundary, category = validate_synthetic_packet(
        packet, previous_sha256, previous_boundary_ms
    )
    if (not isinstance(source_records, dict) or set(source_records) !=
            (set(MARKETS) if packet["status"] == WATCH_STATUS else set())):
        raise ValueError("WATCH needs six market sources; GAP must be empty")
    receipts = []
    if packet["status"] == WATCH_STATUS:
        observations = packet["observations"]
        for observation in observations:
            symbol = observation["symbol"]
            group = source_records[symbol]
            if (not isinstance(group, dict) or
                    set(group) != {"feature_source_sha256", "frames"} or
                    not _hex64(group["feature_source_sha256"]) or
                    group["feature_source_sha256"] !=
                    observation["feature_source_sha256"] or
                    not isinstance(group["frames"], dict) or
                    set(group["frames"]) != set(FRAMES)):
                raise ValueError("Missing, extra or different feature-source proof")
            for frame in FRAMES:
                entry = group["frames"][frame]
                if not isinstance(entry, dict):
                    raise ValueError("Missing frame receipt")
                expected_fields = {
                    "status", "symbol", "frame", "boundary_ms",
                    "raw_sha256", "raw_bytes", "expected_url",
                    "receipt_ms_local_clock_unverified", "provenance",
                    "independent_timestamp_verified",
                    "exchange_response_cryptographically_signed",
                    "external_evidence_replication_verified",
                    "trading_authorized",
                }
                if (set(entry) != expected_fields or
                        entry["status"] != SOURCE_PROOF_STATUS or
                        entry["symbol"] != symbol or entry["frame"] != frame or
                        entry["boundary_ms"] != boundary or
                        not _hex64(entry["raw_sha256"]) or
                        type(entry["raw_bytes"]) is not int or
                        not 2 <= entry["raw_bytes"] <= 256_000 or
                        entry["expected_url"] != _expected_url(symbol, frame, boundary) or
                        type(entry["receipt_ms_local_clock_unverified"]) is not int or
                        not boundary <= entry["receipt_ms_local_clock_unverified"] <=
                        boundary + RECEIPT_MAX_DELAY_MS or
                        entry["provenance"] not in (
                            "INJECTED_TEST_RESPONSE",
                            "LOCAL_SYSTEM_CA_TLS_NO_INDEPENDENT_WITNESS"
                        ) or
                        entry["independent_timestamp_verified"] is not False or
                        entry["exchange_response_cryptographically_signed"] is not False or
                        entry["external_evidence_replication_verified"] is not False or
                        entry["trading_authorized"] is not False):
                    raise ValueError("Frame source receipt is invalid or falsely attested")
                receipts.append({
                    "symbol": symbol,
                    "frame": frame,
                    "raw_response_sha256": entry["raw_sha256"],
                    "local_receipt_claim_ms": entry["receipt_ms_local_clock_unverified"],
                    "request_plan_sha256": request_plan(symbol, frame, boundary)[
                        "request_plan_sha256"
                    ],
                })
        if len(receipts) != MAX_SOURCES:
            raise ValueError("Exactly 24 source receipts required")
    elif packet["status"] != GAP_STATUS:
        raise ValueError("Unsupported witness event status")

    body = {
        "schema": 1,
        "status": "WITNESS_REQUEST_PREPARED_NOT_SUBMITTED",
        "candidate_source_revision": STRATEGY_SHA,
        "event_type": category,
        "protocol_sha256": packet["protocol_sha256"],
        "boundary_ms": boundary,
        "latest_allowed_local_receipt_claim_ms": boundary + RECEIPT_MAX_DELAY_MS,
        "precommit_batch_sha256": digest,
        "source_receipts": receipts,
        "source_receipt_count": len(receipts),
        "all_six_markets_accounted_for": True,
        "independently_timestamped": False,
        "external_signature_verified": False,
        "external_archive_replicated": False,
        "trading_authorized": False,
    }
    fingerprint = sha256(_canonical(body)).hexdigest()
    return {
        **body,
        "witness_content_sha256": fingerprint,
        "witness_content_bytes": len(_canonical(body)),
        "witness_imprint_algorithm": "sha256",
        "witness_imprint_hex_for_external_tsa": fingerprint,
        "witness_service_contacted": False,
        "rfc3161_timestamp_token_verified": False,
        "independent_timestamp_trust_status": "NOT_VERIFIED",
    }


def _expected_url(symbol: str, frame: str, boundary_ms: int) -> str:
    from urllib.parse import urlencode
    plan = request_plan(symbol, frame, boundary_ms)
    return ("https://fapi.binance.com/fapi/v1/klines?" +
            urlencode(plan["query"]))


def validate_unsigned_witness_request(manifest: dict) -> dict:
    """Recompute offline imprint; refuse any claim of external certification."""
    if not isinstance(manifest, dict):
        raise ValueError("Expected a witness manifest")
    body = {key: val for key, val in manifest.items() if key not in {
        "witness_content_sha256", "witness_content_bytes",
        "witness_imprint_algorithm", "witness_imprint_hex_for_external_tsa",
        "witness_service_contacted", "rfc3161_timestamp_token_verified",
        "independent_timestamp_trust_status",
    }}
    payload = _canonical(body)
    imprint = sha256(payload).hexdigest()
    if (imprint != manifest.get("witness_content_sha256") or
            imprint != manifest.get("witness_imprint_hex_for_external_tsa") or
            len(payload) != manifest.get("witness_content_bytes") or
            manifest.get("witness_imprint_algorithm") != "sha256" or
            manifest.get("witness_service_contacted") is not False or
            manifest.get("rfc3161_timestamp_token_verified") is not False or
            manifest.get("independent_timestamp_trust_status") != "NOT_VERIFIED" or
            body.get("independently_timestamped") is not False or
            body.get("external_signature_verified") is not False or
            body.get("external_archive_replicated") is not False or
            body.get("trading_authorized") is not False):
        raise ValueError("Altered, noncanonical or falsely certified witness request")
    return {
        "status": "UNSIGNED_WITNESS_REQUEST_INTEGRITY_PASS_NOT_A_TIMESTAMP",
        "witness_imprint_sha256": imprint,
        "cryptographically_verified_external_receipt": False,
        "trusted_paper_observation": False,
        "orders_or_telegram_authorized": False,
    }
