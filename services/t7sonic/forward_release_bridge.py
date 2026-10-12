"""Phase client-release bridge: offline 24 raw klines -> six paper plans.

Connects existing source-validation geometry to the new V7Sonic draft
planner. Does NOT make HTTPS requests, certify any receipt timestamp,
read live market orders, send Telegram messages or run production engine.
A failure in ANY of the six symbols aborts the whole decision boundary.
"""
from __future__ import annotations

from app.research.t7sonic_replay import _as_of
from app.research.t7sonic_perception import perceive_symbol
from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_release_preview import build_offline_preview
from services.t7sonic.forward_acquisition import (
    ROWS_BY_FRAME, parse_response_bytes, request_plan,
    assemble_offline_snapshot,
)


def preview_from_raw_market_responses(
    boundary_ms: int,
    source_responses: dict,
    quotes: list[dict],
    *, active_symbols: tuple[str, ...] = (),
    previously_seen_candidate_ids: tuple[str, ...] = (),
) -> dict:
    """One synchronous complete batch; no substitute missing-market candles."""
    if (not isinstance(source_responses, dict) or
            set(source_responses) != set(MARKETS)):
        raise ValueError("Six exact frozen markets are required")
    snapshots, proofs = [], {}
    for symbol in MARKETS:
        records = source_responses[symbol]
        if not isinstance(records, dict) or set(records) != set(ROWS_BY_FRAME):
            raise ValueError("Every market needs four native source responses")
        perception, receipt = assemble_offline_snapshot(
            symbol, boundary_ms, records
        )
        raw_frames = {}
        for frame in ROWS_BY_FRAME:
            planned, raw, status, received = records[frame]
            if planned != request_plan(symbol, frame, boundary_ms):
                raise ValueError("Raw-source query differs from frozen boundary")
            raw_frames[frame], _ = parse_response_bytes(
                planned, raw, http_status=status,
                receipt_ms_claim=received,
            )
        event = _as_of(raw_frames, symbol, boundary_ms)
        if (perceive_symbol(event["snapshot"])["feature_source_sha256"] !=
                perception["feature_source_sha256"]):
            raise ValueError("Source geometry proof inconsistent on replay")
        snapshots.append(event["snapshot"])
        proofs[symbol] = receipt

    result = build_offline_preview(
        snapshots, quotes, active_symbols=active_symbols,
        previously_seen_candidate_ids=previously_seen_candidate_ids,
    )
    return {
        **result,
        "status": "24_RAW_RESPONSE_OFFLINE_PAPER_PLANS_UNATTESTED",
        "source_geometry_checks": proofs,
        "raw_source_response_count": 24,
        "real_https_performed": False,
        "actual_exchange_source_authenticated": False,
        "external_clock_receipt_verified": False,
        "telegram_enqueued": False,
        "client_publication_authorized": False,
        "real_money_orders_authorized": False,
    }
