"""T7Sonic Phase 2T: offline Binance USD-M REST kline intake contract.

NO HTTP client, sockets, credentials, scheduler, orders, Telegram, journal
writes, or trusted timestamp is implemented. The caller supplies fake/raw
response bytes and untrusted receipt-time CLAIMS; this module validates
their internal geometry and provides deterministic SHA-256 provenance.

Actual Binance /fapi/v1/klines over HTTPS is a public unsigned API. A
hash of the downloaded body is NOT Binance's signature, a timestamp,
or proof of causal collection. Independent collection-time witnessing
and sealed off-server retention MUST precede any forward certification.
"""
from __future__ import annotations

from hashlib import sha256
import json

from app.research.t7sonic_forward_protocol import (
    START_MS, END_MS, STEP_MS, RECEIPT_MAX_DELAY_MS,
)
from app.research.t7sonic_perception import (
    Bar, INTERVAL_MS, perceive_symbol,
)
from app.research.t7sonic_history import (
    HISTORICAL_FRAMES, _reconcile_higher_frames_against_minutes,
)
from app.research.t7sonic_replay import _as_of
from app.research.t7sonic_validation_plan import MARKETS

HOST = "fapi.binance.com"
RESOURCE = "/fapi/v1/klines"
ROWS_BY_FRAME = {"1m": 480, "15m": 64, "1h": 64, "4h": 64}
MAX_RESPONSE_BYTES = 256_000
PLAN_STATUS = "OFFLINE_REQUEST_PLAN_NO_HTTP"
SOURCE_STATUS = "OFFLINE_UNATTESTED_RAW_RESPONSE_VALIDATION"


