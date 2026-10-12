"""V7Sonic opt-in public USD-M exchangeInfo/bookTicker HTTP transport.

No account authentication, orders, scheduler, Telegram, production wiring,
or implicit network access. Activated only by an explicit caller argument.
Sole allowed origin: Binance USD-M public fapi.binance.com, HTTPS with OS
trusted CA/hostname verification; redirects and proxies are disabled.

The exchange's public REST responses are unsigned and the local receipt time
remains UNATTESTED even after SSL and strict endpoint validation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_live_quote import (
    INFO_ENDPOINT, QUOTE_ENDPOINT, MAX_BOOK_BODY, MAX_EXCHANGE_BODY,
)

MAX_PUBLIC_HTTP_TIMEOUT = 4.0


@dataclass(frozen=True)
class PublicHttpResponse:
    request_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    received_ms_local_claim: int


class _NeverRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Public price metadata must never follow redirects")


def approved_public_url(kind: str, symbol: str | None = None) -> tuple[str,int]:
    if kind == "exchangeInfo" and symbol is None:
        return INFO_ENDPOINT, MAX_EXCHANGE_BODY
    if kind == "bookTicker" and symbol in MARKETS:
        return QUOTE_ENDPOINT+"?"+urlencode({"symbol":symbol}), MAX_BOOK_BODY
    raise ValueError("Only explicit public exchangeInfo or six bookTicker URLs")


def verify_http_response(
    kind: str, response: PublicHttpResponse, *, symbol: str | None = None,
) -> dict:
    """Validate transport geometry only, never authenticate the data publisher."""
    url, maximum = approved_public_url(kind, symbol)
    if (not isinstance(response, PublicHttpResponse) or
            response.request_url != url or response.final_url != url or
            type(response.status) is not int or response.status != 200 or
            not isinstance(response.content_type, str) or
            response.content_type.partition(";")[0].strip().lower() !=
            "application/json" or
            not isinstance(response.body, bytes) or
            not 2 <= len(response.body) <= maximum or
            type(response.received_ms_local_claim) is not int or
            response.received_ms_local_claim <= 0):
        raise ValueError("Malformed/redirected or oversized public HTTP response")
    return {
        "status": "PUBLIC_REST_BODY_UNATTESTED",
        "expected_url": url,
        "body_sha256": sha256(response.body).hexdigest(),
        "body_bytes": len(response.body),
        "receipt_ms_local_clock_unverified": response.received_ms_local_claim,
        "tls_origin_independently_attested": False,
        "data_payload_signed_by_exchange": False,
        "client_publication_authorized": False,
        "orders_authorized": False,
    }


def optional_public_http_get(
    kind: str, *, symbol: str | None = None,
    network_approved: bool = False, timeout_seconds: float = 2.0,
) -> PublicHttpResponse:
    """ONE bounded explicit public GET; no side effects other than that GET."""
    url, maximum = approved_public_url(kind, symbol)
    if network_approved is not True:
        raise PermissionError("Public HTTPS disabled unless explicitly approved")
    if (isinstance(timeout_seconds, bool) or
            not isinstance(timeout_seconds, (int, float)) or
            not 0 < timeout_seconds <= MAX_PUBLIC_HTTP_TIMEOUT):
        raise ValueError("Public HTTPS timeout out of frozen bounds")
    tls = ssl.create_default_context()
    if not tls.check_hostname or tls.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("OS CA and hostname verification required")
    opener = build_opener(
        ProxyHandler({}), HTTPSHandler(context=tls), _NeverRedirect()
    )
    request = Request(url, method="GET", headers={
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "V7Sonic-InternalPaperInspection/1.0",
    })
    try:
        with opener.open(request, timeout=float(timeout_seconds)) as returned:
            body = returned.read(maximum + 1)
            received = time.time_ns()//1_000_000
            response = PublicHttpResponse(
                request_url=url, final_url=returned.geturl(),
                status=returned.status,
                content_type=returned.headers.get("Content-Type", ""),
                body=body, received_ms_local_claim=received,
            )
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ValueError("Public GET transport error, fail closed") from exc
    verify_http_response(kind, response, symbol=symbol)
    return response
