"""V7Sonic paper quote contract for Binance USD-M, with NO HTTP calls.

Bind an injected /fapi/v1/ticker/bookTicker response to source event time,
local receipt claim and explicit frozen /fapi/v1/exchangeInfo rules. This
module performs no polling, scheduling, publishing, DB access or trading.

Even a valid Binance-format REST response is not independently signed or
timestamp witnessed; current outputs are never actionable client signals.
"""
from __future__ import annotations

from decimal import Decimal as D
from hashlib import sha256
import json

from app.research.t7sonic_perception import decimal_number
from app.research.t7sonic_validation_plan import MARKETS

MAX_BOOK_BODY = 8_192
MAX_EXCHANGE_BODY = 2_000_000
MAX_LATENCY_MS = 5_000
MAX_BOUNDARY_LAG_MS = 30_000
QUOTE_ENDPOINT = "https://fapi.binance.com/fapi/v1/ticker/bookTicker"
INFO_ENDPOINT = "https://fapi.binance.com/fapi/v1/exchangeInfo"


def _positive(val: object, name: str) -> D:
    if not isinstance(val, str):
        raise ValueError("Expected decimal string: " + name)
    dec = decimal_number(val, name)
    if dec <= 0:
        raise ValueError("Nonpositive " + name)
    return dec


def extract_contract_rule(exchange_info_raw: bytes, symbol: str) -> dict:
    """Only accept actual PRICE_FILTER and LOT_SIZE, never precision guesses."""
    if symbol not in MARKETS or not isinstance(exchange_info_raw, bytes) or not (
        2 <= len(exchange_info_raw) <= MAX_EXCHANGE_BODY
    ):
        raise ValueError("Invalid source contract bytes")
    try:
        data = json.loads(exchange_info_raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid exchangeInfo JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
        raise ValueError("Missing exchangeInfo symbols")
    matches = [x for x in data["symbols"] if isinstance(x, dict) and
               x.get("symbol") == symbol]
    if len(matches) != 1:
        raise ValueError("Missing or duplicate futures symbol")
    market = matches[0]
    if (market.get("status") != "TRADING" or
            market.get("contractType") != "PERPETUAL" or
            market.get("quoteAsset") != "USDT"):
        raise ValueError("Market not an active USD-M perpetual")
    filters = market.get("filters")
    if not isinstance(filters, list):
        raise ValueError("Missing symbol filters")
    constraints = {}
    for filter_type in ("PRICE_FILTER", "LOT_SIZE"):
        selected = [x for x in filters if isinstance(x, dict) and
                    x.get("filterType") == filter_type]
        if len(selected) != 1:
            raise ValueError("Missing or duplicated venue rule " + filter_type)
        constraints[filter_type] = selected[0]
    p, l = constraints["PRICE_FILTER"], constraints["LOT_SIZE"]
    tick = _positive(p.get("tickSize"), "tickSize")
    min_price = _positive(p.get("minPrice"), "minPrice")
    max_price = _positive(p.get("maxPrice"), "maxPrice")
    step = _positive(l.get("stepSize"), "stepSize")
    min_qty = _positive(l.get("minQty"), "minQty")
    max_qty = _positive(l.get("maxQty"), "maxQty")
    if min_price >= max_price or min_qty >= max_qty or tick > max_price or step > max_qty:
        raise ValueError("Invalid venue price or quantity filter geometry")
    return {
        "symbol": symbol, "tick_size": str(tick),
        "min_price": str(min_price), "max_price": str(max_price),
        "lot_size_step": str(step),
        "min_quantity": str(min_qty), "max_quantity": str(max_qty),
        "contract_source_sha256": sha256(exchange_info_raw).hexdigest(),
        "source_status": "UNATTESTED_EXCHANGEINFO_FORMAT_VALID",
        "quote_and_contract_authenticated": False,
    }


def parse_book_ticker(
    symbol: str, boundary_ms: int, raw: bytes, venue: dict, *,
    received_ms: int, evaluated_ms: int,
) -> tuple[dict, dict]:
    """Fail-closed single-symbol ticker to candidate planner quote mapping.

    Binance's signed field named 'time' is exchange transaction/event time,
    NOT a server-side signature. The local receipt is an untrusted claim.
    """
    if (symbol not in MARKETS or
            type(boundary_ms) is not int or boundary_ms % 300_000 or
            type(received_ms) is not int or type(evaluated_ms) is not int or
            not boundary_ms <= received_ms <= evaluated_ms <=
            boundary_ms + MAX_BOUNDARY_LAG_MS or
            evaluated_ms-received_ms > MAX_LATENCY_MS):
        raise ValueError("Quote outside frozen decision/freshness boundary")
    if not isinstance(venue, dict) or venue.get("symbol") != symbol or (
        venue.get("source_status") != "UNATTESTED_EXCHANGEINFO_FORMAT_VALID"
    ):
        raise ValueError("Missing frozen venue source")
    if not isinstance(raw, bytes) or not (2 <= len(raw) <= MAX_BOOK_BODY):
        raise ValueError("Invalid quote body size")
    try:
        book = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("Invalid bookTicker JSON") from exc
    if (not isinstance(book, dict) or
            set(book) != {"symbol", "bidPrice", "bidQty",
                          "askPrice", "askQty", "time"} or
            book["symbol"] != symbol or type(book["time"]) is not int):
        raise ValueError("Single-market bookTicker schema mismatch")
    exchange_ms = book["time"]
    if not (boundary_ms <= exchange_ms <= received_ms and
            received_ms-exchange_ms <= MAX_LATENCY_MS):
        raise ValueError("Exchange book timestamp stale, premature or future")
    bid, ask = (
        _positive(book[key], key) for key in ("bidPrice", "askPrice")
    )
    bid_size, ask_size = (
        _positive(book[key], key) for key in ("bidQty", "askQty")
    )
    tick = _positive(venue.get("tick_size"), "tick_size")
    floor = _positive(venue.get("min_price"), "min_price")
    ceiling = _positive(venue.get("max_price"), "max_price")
    if (bid >= ask or bid < floor or ask > ceiling or
            (bid-floor)%tick or (ask-floor)%tick):
        raise ValueError("Crossed, out-of-bounds or non-tick-aligned quote")
    q = {
        "symbol": symbol,
        "decision_boundary_ms": boundary_ms,
        "observed_at_ms": exchange_ms,
        "evaluated_at_ms": evaluated_ms,
        "bid": str(bid),
        "ask": str(ask),
        "tick_size": str(tick),
    }
    proof = {
        "status": "VALIDATED_BOOKTICKER_GEOMETRY_NOT_VERIFIED_MARKET_EVIDENCE",
        "book_ticker_sha256": sha256(raw).hexdigest(),
        "venue_rule_sha256": venue["contract_source_sha256"],
        "received_ms_local_clock_claim": received_ms,
        "exchange_event_ms_unattested": exchange_ms,
        "displayed_bid_size": str(bid_size),
        "displayed_ask_size": str(ask_size),
        "independent_receipt_witness_verified": False,
        "actual_available_fill_liquidity_verified": False,
        "trading_authorized": False,
    }
    return q, proof
