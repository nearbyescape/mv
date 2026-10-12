"""Phase 2X — offline RFC3161 TSA HTTP handoff contract, no network.

Builds an exact, provider-neutral HTTPS POST envelope from the prior
unsigned witness digest and nonce-bearing RFC3161 query. The operator
MUST independently select and approve a real outside TSA hostname,
policy OID and CA bundle fingerprint in a later phase.

This module does not send requests, follow redirects, use proxies, accept
clock claims as witnesses, start collectors, or enable trading. Genuine
off-VPS timestamp service governance and raw source replication remain
not implemented. Binary response verification happens separately in
forward_rfc3161.py after an independent receiver captures its bytes.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
import ipaddress
import re
import tempfile

from services.t7sonic.forward_rfc3161 import (
    _openssl, _read_imprint_from_query_dump,
    MAX_QUERY_BYTES, MAX_TOKEN_BYTES,
)
from services.t7sonic.forward_witness import validate_unsigned_witness_request

DOMAINS_BLOCKED = frozenset({
    "localhost", "local", "internal", "test", "invalid", "example",
})
MAX_ENDPOINT_CHARS = 240
MAX_RESPONSE_BYTES = MAX_TOKEN_BYTES


def _sha(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _oid(value):
    return isinstance(value, str) and bool(
        re.fullmatch(r"(?:[0-9]+\.){2,12}[0-9]+", value)
    )


def _endpoint(url: str) -> str:
    """Reject ambiguous/embedded IP, credentials and non-HTTPS TSA endpoints.

    DNS rebinding is NOT addressed by syntax checks; deployment requires
    a separate network policy restricting egress to approved TSA IPs.
    """
    if (not isinstance(url, str) or not 15 < len(url) <= MAX_ENDPOINT_CHARS
            or not url.isascii() or any(ord(c) <= 32 for c in url)
            or "#" in url or "@" in url or "%" in url or "\\" in url):
        raise ValueError("Invalid noncanonical TSA endpoint")
    try:
        u = urlsplit(url)
        host = u.hostname
        port = u.port
    except ValueError as exc:
        raise ValueError("Invalid TSA endpoint URI") from exc
    if (u.scheme != "https" or not host or
            u.username is not None or u.password is not None or
            port not in (None, 443) or not u.netloc.endswith(host)
            or u.query or u.fragment or not u.path.startswith("/")
            or "//" in u.path or "/../" in u.path or "/./" in u.path
            or u.path.endswith("/..") or u.path.endswith("/.")):
        raise ValueError("TSA destination must be canonical fixed HTTPS URI")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP literal TSA endpoints forbidden")
    labels = host.split(".")
    if (len(labels) < 2 or any(not re.fullmatch(
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label
        ) for label in labels) or labels[-1] in DOMAINS_BLOCKED):
        raise ValueError("TSA must be a public canonical DNS hostname")
    return url


def prepare_offline_tsa_post(
    manifest: dict, query_der: bytes, *,
    tsa_endpoint: str, approved_ca_sha256: str, approved_policy_oid: str
) -> dict:
    """Structural submission specification; DO NOT POST OR CLAIM AUTHORIZATION."""
    evidence = validate_unsigned_witness_request(manifest)
    endpoint = _endpoint(tsa_endpoint)
    if not _sha(approved_ca_sha256) or not _oid(approved_policy_oid):
        raise PermissionError("Frozen independently selected CA and OID required")
    if not isinstance(query_der, bytes) or not 16 <= len(query_der) <= MAX_QUERY_BYTES:
        raise ValueError("Malformed nonce-bearing RFC3161 query")
    with tempfile.TemporaryDirectory(prefix="t7sonic-tsa-plan-") as tmp:
        request = Path(tmp) / "request.tsq"
        request.write_bytes(query_der)
        qtext = _openssl("-query", "-in", str(request), "-text")
    if (_read_imprint_from_query_dump(qtext) != evidence["witness_imprint_sha256"]
            or "Nonce:" not in qtext or
            "Certificate required: yes" not in qtext
            or "Hash Algorithm: sha256" not in qtext):
        raise ValueError("RFC3161 request does not bind frozen witness imprint")
    return {
        "schema": 1,
        "status": "OFFLINE_TSA_SUBMISSION_PLAN_NOT_SENT",
        "http_method": "POST",
        "tsa_endpoint": endpoint,
        "content_type": "application/timestamp-query",
        "accept": "application/timestamp-reply",
        "query_der_sha256": sha256(query_der).hexdigest(),
        "query_der_bytes": len(query_der),
        "witness_imprint_sha256": evidence["witness_imprint_sha256"],
        "approved_ca_bundle_sha256_input": approved_ca_sha256,
        "approved_policy_oid_input": approved_policy_oid,
        "expected_response_max_bytes": MAX_RESPONSE_BYTES,
        "max_request_duration_seconds": 8,
        "must_reject_redirects": True,
        "must_disable_environment_proxies": True,
        "network_call_implemented": False,
        "request_sent": False,
        "response_received": False,
        "independent_tsa_audited": False,
        "signed_token_verified": False,
        "remote_source_archive_witnessed": False,
        "paper_observation_approved": False,
        "trading_authorized": False,
    }


def inspect_unverified_tsa_http_envelope(
    plan: dict, *, endpoint: str, status: int,
    content_type: str, raw_reply: bytes,
) -> dict:
    """Body and origin shape only; NEVER treat an unverified reply as a timestamp."""
    if (not isinstance(plan, dict) or
            plan.get("status") != "OFFLINE_TSA_SUBMISSION_PLAN_NOT_SENT"
            or plan.get("network_call_implemented") is not False
            or plan.get("request_sent") is not False
            or plan.get("signed_token_verified") is not False
            or endpoint != plan.get("tsa_endpoint") or _endpoint(endpoint) != endpoint
            or type(status) is not int or status != 200
            or not isinstance(content_type, str) or
            content_type.partition(";")[0].strip().lower() !=
                "application/timestamp-reply" or
            not isinstance(raw_reply, bytes) or
            not 32 <= len(raw_reply) <= MAX_RESPONSE_BYTES):
        raise ValueError("Unapproved, redirected, malformed or oversized TSA HTTP reply")
    return {
        "status": "UNVERIFIED_TSA_HTTP_REPLY_ONLY",
        "response_sha256": sha256(raw_reply).hexdigest(),
        "response_bytes": len(raw_reply),
        "endpoint": endpoint,
        "rfc3161_signature_verified": False,
        "receipt_time_verified": False,
        "paper_study_approved": False,
        "trading_authorized": False,
    }
