"""V7Sonic six-market dry-run handoff: no Telegram/DB/production writes.

Builds a single causal batch from exactly six completed 5-frame market
snapshots and six injected public quotes. Candidates are risk-defined but
NOT certified predictive signals. Idempotent preview receipt and fenced
presentation explicitly disable real publication.
"""
from __future__ import annotations

from hashlib import sha256
import json

from .t7sonic_release_candidate import indicative_plan, POLICY
from .t7sonic_validation_plan import MARKETS

DRY_RUN_STATUS = "OFFLINE_PAPER_PREVIEW_NOT_FOR_CLIENT_PUBLISHING"


def build_offline_preview(
    snapshots: list[dict],
    quotes: list[dict],
    *,
    active_symbols: tuple[str, ...] = (),
    previously_seen_candidate_ids: tuple[str, ...] = (),
) -> dict:
    """Reject gaps instead of treating a missing market as NO SIGNAL."""
    if (not isinstance(snapshots, list) or not isinstance(quotes, list)
            or len(snapshots) != len(MARKETS)
            or len(quotes) != len(MARKETS)):
        raise ValueError("Exactly six snapshots and six quotes are mandatory")
    if not all(isinstance(x, dict) for x in snapshots+quotes):
        raise ValueError("Malformed six-market snapshot/quote packet")
    if [p.get("symbol") for p in snapshots] != list(MARKETS):
        raise ValueError("Frozen market order and coverage required")
    if [q.get("symbol") for q in quotes] != list(MARKETS):
        raise ValueError("Every market must have its own quote")
    boundaries = {p.get("as_of_ms") for p in snapshots}
    if len(boundaries) != 1:
        raise ValueError("Mixed decision boundaries; do not backfill")
    if (not isinstance(previously_seen_candidate_ids, tuple) or
            any(not isinstance(x, str) or len(x) != 64
                for x in previously_seen_candidate_ids) or
            len(set(previously_seen_candidate_ids)) !=
            len(previously_seen_candidate_ids)):
        raise ValueError("Malformed previous candidate identifiers")
    plans = [
        indicative_plan(s, q, active_symbols=active_symbols)
        for s, q in zip(snapshots, quotes)
    ]
    proposals = []
    for plan in plans:
        if plan["status"].startswith("PAPER_INDICATIVE_"):
            duplicate = plan["candidate_id"] in previously_seen_candidate_ids
            proposals.append({
                **plan,
                "delivery_status": (
                    "SUPPRESSED_DUPLICATE_IN_OFFLINE_PREVIEW"
                    if duplicate else "PREVIEW_ONLY_NEVER_QUEUED"
                ),
            })
    absent = [
        {"symbol": p["symbol"], "reason": p["reason"]}
        for p in plans if p["status"] == "NO_CANDIDATE"
    ]
    digest = sha256(json.dumps({
        "policy": POLICY,
        "decision_boundary_ms": snapshots[0]["as_of_ms"],
        "source_hashes": [p["source_sha256"] for p in plans],
        "candidate_ids": [p["candidate_id"] for p in proposals],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": 1,
        "status": DRY_RUN_STATUS,
        "policy": POLICY,
        "decision_boundary_ms": snapshots[0]["as_of_ms"],
        "markets_expected": len(MARKETS),
        "markets_evaluated": len(plans),
        "no_candidate": absent,
        "indicative_candidates": proposals,
        "candidate_count": len(proposals),
        "batch_sha256": digest,
        "market_data_source_authenticated": False,
        "external_receipt_timestamp_verified": False,
        "live_inference_deployed": False,
        "telegram_enqueued": False,
        "client_publication_authorized": False,
        "real_money_orders_authorized": False,
    }


def format_explicit_test_message(candidate: dict) -> str:
    """Short internal test text. NEVER route to the client Telegram channel."""
    if (not isinstance(candidate, dict) or
            candidate.get("status") !=
                "PAPER_INDICATIVE_UNVERIFIED_NOT_FOR_CLIENT_PUBLICATION"
            or candidate.get("publishable_signal") is not False
            or candidate.get("executable_order") is not False
            or candidate.get("policy") != POLICY):
        raise ValueError("Only non-publishable paper candidates may be formatted")
    return (
        "V7Sonic · INTERNAL PAPER TEST — DO NOT TRADE\n"
        f"{candidate['direction']} {candidate['symbol']} · "
        f"{candidate['expert']}\n"
        f"Indicative entry: {candidate['entry']}\n"
        f"Stop (estimated): {candidate['stop_loss']}\n"
        f"TP1 / TP2: {candidate['take_profit_1']} / "
        f"{candidate['take_profit_2']}\n"
        f"Modeled net R if both 50/50 TPs fill: {candidate['estimated_net_rr_50_50_if_both_tps_filled']}\n"
        "UNVALIDATED research signal. No actual fill or profitable edge "
        "demonstrated. Not authorized for client publication."
    )
