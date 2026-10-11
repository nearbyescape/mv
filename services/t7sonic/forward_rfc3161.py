"""Phase 2W: offline RFC3161 response validation against a pinned TSA root.

Pure offline OpenSSL CLI invocation, NO network, no TSA submission, no order
or Telegram code. A response is only useful after an independently selected
TSA/root/certificate policy and external source-retention agreement.

A cryptographically valid time token is NOT itself evidence of genuine
Binance price data, independent TSA governance, a complete observation
schedule, or profitable trades. Synthetic self-signed test TSAs are never
admissible as real independent witness evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import os
import re
import subprocess
import tempfile

from app.research.t7sonic_forward_protocol import RECEIPT_MAX_DELAY_MS
from services.t7sonic.forward_witness import validate_unsigned_witness_request

MAX_QUERY_BYTES = 4_096
MAX_TOKEN_BYTES = 65_536
MAX_CA_BYTES = 32_768
MAX_PROCESS_SECONDS = 10
_POLICY_RE = re.compile(r"(?:[0-9]+\.){2,12}[0-9]+\Z")
_TIMESTAMP_RE = re.compile(
    r"^Time stamp:\s*([A-Z][a-z]{2}\s+\d{1,2}\s+"
    r"\d{2}:\d{2}:\d{2}\s+\d{4}\s+GMT)\s*$",
    flags=re.MULTILINE,
)


def _hex64(text: object) -> bool:
    return (isinstance(text, str) and len(text) == 64 and
            all(c in "0123456789abcdef" for c in text))


def _openssl(*args: str) -> str:
    """Bounded, shell-free OpenSSL process with no proxy/network functionality."""
    cmd = ("openssl", "ts", *args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, check=False,
            timeout=MAX_PROCESS_SECONDS,
            env={"PATH": os.defpath, "OPENSSL_CONF": "/dev/null"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("OpenSSL timestamp command unavailable or timed out") from exc
    if result.returncode != 0 or len(result.stdout) > 128_000:
        raise ValueError("Timestamp query/signature/chain verification failed")
    return result.stdout.decode("utf-8", "strict")


def _read_imprint_from_query_dump(text: str) -> str:
    """Extract SHA-256 query imprint from the printable RFC3161 query dump."""
    match = re.search(
        r"(?m)^Message data:\s*\n"
        r"((?:\s*[0-9a-fA-F]{4}\s+-\s+[^\n]+\n){1,4})",
        text,
    )
    if match is None:
        raise ValueError("Cannot authenticate query digest mapping")
    chunks = []
    for line in match.group(1).splitlines():
        data = line.split(" - ", 1)
        if len(data) != 2:
            raise ValueError("Invalid RFC3161 query digest display")
        left = data[1].split("   ", 1)[0]
        chunks += re.findall(
            r"(?<![0-9a-fA-F])[0-9a-fA-F]{2}(?![0-9a-fA-F])",
            left,
        )
    value = "".join(chunks).lower()
    if not _hex64(value):
        raise ValueError("Query is not an exact SHA-256 imprint")
    return value


def make_unsigned_rfc3161_query(manifest: dict) -> bytes:
    """Generate locally a nonce-bound SHA256 query; NOT timestamp evidence."""
    validate_unsigned_witness_request(manifest)
    digest = manifest["witness_imprint_hex_for_external_tsa"]
    with tempfile.TemporaryDirectory(prefix="t7sonic-ts-query-") as tmp:
        query = Path(tmp) / "request.tsq"
        _openssl("-query", "-digest", digest, "-sha256", "-cert",
                 "-out", str(query))
        data = query.read_bytes()
        if not 16 <= len(data) <= MAX_QUERY_BYTES:
            raise ValueError("Invalid RFC3161 query length")
        described = _openssl("-query", "-in", str(query), "-text")
        if _read_imprint_from_query_dump(described) != digest:
            raise ValueError("RFC3161 query digest mismatch")
        if "Nonce:" not in described or "Certificate required: yes" not in described:
            raise ValueError("Nonce and TSA certificate request mandatory")
        return data


def verify_offline_rfc3161_response(
    manifest: dict, query_der: bytes, response_der: bytes,
    trust_anchor_pem: bytes, *,
    approved_trust_anchor_sha256: str,
    approved_policy_oid: str,
) -> dict:
    """Verify query/imprint/nonce, signed chain/policy, then deadline.

    No TSA service is contacted. The externally pinned trust-anchor digest
    is a procedural *input* and needs prior independent human approval.
    """
    validate_unsigned_witness_request(manifest)
    if (not _hex64(approved_trust_anchor_sha256) or
            not isinstance(trust_anchor_pem, bytes) or
            not 1 <= len(trust_anchor_pem) <= MAX_CA_BYTES or
            sha256(trust_anchor_pem).hexdigest() != approved_trust_anchor_sha256):
        raise PermissionError("Trusted TSA root must match preapproved SHA-256")
    if not isinstance(approved_policy_oid, str) or not _POLICY_RE.fullmatch(approved_policy_oid):
        raise PermissionError("Explicit frozen TSA policy OID required")
    if (not isinstance(query_der, bytes) or
            not 16 <= len(query_der) <= MAX_QUERY_BYTES or
            not isinstance(response_der, bytes) or
            not 32 <= len(response_der) <= MAX_TOKEN_BYTES):
        raise ValueError("Missing or unbounded RFC3161 query/response bytes")
    with tempfile.TemporaryDirectory(prefix="t7sonic-ts-offline-") as tmp:
        path = Path(tmp)
        q, r, ca = (
            path / "query.tsq", path / "response.tsr", path / "tsa-ca.pem"
        )
        for file, data in ((q, query_der), (r, response_der), (ca, trust_anchor_pem)):
            file.write_bytes(data)
            file.chmod(0o600)

        query_text = _openssl("-query", "-in", str(q), "-text")
        if _read_imprint_from_query_dump(query_text) != manifest["witness_imprint_hex_for_external_tsa"]:
            raise ValueError("RFC3161 query does not bind this 24-source precommit")
        if "Nonce:" not in query_text or "Certificate required: yes" not in query_text:
            raise ValueError("RFC3161 query missing required nonce/cert flag")

        verification = _openssl(
            "-verify", "-queryfile", str(q),
            "-in", str(r), "-CAfile", str(ca),
            "-tspolicy", approved_policy_oid,
        )
        if "Verification: OK" not in verification:
            raise ValueError("Signed TSA response was not verified")

        details = _openssl("-reply", "-in", str(r), "-text")
        policy = re.search(r"(?m)^Policy OID:\s*(\S+)\s*$", details)
        stamp = _TIMESTAMP_RE.search(details)
        if (not policy or policy.group(1) != approved_policy_oid or
                not stamp or "Status: Granted." not in details or
                "Hash Algorithm: sha256" not in details):
            raise ValueError("Unapproved timestamp policy, hash or response status")
        try:
            signed_time = datetime.strptime(
                stamp.group(1), "%b %d %H:%M:%S %Y GMT"
            ).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError("Unparseable TSA signed generation time") from exc
        signed_ms = int(signed_time.timestamp()) * 1000
        boundary = manifest["boundary_ms"]
        if not (type(boundary) is int and
                boundary <= signed_ms <= boundary + RECEIPT_MAX_DELAY_MS):
            raise ValueError(
                "Even a genuine signed TSA response is OUTSIDE forward observation deadline"
            )
        return {
            "status": "OFFLINE_TSA_CHAIN_AND_DEADLINE_VERIFIED_NOT_PAPER_CERTIFIED",
            "witness_imprint_sha256": manifest["witness_imprint_hex_for_external_tsa"],
            "tsa_token_sha256": sha256(response_der).hexdigest(),
            "approved_policy_oid": approved_policy_oid,
            "verified_signed_time_ms": signed_ms,
            "cryptographic_signature_chain_verified": True,
            "signed_time_inside_predeclared_60s_window": True,
            "trusted_tsa_independence_audited": False,
            "source_origin_independently_certified": False,
            "raw_source_bytes_replicated_off_server": False,
            "full_forward_schedule_collected": False,
            "paper_validation_authorized": False,
            "orders_and_telegram_authorized": False,
        }
