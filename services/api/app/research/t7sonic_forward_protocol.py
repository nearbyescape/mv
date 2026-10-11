"""T7Sonic Phase 2Q: synthetic-only forward observation precommit protocol.

This module NEVER polls an exchange, writes outcomes, sends messages, places
orders, or certifies wall-clock timestamps. It is a deterministic protocol
for future deployment of a separate trusted observation recorder. Synthetic
tests only: an input receipt_ms is a CLAIM, not a trusted timestamp.

The frozen candidate remains the original failed-breakout-reversal
implementation from source commit 384d089..., with all six markets
recorded at every qualifying 5-minute boundary, INCLUDING NO-WATCH rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from .t7sonic_experts import EXPERT_NAMES, RESEARCH_ONLY_STATUS
from .t7sonic_validation_plan import MARKETS, EXPERT, STRATEGY_SHA

START = datetime(2026, 10, 15, tzinfo=timezone.utc)
END_EXCLUSIVE = datetime(2026, 12, 29, tzinfo=timezone.utc)
START_MS = int(START.timestamp() * 1000)
END_MS = int(END_EXCLUSIVE.timestamp() * 1000)
STEP_MS = 300_000
RECEIPT_MAX_DELAY_MS = 60_000
SHA_PATTERN_LENGTH = 64
FIRST_PREVIOUS_SHA = "0" * 64
ONLY_ALLOWED_MODE = "SYNTHETIC_TEST_NO_TRUSTED_TIMESTAMP"


def _digest(payload: dict) -> str:
    return sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def frozen_forward_protocol() -> dict:
    """Sealed proposed future date range, not authorization to observe live markets."""
    base = {
        "schema": 1,
        "status": "ENGINEERING_ONLY_LIVE_OBSERVER_NOT_DEPLOYED",
        "mode": ONLY_ALLOWED_MODE,
        "original_expert_source_sha": STRATEGY_SHA,
        "candidate_expert": EXPERT,
        "markets": list(MARKETS),
        "start_utc": START.isoformat(),
        "end_exclusive_utc": END_EXCLUSIVE.isoformat(),
        "utc_calendar_days": (END_EXCLUSIVE - START).days,
        "five_minute_boundaries_per_day": 288,
        "maximum_observation_receipt_delay_ms": RECEIPT_MAX_DELAY_MS,
        "primary_horizon_minutes": 60,
        "baseline_directions": ["LONG", "SHORT"],
        "emit_no_watch_rows": True,
        "watch_direction_origin": "UNCHANGED_T7SONIC_RESEARCH_MARKET",
        "trusted_timestamp_receipts_implemented": False,
        "real_time_binance_collector_implemented": False,
        "future_outcomes_accessible": False,
        "live_signal_publication_authorized": False,
        "live_order_submission_authorized": False,
        "production_engine_may_restart": False,
        "development_data_reused_as_independent": False,
    }
    return {**base, "protocol_sha256": _digest(base)}


def _valid_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == SHA_PATTERN_LENGTH
            and all(ch in "0123456789abcdef" for ch in value))


def make_synthetic_precommit(*, boundary_ms: int, receipt_ms: int,
                             market_reports: list[dict],
                             feature_source_hashes: dict,
                             previous_sha256: str = FIRST_PREVIOUS_SHA,
                             previous_boundary_ms: int | None = None) -> dict:
    """Seal one complete six-market *synthetic* WATCH observation batch.

    Not a trusted forward record. The caller could forge receipt_ms;
    production use requires a distinct independently timestamped
    append-only receipt service and audit of the actual source feed.
    """
    if type(boundary_ms) is not int or (not START_MS <= boundary_ms < END_MS
                                      or boundary_ms % STEP_MS != 0):
        raise ValueError("Boundary outside predeclared UTC prospective window")
    if (type(receipt_ms) is not int or
            not boundary_ms <= receipt_ms <= boundary_ms + RECEIPT_MAX_DELAY_MS):
        raise ValueError("Late, early or malformed time receipt claim")
    if not _valid_sha(previous_sha256):
        raise ValueError("Invalid prior observation digest")
    if previous_boundary_ms is None:
        if previous_sha256 != FIRST_PREVIOUS_SHA:
            raise ValueError("First packet must use genesis digest")
        if boundary_ms != START_MS:
            raise ValueError("Cannot silently omit initial frozen boundaries")
    elif (type(previous_boundary_ms) is not int or
          boundary_ms != previous_boundary_ms + STEP_MS or
          previous_sha256 == FIRST_PREVIOUS_SHA):
        raise ValueError("Noncontiguous or unverifiable prior observation chain")
    if (not isinstance(market_reports, list)
            or len(market_reports) != len(MARKETS)
            or not isinstance(feature_source_hashes, dict)
            or set(feature_source_hashes) != set(MARKETS)
            or not all(_valid_sha(x) for x in feature_source_hashes.values())):
        raise ValueError("All six markets and their feature digests are mandatory")

    reports_by_symbol = {}
    for report in market_reports:
        if not isinstance(report, dict):
            raise ValueError("Invalid market report")
        symbol = report.get("symbol")
        if symbol not in MARKETS or symbol in reports_by_symbol:
            raise ValueError("Missing, duplicate or unknown research market")
        watches = report.get("watch_hypotheses")
        if not isinstance(watches, list):
            raise ValueError("Full research hypothesis list required")
        unique = set()
        for hypothesis in watches:
            if not isinstance(hypothesis, dict):
                raise ValueError("Malformed research hypothesis")
            if (hypothesis.get("status") != RESEARCH_ONLY_STATUS
                    or hypothesis.get("symbol") != symbol
                    or hypothesis.get("as_of_ms") != boundary_ms
                    or hypothesis.get("source_sha256") != feature_source_hashes[symbol]
                    or hypothesis.get("expert") not in EXPERT_NAMES
                    or hypothesis.get("direction") not in ("LONG", "SHORT")
                    or hypothesis.get("publishable_signal") is not False
                    or hypothesis.get("executable_order") is not False
                    or hypothesis.get("entry_price") is not None
                    or hypothesis.get("stop_loss") is not None
                    or hypothesis.get("take_profit") is not None):
                raise ValueError("Noncausal, mismatched or actionable hypothesis")
            key = (hypothesis["expert"], hypothesis["direction"])
            if key in unique:
                raise ValueError("Duplicate expert direction")
            unique.add(key)
        reports_by_symbol[symbol] = sorted(unique)
    if set(reports_by_symbol) != set(MARKETS):
        raise ValueError("Omitted market")

    observations = []
    for symbol in MARKETS:
        active = reports_by_symbol[symbol]
        directions = sorted({direction for expert, direction in active
                             if expert == EXPERT})
        observations.append({
            "symbol": symbol,
            "feature_source_sha256": feature_source_hashes[symbol],
            "all_expert_watch_keys": [[expert, side] for expert, side in active],
            "candidate_directions": directions,
            "candidate_active": bool(directions),
        })
    base = {
        "schema": 1,
        "status": "SYNTHETIC_PRECOMMIT_NOT_TRUSTED_FORWARD_EVIDENCE",
        "protocol_sha256": frozen_forward_protocol()["protocol_sha256"],
        "candidate_source_sha256": STRATEGY_SHA,
        "boundary_ms": boundary_ms,
        "receipt_ms_untrusted_claim": receipt_ms,
        "previous_boundary_ms": previous_boundary_ms,
        "previous_batch_sha256": previous_sha256,
        "observations": observations,
        "market_count": len(observations),
        "training_performed": False,
        "market_prices_read": False,
        "future_labels_computed": False,
        "orders_authorized": False,
        "signals_authorized": False,
        "trusted_timestamp_receipt": False,
    }
    return {**base, "batch_sha256": _digest(base)}


def verify_synthetic_chain(packets: list[dict]) -> dict:
    """Verify every recorded packet link and complete six-market watch list."""
    if not isinstance(packets, list) or not packets:
        raise ValueError("Nonempty packet sequence required")
    previous_hash = FIRST_PREVIOUS_SHA
    previous_time = None
    for packet in packets:
        if not isinstance(packet, dict):
            raise ValueError("Invalid packet")
        digest = packet.get("batch_sha256")
        payload = {k: v for k, v in packet.items() if k != "batch_sha256"}
        if (not _valid_sha(digest) or _digest(payload) != digest
                or payload.get("previous_batch_sha256") != previous_hash
                or payload.get("previous_boundary_ms") != previous_time):
            raise ValueError("Packet modified or chain is broken")
        boundary = payload.get("boundary_ms")
        if type(boundary) is not int or (previous_time is None and boundary != START_MS
                                       or previous_time is not None
                                       and boundary != previous_time + STEP_MS):
            raise ValueError("Unrecorded or out-of-order 5m observation")
        observations = payload.get("observations")
        if (not isinstance(observations, list)
                or [x.get("symbol") for x in observations] != list(MARKETS)):
            raise ValueError("Missing a market observation")
        if payload.get("future_labels_computed") is not False:
            raise ValueError("Future outcomes smuggled into precommit")
        if (payload.get("trusted_timestamp_receipt") is not False
                or payload.get("status") !=
                "SYNTHETIC_PRECOMMIT_NOT_TRUSTED_FORWARD_EVIDENCE"):
            raise ValueError("Synthetic receipt falsely certified")
        previous_hash, previous_time = digest, boundary
    return {
        "status": "SYNTHETIC_CHAIN_STRUCTURE_PASS_NOT_CLOCK_ATTESTED",
        "packets": len(packets),
        "last_digest": previous_hash,
        "no_trading_authorization": True,
    }
