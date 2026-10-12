"""V7Sonic quantitative gate for an OPERATOR-ATTESTED portfolio snapshot.

This is deliberately a zero-I/O verification function, not an exchange
account or venue source authenticator. A signed, bounded risk review is
better than a meaningless 64-character "risk_review_sha256" field, but
manual attestations are NOT proof of actual funds, liquidation, margin,
open positions, exchange fills or trading profitability.

The independent release-certification producer remains a separate gate.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from app.research.t7sonic_validation_plan import MARKETS

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_RISK_PER_TRADE = Decimal("0.005")
MAX_AGGREGATE_RISK = Decimal("0.02")
MAX_GROSS_NOTIONAL = Decimal("2")
MAX_OPEN_POSITIONS = 4
MIN_FEE_BPS_SIDE = Decimal("4")
MIN_SLIP_BPS_SIDE = Decimal("4")
MIN_FUNDING_BPS = Decimal("2")

_REVIEW_KEYS = {
    "schema", "candidate_id", "original_http_sha256", "observed_at_ms",
    "snapshot_origin", "equity_usdt", "reserved_loss_usdt",
    "gross_open_notional_usdt", "open_positions", "active_symbols",
    "candidate_quantity", "market_min_quantity", "market_max_quantity",
    "market_step", "minimum_notional_usdt", "fee_bps_per_side",
    "slippage_bps_per_side", "funding_buffer_bps",
    "contract_source_sha256",
}


def _number(packet: dict, key: str, *, allow_zero=False) -> Decimal:
    value = packet.get(key)
    if not isinstance(value, str) or len(value) > 70:
        raise PermissionError("Risk review requires exact decimal strings")
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise PermissionError("Invalid numeric risk review field") from None
    if not n.is_finite() or n < 0 or (n == 0 and not allow_zero):
        raise PermissionError("Non-positive or non-finite risk review field")
    return n


def audit_operator_risk_review(
    review: dict, candidate: dict, *,
    now_ms: int, expected_original_http_sha256: str,
) -> dict:
    """Verify a signed *claimed* risk snapshot against original candidate.

    This does NOT say the source is authenticated. Only a separately reviewed
    source/portfolio certification can enable final client publication.
    """
    if (not isinstance(review, dict) or set(review) != _REVIEW_KEYS or
            not isinstance(candidate, dict) or type(now_ms) is not int or
            not isinstance(expected_original_http_sha256, str) or
            not HEX64.fullmatch(expected_original_http_sha256)):
        raise PermissionError("Complete risk review and pinned source required")
    if (type(review["schema"]) is not int or review["schema"] != 1 or
            review["candidate_id"] != candidate.get("candidate_id") or
            review["original_http_sha256"] != expected_original_http_sha256 or
            not isinstance(review["contract_source_sha256"], str) or
            not HEX64.fullmatch(review["contract_source_sha256"])):
        raise PermissionError("Risk review candidate or source does not match")

    # A reconciled manual claim is permitted only as an explicit attestation;
    # it cannot be represented as automatically exchange-authenticated.
    if review["snapshot_origin"] != "OPERATOR_RECONCILED_UNATTESTED":
        raise PermissionError("Unsupported claimed account-source classification")
    observed = review["observed_at_ms"]
    if (type(observed) is not int or observed > now_ms or
            now_ms - observed > 5_000):
        raise PermissionError("Stale operator portfolio snapshot")
    active = review["active_symbols"]
    slots = review["open_positions"]
    if (type(slots) is not int or not 0 <= slots < MAX_OPEN_POSITIONS or
            not isinstance(active, list) or
            len(active) != slots or len(set(active)) != len(active) or
            any(not isinstance(x, str) or x not in MARKETS for x in active) or
            candidate.get("symbol") in active):
        raise PermissionError("Incomplete, conflicting or full portfolio slots")

    equity = _number(review, "equity_usdt")
    reserved = _number(review, "reserved_loss_usdt", allow_zero=True)
    gross = _number(review, "gross_open_notional_usdt", allow_zero=True)
    quantity = _number(review, "candidate_quantity")
    minimum_qty = _number(review, "market_min_quantity")
    maximum_qty = _number(review, "market_max_quantity")
    step = _number(review, "market_step")
    min_notional = _number(review, "minimum_notional_usdt")
    fees = _number(review, "fee_bps_per_side")
    slippage = _number(review, "slippage_bps_per_side")
    funding = _number(review, "funding_buffer_bps")
    entry = _number(candidate, "entry")
    stop = _number(candidate, "stop_loss")
    if (fees < MIN_FEE_BPS_SIDE or slippage < MIN_SLIP_BPS_SIDE or
            funding < MIN_FUNDING_BPS or minimum_qty > maximum_qty or
            not minimum_qty <= quantity <= maximum_qty or
            quantity % step != 0 or
            (candidate.get("direction") == "LONG" and stop >= entry) or
            (candidate.get("direction") == "SHORT" and stop <= entry) or
            candidate.get("direction") not in ("LONG", "SHORT")):
        raise PermissionError("Untradeable claimed quantity, cost or geometry")

    exposure = quantity * entry
    cost_unit = ((entry + stop) * (fees + slippage) / Decimal("10000") +
                 entry * funding / Decimal("10000"))
    risk_new = quantity * (abs(entry - stop) + cost_unit)
    if (exposure < min_notional or
            risk_new > equity * MAX_RISK_PER_TRADE or
            reserved + risk_new > equity * MAX_AGGREGATE_RISK or
            gross + exposure > equity * MAX_GROSS_NOTIONAL or
            reserved > equity * MAX_AGGREGATE_RISK or
            gross > equity * MAX_GROSS_NOTIONAL):
        raise PermissionError("Portfolio or venue notional risk limit exceeded")
    return {
        "status": "MANUAL_PORTFOLIO_RISK_ATTESTATION_BOUNDS_PASS_UNAUTHENTICATED",
        "candidate_id": candidate["candidate_id"],
        "per_trade_risk_fraction": str(risk_new / equity),
        "aggregate_risk_fraction": str((reserved + risk_new) / equity),
        "gross_notional_multiple": str((gross + exposure) / equity),
        "active_slots_after": slots + 1,
        "live_account_or_venue_authenticated": False,
        "orders_authorized": False,
    }
