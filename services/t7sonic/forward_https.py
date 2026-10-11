"""Phase 2U — fail-closed *optional* HTTPS transport adapter for future paper research.

Not a daemon, deployment, background job, signal publisher, or order client.
Network access defaults to DENIED. Synthetic tests inject a mock response,
never contact Binance. When independently approved in a separate process,
the sole allowed destination is Binance USD-M public kline GET over verified
system-CA HTTPS, with no environment proxies or redirects.

Neither CA-verified TLS nor this machine's wall clock proves external
timestamp authenticity. No signed witness, off-VPS replication, full-six-
market synchronous capture, or production authorization exists here.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Callable
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

from app.research.t7sonic_forward_protocol import RECEIPT_MAX_DELAY_MS
from services.t7sonic.forward_acquisition import (
    HOST, RESOURCE, MAX_RESPONSE_BYTES,
    parse_response_bytes, request_plan,
)

MAX_NETWORK_TIMEOUT_SECONDS = 8.0
ALLOWED_JSON_TYPES = ("application/json",)
LOCAL_RECEIPT_UNWITNESSED = "LOCAL_CLOCK_ONLY_UNATTESTED"
SYNTHETIC_SOURCE = "INJECTED_TEST_RESPONSE"


@dataclass(frozen=True)
class TransportEnvelope:
    status: int
    final_url: str
    content_type: str
    raw_body: bytes
    received_ms: int
    provenance: str


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect forbidden: public research source must not change")


def expected_url(plan: dict) -> str:
    """Exact origin, path and whitelisted fixed query fields; never arbitrary URLs."""
    if not isinstance(plan, dict):
        raise ValueError("Approved source request plan required")
    params = plan.get("query")
    if not isinstance(params, dict):
        raise ValueError("Malformed request plan")
    # Reconstruct the original plan: never trust a caller-provided hostname.
    if plan != request_plan(params.get("symbol"), params.get("interval"),
                            plan.get("boundary_ms")):
        raise ValueError("Source plan differs from frozen source contract")
    return "https://" + HOST + RESOURCE + "?" + urlencode(params)


def inspect_transport_response(plan: dict, envelope: TransportEnvelope):
    """Verify exact URL, claimed receipt, response size and kline geometry.

    No HTTP is performed here. The response and receipt clock remain
    unauthenticated inputs even after all checks pass.
    """
    url = expected_url(plan)
    if not isinstance(envelope, TransportEnvelope):
        raise ValueError("Explicit transport envelope required")
    if (envelope.final_url != url or
            type(envelope.status) is not int or envelope.status != 200):
        raise ValueError("Non-200 or redirected public market response")
    content_type = envelope.content_type.split(";", 1)[0].strip().lower()
    if content_type not in ALLOWED_JSON_TYPES:
        raise ValueError("Unexpected source content type")
    if (not isinstance(envelope.raw_body, bytes) or
            not 2 <= len(envelope.raw_body) <= MAX_RESPONSE_BYTES):
        raise ValueError("Missing or oversized source response body")
    if (type(envelope.received_ms) is not int or
            not plan["boundary_ms"] <= envelope.received_ms <=
            plan["boundary_ms"] + RECEIPT_MAX_DELAY_MS):
        raise ValueError("Stale, future or untrusted claimed receipt cutoff")
    if envelope.provenance not in (
        SYNTHETIC_SOURCE, "LOCAL_SYSTEM_CA_TLS_NO_INDEPENDENT_WITNESS"
    ):
        raise ValueError("Unsupported or falsely claimed transport provenance")
    bars, proof = parse_response_bytes(
        plan, envelope.raw_body, http_status=envelope.status,
        receipt_ms_claim=envelope.received_ms,
    )
    if proof["response_body_sha256"] != sha256(envelope.raw_body).hexdigest():
        raise ValueError("Raw source digest mismatch")
    metadata = {
        "status": "UNATTESTED_TRANSPORT_GEOMETRY_ONLY",
        "symbol": plan["query"]["symbol"],
        "frame": plan["query"]["interval"],
        "boundary_ms": plan["boundary_ms"],
        "expected_url": url,
        "raw_sha256": proof["response_body_sha256"],
        "raw_bytes": len(envelope.raw_body),
        "receipt_ms_local_clock_unverified": envelope.received_ms,
        "provenance": envelope.provenance,
        "native_rows_validated": len(bars),
        "exchange_response_cryptographically_signed": False,
        "independent_timestamp_verified": False,
        "external_evidence_replication_verified": False,
        "trading_authorized": False,
    }
    return bars, metadata


def inspect_with_injected_transport(
    plan: dict, transport: Callable[[dict], TransportEnvelope]
):
    """Offline test seam: caller-injected transport cannot certify actual capture."""
    expected_url(plan)
    if not callable(transport):
        raise ValueError("Explicit test transport callable required")
    envelope = transport(plan)
    if (not isinstance(envelope, TransportEnvelope) or
            envelope.provenance != SYNTHETIC_SOURCE):
        raise ValueError("Offline injection must be explicitly marked synthetic")
    return inspect_transport_response(plan, envelope)


def optional_https_get(plan: dict, *, network_approved: bool = False,
                       timeout_seconds: float = 5.0) -> TransportEnvelope:
    """One bounded HTTPS GET, disabled by default. NO scheduling or persistence.

    Network activation requires explicit use of this function with approval.
    Even then it yields only local clock claims and raw response bytes.
    Never treat it as a certified prospective observation recorder.
    """
    url = expected_url(plan)
    if network_approved is not True:
        raise PermissionError("Live HTTPS disabled: independent collector not certified")
    if (isinstance(timeout_seconds, bool) or
            not isinstance(timeout_seconds, (float, int)) or
            not 0 < timeout_seconds <= MAX_NETWORK_TIMEOUT_SECONDS):
        raise ValueError("Invalid bounded HTTPS timeout")
    local_now = time.time_ns() // 1_000_000
    if local_now < plan["boundary_ms"]:
        raise ValueError("Cannot request frozen boundary before it occurs")
    if local_now > plan["boundary_ms"] + RECEIPT_MAX_DELAY_MS:
        raise ValueError("Deadline already missed before HTTPS request; do not backfill")
    # No redirects and no environment-controlled HTTP(S) proxies.
    context = ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("OS TLS certificate/hostname checking is mandatory")
    opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context),
                          _NoRedirects())
    request = Request(
        url, method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "T7Sonic-PaperResearch/2U",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with opener.open(request, timeout=float(timeout_seconds)) as response:
            final_url = response.geturl()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(MAX_RESPONSE_BYTES + 1)
            received = time.time_ns() // 1_000_000
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError("Public kline HTTPS acquisition failed closed") from exc
    envelope = TransportEnvelope(
        status=status, final_url=final_url, content_type=content_type,
        raw_body=body, received_ms=received,
        provenance="LOCAL_SYSTEM_CA_TLS_NO_INDEPENDENT_WITNESS",
    )
    # Verify immediately. Caller may preserve this envelope only after
    # separately satisfying future witness/retention certification.
    inspect_transport_response(plan, envelope)
    return envelope
