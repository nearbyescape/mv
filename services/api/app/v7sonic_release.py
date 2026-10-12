"""V7Sonic release-adapter stage 1: six-market contract and message rehearsal.

Only consumes previously persisted ORIGINAL 31 public REST response bodies.
Recomputes the exact six-market planner from those bytes. This module has
no Binance network, database writer, Telegram sender or broker API.

IMPORTANT: The source research candidate remains NONPUBLISHABLE. The
outputs are a rehearsal contract for a separately tested production runner,
not permission to deliver signals to clients.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json
from typing import Any

from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_release_preview import build_offline_preview
from app.research.t7sonic_replay import _as_of
from app.research.t7sonic_release_candidate import POLICY
from services.t7sonic.early_live_smoke import FRAMES, _parse
from services.t7sonic.forward_live_quote import extract_contract_rule, parse_book_ticker
from services.t7sonic.replay_original_capture import _decode, replay_original

STRATEGY_ID = "MV-V7SONIC-REFERENCE-v1"
STEP_MS = 300_000
MAX_BOUNDARY_LAG_MS = 30_000
MAX_QUOTE_AGE_MS = 5_000
IST_OFFSET_MS = 330 * 60_000
DAY_MS = 86_400_000
OPEN_MS = 9 * 3_600_000
CLOSE_MS = 23 * 3_600_000
PAPER_STATUS = "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION"


def _ist_open(ms: int) -> bool:
    return OPEN_MS <= (ms + IST_OFFSET_MS) % DAY_MS < CLOSE_MS


def _hash_plan(plan: dict) -> str:
    return sha256(json.dumps(
        {key: value for key, value in plan.items() if key not in ("candidate_sha256", "delivery_status")},
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def _as_market_tuple(value: tuple, *, name: str) -> tuple:
    if not isinstance(value, tuple) or len(value) != len(set(value)) or any(
        item not in MARKETS for item in value
    ):
        raise ValueError("Invalid " + name)
    return value


def _seen_ids(value: tuple) -> tuple:
    if not isinstance(value, tuple) or len(value) != len(set(value)) or any(
        not isinstance(item, str) or len(item) != 64 or
        any(c not in "0123456789abcdef" for c in item)
        for item in value
    ):
        raise ValueError("Invalid persistent candidate-ID snapshot")
    return value


def format_private_rehearsal(candidate: dict) -> str:
    """Render the *actual V7 two-target schema*, never the V4 three-target one."""
    if (not isinstance(candidate, dict) or
            candidate.get("policy") != POLICY or
            candidate.get("status") != PAPER_STATUS or
            candidate.get("publishable_signal") is not False or
            candidate.get("executable_order") is not False or
            candidate.get("candidate_sha256") != _hash_plan(candidate) or
            candidate.get("symbol") not in MARKETS or
            candidate.get("direction") not in ("LONG", "SHORT") or
            not isinstance(candidate.get("expert"), str) or
            candidate.get("exit_fraction_tp1") != "0.5" or
            candidate.get("exit_fraction_tp2") != "0.5" or
            candidate.get("exit_policy") !=
            "TP1 50%, TP2 50%; then stop to entry for remainder"):
        raise ValueError("Unapproved, tampered or invalid V7Sonic candidate")

    boundary = candidate.get("decision_boundary_ms")
    if (type(boundary) is not int or boundary <= 0 or
            boundary % STEP_MS or
            candidate.get("expires_at_ms") != boundary + MAX_BOUNDARY_LAG_MS):
        raise ValueError("Malformed five-minute candidate deadline")

    from decimal import Decimal, InvalidOperation
    try:
        entry, stop, tp1, tp2 = (
            Decimal(candidate[k]) for k in
            ("entry", "stop_loss", "take_profit_1", "take_profit_2")
        )
        if any(not x.is_finite() or x <= 0 for x in (entry, stop, tp1, tp2)):
            raise ValueError("Invalid numeric levels")
    except (KeyError, TypeError, InvalidOperation):
        raise ValueError("Invalid numeric levels") from None
    if candidate["direction"] == "LONG":
        if not stop < entry < tp1 < tp2:
            raise ValueError("Invalid LONG geometry")
    elif not tp2 < tp1 < entry < stop:
        raise ValueError("Invalid SHORT geometry")

    boundary_ist = datetime.fromtimestamp(
        boundary / 1000, timezone(timedelta(hours=5, minutes=30))
    ).strftime("%d %b %Y %I:%M:%S %p IST")
    text = (
        "V7SONIC · INTERNAL RELEASE REHEARSAL — DO NOT TRADE\n"
        f"{candidate['direction']} {candidate['symbol']} · Binance USDT perpetual\n"
        f"Five-minute decision: {boundary_ist}\n"
        f"Expert: {candidate['expert']}\n"
        f"Indicative entry: {candidate['entry']}\n"
        f"Stop loss: {candidate['stop_loss']}\n"
        f"TP1 (50% at +1R): {candidate['take_profit_1']}\n"
        f"TP2 (50% at +2.5R): {candidate['take_profit_2']}\n"
        "After TP1: move the remaining stop to entry (reference only).\n"
        "No exchange orders or fills verified. Not authorized for clients."
    )
    if len(text) > 4096:
        raise ValueError("Telegram message would exceed provider limit")
    return text


def rehearse_original_capture(
    receipt: dict, *,
    observed_now_ms: int,
    active_symbols: tuple[str, ...],
    previously_seen_candidate_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Recalculate every decision against all 31 ORIGINAL saved HTTP bodies.

    Fail closed on any missing 1m/15m/1h/4h response, changed OHLCV, bad
    event-time, session, 5-second quote freshness or 30-second decision lag.
    No side effects, post-hoc requery, backfill, publication or orders.
    """
    active_symbols = _as_market_tuple(active_symbols, name="active symbols")
    seen = _seen_ids(previously_seen_candidate_ids)

    verified = replay_original(receipt)
    if (verified["original_http_responses_hash_checked"] != 31 or
            verified["exact_reconciliation_passed"] is not True or
            verified["price_field_discrepancies"] != 0 or
            verified["volume_field_discrepancies"] != 0):
        raise ValueError("Original market-source reconciliation failed")

    boundary = receipt["decision_boundary_ms"]
    recorded = receipt.get("recorded_ms_local_clock_claim")
    if (type(observed_now_ms) is not int or type(recorded) is not int or
            not boundary <= recorded <= observed_now_ms <=
            boundary + MAX_BOUNDARY_LAG_MS):
        raise ValueError("Stale or invalid live decision boundary")
    if not (_ist_open(boundary) and _ist_open(observed_now_ms)):
        raise ValueError("Outside frozen IST client operating session")

    exchange_info = _decode(receipt["exchange_info_body"])
    snapshots = []
    quotes = []
    for symbol in MARKETS:
        native = {
            frame: _parse(
                symbol, frame, boundary,
                _decode(receipt["kline_bodies"][symbol][frame])
            )
            for frame in FRAMES
        }
        snapshots.append(_as_of(native, symbol, boundary)["snapshot"])
        contract = extract_contract_rule(exchange_info, symbol)
        quote, proof = parse_book_ticker(
            symbol, boundary, _decode(receipt["quote_bodies"][symbol]),
            contract,
            received_ms=receipt["quote_received_ms_local_clock_claim"][symbol],
            evaluated_ms=observed_now_ms,
        )
        if (observed_now_ms - quote["observed_at_ms"] > MAX_QUOTE_AGE_MS or
                proof.get("source_status") == "FAILED"):
            raise ValueError("Stale source quote in client rehearsal")
        quotes.append(quote)

    result = build_offline_preview(
        snapshots, quotes,
        active_symbols=active_symbols,
        previously_seen_candidate_ids=seen,
    )
    if (result["markets_evaluated"] != len(MARKETS) or
            result["client_publication_authorized"] is not False or
            result["telegram_enqueued"] is not False or
            result["real_money_orders_authorized"] is not False):
        raise ValueError("Unexpected release or incomplete market coverage")

    rehearsal = []
    for candidate in result["indicative_candidates"]:
        if candidate["delivery_status"] == "SUPPRESSED_DUPLICATE_IN_OFFLINE_PREVIEW":
            continue
        if candidate["candidate_id"] in seen:
            raise ValueError("Duplicate candidate identity")
        rehearsal.append({
            "candidate_id": candidate["candidate_id"],
            "symbol": candidate["symbol"],
            "direction": candidate["direction"],
            "expert": candidate["expert"],
            "expires_at_ms": candidate["expires_at_ms"],
            "rehearsal_text": format_private_rehearsal(candidate),
        })
    return {
        "schema": 1,
        "status": "V7_RELEASE_CONTRACT_PRIVATE_REHEARSAL_NO_CLIENT_SEND",
        "strategy_id": STRATEGY_ID,
        "decision_boundary_ms": boundary,
        "source_batch_sha256": result["batch_sha256"],
        "original_http_responses_verified": 31,
        "markets_evaluated": len(MARKETS),
        "no_candidate": result["no_candidate"],
        "candidate_count": result["candidate_count"],
        "new_rehearsals": rehearsal,
        # Entire validated preview for the isolated PRIVATE paper ledger only.
        # No code consumes this as a client-authorized publication event.
        "sealed_internal_paper_batch": result,
        "client_publication_authorized": False,
        "telegram_enqueued": False,
        "orders_authorized": False,
        "persisted_outbox_implemented": False,
        "live_worker_integrated": False,
    }
