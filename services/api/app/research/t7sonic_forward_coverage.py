"""Phase 2R: synthetic-only fail-closed coverage and gap accounting.

A missing, stale or delayed market observation is NOT "no signal".
This pure offline component makes explicit gap packets and verifies a
continuous schedule mixing normal synthetic precommit and gap packets.

No filesystem, network, exchange, Telegram, orders, wall-clock assertions,
or outcome labels. SHA chaining is tamper-evidence only with an external
immutable/timestamped witness; this package does NOT provide such a witness.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json

from .t7sonic_forward_protocol import (
    START_MS, END_MS, STEP_MS, RECEIPT_MAX_DELAY_MS,
    FIRST_PREVIOUS_SHA, _digest, _valid_sha, frozen_forward_protocol,
)
from .t7sonic_validation_plan import MARKETS, STRATEGY_SHA, EXPERT
from .t7sonic_experts import EXPERT_NAMES

GAP_REASONS = frozenset({
    "SOURCE_UNAVAILABLE", "SOURCE_STALE", "SOURCE_INCOMPLETE",
    "RECEIPT_DEADLINE_MISSED", "ENGINE_FAILURE",
})
GAP_STATUS = "SYNTHETIC_GAP_NEVER_TREAT_AS_NO_WATCH"
WATCH_STATUS = "SYNTHETIC_PRECOMMIT_NOT_TRUSTED_FORWARD_EVIDENCE"
MAX_RECORD_DELAY_MS = STEP_MS * 2
PROTOCOL_SHA = frozen_forward_protocol()["protocol_sha256"]


def make_synthetic_gap(*, boundary_ms: int, recorded_ms: int,
                       missing_reasons: dict[str, str],
                       previous_sha256: str = FIRST_PREVIOUS_SHA,
                       previous_boundary_ms: int | None = None) -> dict:
    """One failed all-market decision cycle, with source-specific cause.

    At least one affected market is mandatory. Remaining markets are
    NOT_EVALUATED, never inferred as "no candidate". This is a synthetic
    protocol test fixture, not an actual witnessed missing cycle.
    """
    if (type(boundary_ms) is not int or
            not START_MS <= boundary_ms < END_MS or boundary_ms % STEP_MS):
        raise ValueError("Gap boundary outside fixed forward schedule")
    if (type(recorded_ms) is not int or recorded_ms < boundary_ms or
            recorded_ms > boundary_ms + MAX_RECORD_DELAY_MS):
        raise ValueError("Invalid synthetic gap recording timestamp")
    if (not isinstance(missing_reasons, dict) or not missing_reasons or
            not set(missing_reasons) <= set(MARKETS) or
            any(reason not in GAP_REASONS for reason in missing_reasons.values())):
        raise ValueError("Explicit enumerated reason per missing market is required")
    if not _valid_sha(previous_sha256):
        raise ValueError("Invalid previous packet sha256")
    if previous_boundary_ms is None:
        if previous_sha256 != FIRST_PREVIOUS_SHA or boundary_ms != START_MS:
            raise ValueError("Missing initial five-minute boundary")
    elif (type(previous_boundary_ms) is not int or
          boundary_ms != previous_boundary_ms + STEP_MS or
          previous_sha256 == FIRST_PREVIOUS_SHA):
        raise ValueError("Gap cannot hide skipped observation boundaries")
    observations = [{
        "symbol": symbol,
        "state": "DATA_MISSING" if symbol in missing_reasons
                 else "NOT_EVALUATED_DUE_TO_PARTIAL_SOURCE_FAILURE",
        "reason": missing_reasons.get(symbol),
        "watch_evaluation_performed": False,
        "candidate_directions": None,
    } for symbol in MARKETS]
    body = {
        "schema": 1,
        "status": GAP_STATUS,
        "protocol_sha256": PROTOCOL_SHA,
        "candidate_source_sha256": STRATEGY_SHA,
        "boundary_ms": boundary_ms,
        "recorded_ms_untrusted_claim": recorded_ms,
        "previous_boundary_ms": previous_boundary_ms,
        "previous_batch_sha256": previous_sha256,
        "observations": observations,
        "market_count": len(observations),
        "reasons_by_symbol": dict(sorted(missing_reasons.items())),
        "on_time_observation": False,
        "training_performed": False,
        "future_labels_computed": False,
        "orders_authorized": False,
        "signals_authorized": False,
        "trusted_timestamp_receipt": False,
    }
    return {**body, "batch_sha256": _digest(body)}


def _check_common(packet: dict, prior: str, prior_time: int | None) -> tuple[str, int]:
    if not isinstance(packet, dict):
        raise ValueError("Invalid packet structure")
    digest = packet.get("batch_sha256")
    body = {key: value for key, value in packet.items() if key != "batch_sha256"}
    t = body.get("boundary_ms")
    if (not _valid_sha(digest) or _digest(body) != digest or
            body.get("previous_batch_sha256") != prior or
            body.get("previous_boundary_ms") != prior_time):
        raise ValueError("Tampered record or broken SHA chain")
    if (type(t) is not int or
            (prior_time is None and t != START_MS) or
            (prior_time is not None and t != prior_time + STEP_MS) or
            t >= END_MS):
        raise ValueError("Skipped, repeated or out-of-window five-minute boundary")
    if (body.get("protocol_sha256") != PROTOCOL_SHA or
            body.get("candidate_source_sha256") != STRATEGY_SHA or
            body.get("market_count") != len(MARKETS) or
            body.get("training_performed") is not False or
            body.get("future_labels_computed") is not False or
            body.get("orders_authorized") is not False or
            body.get("signals_authorized") is not False or
            body.get("trusted_timestamp_receipt") is not False):
        raise ValueError("Invalid research-only protocol or trading restriction")
    obs = body.get("observations")
    if (not isinstance(obs, list) or len(obs) != len(MARKETS) or
            any(not isinstance(item, dict) for item in obs) or
            [item["symbol"] for item in obs] != list(MARKETS)):
        raise ValueError("Incomplete, unordered or duplicated six-market packet")
    return digest, t


def validate_synthetic_packet(item: dict, prev_sha: str,
                              prev_time: int | None) -> tuple[str, int, str]:
    """Validate one next packet, without repeatedly scanning prior history."""
    digest, t = _check_common(item, prev_sha, prev_time)
    status = item["status"]
    if status == WATCH_STATUS:
        receipt = item.get("receipt_ms_untrusted_claim")
        if (type(receipt) is not int or
                not t <= receipt <= t + RECEIPT_MAX_DELAY_MS or
                item.get("market_prices_read") is not False):
            raise ValueError("Missing timely synthetic WATCH receipt")
        for obs in item["observations"]:
            dirs = obs.get("candidate_directions")
            keys = obs.get("all_expert_watch_keys")
            if (not _valid_sha(obs.get("feature_source_sha256")) or
                    not isinstance(dirs, list) or
                    any(d not in ("LONG", "SHORT") for d in dirs) or
                    obs.get("candidate_active") is not bool(dirs) or
                    not isinstance(keys, list) or
                    any(not isinstance(k, list) or len(k) != 2 or
                            k[0] not in EXPERT_NAMES or
                            k[1] not in ("LONG", "SHORT") for k in keys) or
                    len({tuple(k) for k in keys}) != len(keys) or
                    dirs != sorted({side for expert, side in keys
                                    if expert == EXPERT})):
                raise ValueError("Malformed observed WATCH/no-WATCH state")
        category = "WATCH_CYCLE_COMPLETE"
    elif status == GAP_STATUS:
        claim = item.get("recorded_ms_untrusted_claim")
        reasons = item.get("reasons_by_symbol")
        if (type(claim) is not int or
                not t <= claim <= t + MAX_RECORD_DELAY_MS or
                item.get("on_time_observation") is not False or
                not isinstance(reasons, dict) or not reasons or
                not set(reasons) <= set(MARKETS) or
                any(reason not in GAP_REASONS for reason in reasons.values())):
            raise ValueError("Malformed missing-data gap receipt")
        for obs in item["observations"]:
            symbol = obs["symbol"]
            expected_state = ("DATA_MISSING" if symbol in reasons else
                              "NOT_EVALUATED_DUE_TO_PARTIAL_SOURCE_FAILURE")
            if (obs.get("state") != expected_state or
                    obs.get("reason") != reasons.get(symbol) or
                    obs.get("candidate_directions", "notset") is not None or
                    obs.get("watch_evaluation_performed") is not False):
                raise ValueError("Gap cannot be relabeled as NO_WATCH")
        category = "MISSING_DATA_CYCLE"
    else:
        raise ValueError("Unrecognized protocol event")
    return digest, t, category


def verify_synthetic_coverage(packets: list[dict]) -> dict:
    """Structural schedule audit; no trusted receipt time or source authentication."""
    if not isinstance(packets, list) or not packets:
        raise ValueError("Nonempty synthetic packet history required")
    prev_sha = FIRST_PREVIOUS_SHA
    prev_time = None
    tally = Counter()
    for item in packets:
        digest, t, category = validate_synthetic_packet(item, prev_sha, prev_time)
        tally[category] += 1
        prev_sha, prev_time = digest, t
    complete = tally["WATCH_CYCLE_COMPLETE"]
    missing = tally["MISSING_DATA_CYCLE"]
    return {
        "status": "SYNTHETIC_COVERAGE_STRUCTURE_PASS_NOT_TIMESTAMP_ATTESTED",
        "total_expected_through_last_boundary": len(packets),
        "complete_six_market_watch_cycles": complete,
        "missing_source_or_deadline_cycles": missing,
        "coverage_fraction": format(complete / len(packets), ".6f"),
        "last_boundary_ms": prev_time,
        "last_batch_sha256": prev_sha,
        "independently_timestamped": False,
        "real_exchange_data_verified": False,
        "signals_authorized": False,
        "orders_authorized": False,
    }

def make_external_witness_request(packet: dict) -> dict:
    """Prepare a digest-only witness request. DOES NOT contact a witness."""
    digest, boundary = _check_common(
        packet, packet.get("previous_batch_sha256"),
        packet.get("previous_boundary_ms")
    )
    return {
        "schema": 1,
        "status": "UNSUBMITTED_EXTERNAL_TIMESTAMP_REQUEST",
        "record_digest_sha256": digest,
        "boundary_ms": boundary,
        "protocol_sha256": PROTOCOL_SHA,
        "external_witness_service_configured": False,
        "receipt_signature_verified": False,
        "trusted_timestamp_receipt": False,
    }