def _canonical_digest(item: dict) -> str:
    return sha256(json.dumps(
        item, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()


def request_plan(symbol: str, frame: str, boundary_ms: int) -> dict:
    """Exact bounded GET query for 64 model bars or 480 1m proof bars.

    Ending at last COMPLETED candle avoids an in-progress kline. Each
    request explicitly supplies startTime, endTime, limit and interval.
    """
    if symbol not in MARKETS or frame not in ROWS_BY_FRAME:
        raise ValueError("Only the six frozen USD-M symbols/four source frames")
    if (type(boundary_ms) is not int or
            not START_MS <= boundary_ms < END_MS or
            boundary_ms % STEP_MS):
        raise ValueError("Outside frozen 5m prospective schedule")
    step = INTERVAL_MS[frame]
    end = (boundary_ms // step) * step
    count = ROWS_BY_FRAME[frame]
    start = end - count * step
    if start < 0:
        raise ValueError("Impossible historical warmup")
    body = {
        "status": PLAN_STATUS,
        "method": "GET",
        "scheme": "https",
        "host": HOST,
        "path": RESOURCE,
        "query": {
            "symbol": symbol, "interval": frame,
            "startTime": start,
            "endTime": end - 1,
            "limit": count,
        },
        "boundary_ms": boundary_ms,
        "expected_last_complete_end_ms": end,
        "requires_external_source_time_witness": True,
        "http_implemented": False,
        "trading_authorized": False,
    }
    return {**body, "request_plan_sha256": _canonical_digest(body)}


def parse_response_bytes(
    plan: dict, raw_response: bytes, *, http_status: int,
    receipt_ms_claim: int,
) -> tuple[list[Bar], dict]:
    """Validate an exact synthetic/example Binance-shaped 12-field kline body.

    A caller can forge payload and receipt claims: output is intentionally
    UNATTESTED. This parser does not make an HTTP request.
    """
    if not isinstance(plan, dict):
        raise ValueError("Exact request plan required")
    symbol = plan.get("query", {}).get("symbol") if isinstance(plan.get("query"), dict) else None
    frame = plan.get("query", {}).get("interval") if isinstance(plan.get("query"), dict) else None
    boundary = plan.get("boundary_ms")
    if plan != request_plan(symbol, frame, boundary):
        raise ValueError("Kline request metadata mismatch")
    if type(http_status) is not int or http_status != 200:
        raise ValueError("Source HTTP error or redirect is not a kline response")
    if (type(receipt_ms_claim) is not int or
            not boundary <= receipt_ms_claim <= boundary + RECEIPT_MAX_DELAY_MS):
        raise ValueError("Source response not received within claimed decision deadline")
    if (not isinstance(raw_response, bytes) or
            not 2 <= len(raw_response) <= MAX_RESPONSE_BYTES):
        raise ValueError("Missing or unbounded raw kline body")
    try:
        rows = json.loads(raw_response)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Malformed raw JSON response") from exc
    count = ROWS_BY_FRAME[frame]
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Missing/duplicated/extra kline rows at frozen time window")

    step = INTERVAL_MS[frame]
    first = plan["query"]["startTime"]
    parsed = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 12:
            raise ValueError("Expected 12-position USD-M kline")
        t, closing = row[0], row[6]
        if (type(t) is not int or type(closing) is not int or
                t != first + index * step or closing != t + step - 1):
            raise ValueError("Missing, duplicate, reordered or partial source candles")
        if not all(isinstance(row[k], str) for k in (1, 2, 3, 4, 5)):
            raise ValueError("Price/volume values must be source decimal strings")
        bar = Bar.parse({
            "open_ms": t,
            "open": row[1], "high": row[2], "low": row[3],
            "close": row[4], "volume": row[5],
        }, frame)
        if t + step > plan["expected_last_complete_end_ms"]:
            raise ValueError("Lookahead: incomplete candle in source")
        parsed.append(bar)
    if parsed[-1].open_ms + step != plan["expected_last_complete_end_ms"]:
        raise ValueError("Last completed bar unexpectedly stale")

    proof = {
        "status": SOURCE_STATUS,
        "symbol": symbol,
        "frame": frame,
        "decision_boundary_ms": boundary,
        "request_plan_sha256": plan["request_plan_sha256"],
        "response_body_sha256": sha256(raw_response).hexdigest(),
        "raw_response_bytes": len(raw_response),
        "verified_calendar_rows": len(parsed),
        "first_source_open_ms": parsed[0].open_ms,
        "last_source_complete_end_ms": parsed[-1].open_ms + step,
        "receipt_ms_untrusted_claim": receipt_ms_claim,
        "tls_peer_certificate_verified": False,
        "exchange_signature_verified": False,
        "independent_timestamp_witness": False,
        "historical_outcome_labels_read": False,
        "trading_authorized": False,
    }
    return parsed, proof


def assemble_offline_snapshot(
    symbol: str, boundary_ms: int,
    response_records: dict[str, tuple[dict, bytes, int, int]],
) -> tuple[dict, dict]:
    """Four exact frame responses -> one causal five-frame perception proof.

    Values in response_records are (request_plan, raw_bytes, HTTP_status,
    claimed_receipt_ms). All source frames must share symbol and boundary.
    No outside data or future price is loaded.
    """
    if (symbol not in MARKETS or
            not isinstance(response_records, dict) or
            set(response_records) != set(HISTORICAL_FRAMES)):
        raise ValueError("Four source frames mandatory for one frozen market")
    frames = {}
    proofs = {}
    for frame in HISTORICAL_FRAMES:
        record = response_records[frame]
        if not isinstance(record, tuple) or len(record) != 4:
            raise ValueError("Explicit source response tuple required")
        request, raw, status, receipt = record
        if request != request_plan(symbol, frame, boundary_ms):
            raise ValueError("Response does not match frozen market and cutoff")
        frames[frame], proofs[frame] = parse_response_bytes(
            request, raw, http_status=status, receipt_ms_claim=receipt
        )
    event = _as_of(frames, symbol, boundary_ms)
    perception = perceive_symbol(event["snapshot"])
    audited = {
        "status": "OFFLINE_AS_OF_PERCEPTION_NOT_LIVE_SIGNAL",
        "symbol": symbol,
        "decision_boundary_ms": boundary_ms,
        "frame_source_proofs": proofs,
        "native_cross_resolution_reconciliation": event["reconciliation"],
        "perception_feature_source_sha256": perception["feature_source_sha256"],
        "independent_receipt_time_verified": False,
        "live_binance_collection_performed": False,
        "trades_or_telegram_authorized": False,
        "outcome_labels_computed": False,
    }
    return perception, audited
