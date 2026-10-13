"""Conservative V7 historical 30-second aggregate trade-print diagnostic.

Public aggregate trade prints are NOT quotes or proof of executable orders.
The original candidate was never sent. Only assess records at/after the
durable local paper-journal insertion time, before boundary+30 seconds.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json

BOUNDARY = 1791862500000
WINDOW_END = BOUNDARY + 30_000   # exclusive
SLICE_MS = 5_000
SYMBOLS = ("SOLUSDT", "DOGEUSDT")
LIMIT = 1_000


def _decimal(text, *, allow_zero=False):
    if not isinstance(text, str):
        raise ValueError("String trade decimal required")
    try:
        result = Decimal(text)
    except InvalidOperation:
        raise ValueError("Invalid trade decimal") from None
    if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
        raise ValueError("Invalid trade decimal range")
    return result


def decode_slice(raw: bytes, *, start_ms: int, end_ms: int) -> list[dict]:
    """Fail closed on possibly truncated 1000-record endpoint response."""
    if (not isinstance(raw, bytes) or not 2 <= len(raw) <= 256_000 or
            type(start_ms) is not int or type(end_ms) is not int or
            not BOUNDARY <= start_ms < end_ms <= WINDOW_END or
            start_ms % SLICE_MS or end_ms - start_ms != SLICE_MS):
        raise ValueError("Invalid aggregate trade slice contract")
    try:
        packet = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Malformed Binance aggregate-trade response") from None
    if not isinstance(packet, list) or len(packet) >= LIMIT:
        raise ValueError("POSSIBLY_TRUNCATED_AGGREGATE_TRADES_FAIL_CLOSED")
    previous_id, previous_ts = None, None
    parsed = []
    for rec in packet:
        if (not isinstance(rec, dict) or
                not {"a", "p", "q", "f", "l", "T", "m"}.issubset(rec) or
                type(rec["a"]) is not int or rec["a"] < 0 or
                type(rec["f"]) is not int or
                type(rec["l"]) is not int or
                not 0 <= rec["f"] <= rec["l"] or
                type(rec["T"]) is not int or
                not start_ms <= rec["T"] < end_ms or
                type(rec["m"]) is not bool):
            raise ValueError("Malformed or off-window aggregate trade")
        if ((previous_id is not None and rec["a"] <= previous_id) or
                (previous_ts is not None and rec["T"] < previous_ts)):
            raise ValueError("Aggregate trade IDs or event times not ordered")
        price = _decimal(rec["p"])
        _decimal(rec["q"])
        previous_id, previous_ts = rec["a"], rec["T"]
        parsed.append({
            "id": rec["a"], "event_ms": rec["T"], "price": price,
            "buyer_is_maker": rec["m"],
        })
    return parsed


def score_entry_window(candidate: dict, *,
                       journal_inserted_ms: int, trade_slices: list[list[dict]]) -> dict:
    """Price-print evidence only. No order book, fills or execution claims."""
    if (not isinstance(candidate, dict) or
            candidate.get("symbol") not in SYMBOLS or
            candidate.get("direction") != "LONG" or
            candidate.get("expert") != "breakout" or
            type(journal_inserted_ms) is not int or
            not BOUNDARY <= journal_inserted_ms < WINDOW_END or
            not isinstance(trade_slices, list) or len(trade_slices) != 6):
        raise ValueError("Invalid V7 historical 30s entry tape context")
    entry = _decimal(candidate["entry"])
    stop = _decimal(candidate["stop_loss"])
    if not stop < entry:
        raise ValueError("Bad original reference entry/stop")
    records = [x for chunk in trade_slices for x in chunk]
    if any(not isinstance(r, dict) or
           not isinstance(r.get("price"), Decimal) for r in records):
        raise ValueError("Invalid trade event")
    for a,b in zip(records, records[1:]):
        if a["id"] >= b["id"] or a["event_ms"] > b["event_ms"]:
            raise ValueError("Overlapping or out-of-order aggregate trade slices")
    eligible = [r for r in records
                if journal_inserted_ms <= r["event_ms"] < WINDOW_END]
    at_or_above = [r for r in eligible if r["price"] >= entry]
    at_or_below = [r for r in eligible if r["price"] <= entry]
    return {
        "symbol": candidate["symbol"],
        "original_entry_reference": str(entry),
        "decision_boundary_ms": BOUNDARY,
        "earliest_conservative_observation_ms_local_unattested": journal_inserted_ms,
        "candidate_expiry_ms_exclusive": WINDOW_END,
        "aggregate_trade_slices_verified": 6,
        "prints_in_full_30s_window": len(records),
        "prints_after_journal_before_expiry": len(eligible),
        "any_post_journal_trade_price_at_or_above_entry": bool(at_or_above),
        "any_post_journal_trade_price_at_or_below_entry": bool(at_or_below),
        "first_post_journal_print_at_or_above_entry_ms":
            at_or_above[0]["event_ms"] if at_or_above else None,
        "first_post_journal_print_at_or_below_entry_ms":
            at_or_below[0]["event_ms"] if at_or_below else None,
        "minimum_post_journal_trade_price":
            str(min((r["price"] for r in eligible), default=Decimal(0)))
            if eligible else None,
        "maximum_post_journal_trade_price":
            str(max((r["price"] for r in eligible), default=Decimal(0)))
            if eligible else None,
        "market_trade_prints_are_order_book_quotes": False,
        "actual_quote_liquidity_verified": False,
        "original_client_signal_sent": False,
        "original_entry_order_or_fill_proven": False,
        "historical_reference_only_do_not_trade": True,
        "status": "V7_30S_AGGREGATE_TRADE_PRINTS_OBSERVED_NO_EXECUTION_PROOF",
    }
