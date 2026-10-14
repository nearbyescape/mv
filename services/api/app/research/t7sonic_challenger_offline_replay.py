"""Offline paper-only comparison of unchanged V7 and separate regime challenger.

Reads exact previously captured, certified four-boundary source packets.
It never connects to Binance, Telegram, PostgreSQL or an exchange account.
All outputs are retrospective and explicitly NOT tradable signals.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from app.research.t7sonic_release_candidate import indicative_plan
from app.research.t7sonic_regime_challenger import (
    NOT_FOR_CLIENTS, propose_paper_challenger, POLICY,
)
from app.research.t7sonic_replay import _as_of
from app.research.t7sonic_validation_plan import MARKETS
from app.v7sonic_pilot_recertify import recertify_pilot
from services.t7sonic.early_live_smoke import FRAMES, _parse
from services.t7sonic.forward_live_quote import (
    extract_contract_rule, parse_book_ticker,
)
from services.t7sonic.replay_original_capture import _decode, replay_original


def compare_saved_pilot(
    root_path: str, *, original_source_sha: str, first_boundary_ms: int,
) -> dict:
    root = Path(root_path)
    starts = tuple(first_boundary_ms + i*300_000 for i in range(4))
    proof = recertify_pilot(
        root, expected_sha=original_source_sha,
        expected_boundaries=starts,
    )
    baseline = Counter()
    challenger = Counter()
    rows = []

    for cycle in proof["cycles"]:
        boundary = cycle["boundary_ms"]
        summary_path = root / f"v7sonic-private-paper-cycle-{boundary}.json"
        summary = json.loads(summary_path.read_bytes())
        original_name = Path(
            summary["source_attempts"][-1]["original_http_file"]
        ).name
        original_path = root / original_name
        if (original_path.is_symlink() or not original_path.is_file()
                or not original_name.startswith("v7sonic-original-http-")
                or original_path.stat().st_size > 8_000_000):
            raise ValueError("Invalid original source evidence path")
        original = original_path.read_bytes()
        if sha256(original).hexdigest() != cycle["source_sha256"]:
            raise ValueError("Original source modified after certification")
        receipt = json.loads(original)
        source_proof = replay_original(receipt)
        if (source_proof["exact_reconciliation_passed"] is not True
                or source_proof["decision_boundary_ms"] != boundary):
            raise ValueError("Original source is incomplete or inconsistent")

        exchange = _decode(receipt["exchange_info_body"])
        for symbol in MARKETS:
            candles = {
                frame: _parse(
                    symbol, frame, boundary,
                    _decode(receipt["kline_bodies"][symbol][frame]),
                )
                for frame in FRAMES
            }
            snapshot = _as_of(candles, symbol, boundary)["snapshot"]
            venue = extract_contract_rule(exchange, symbol)
            quote, _ = parse_book_ticker(
                symbol, boundary, _decode(receipt["quote_bodies"][symbol]),
                venue,
                received_ms=receipt[
                    "quote_received_ms_local_clock_claim"
                ][symbol],
                evaluated_ms=receipt[
                    "recorded_ms_local_clock_claim"
                ],
            )
            baseline_plan = indicative_plan(snapshot, quote)
            challenger_plan = propose_paper_challenger(snapshot, quote)
            baseline[baseline_plan.get("reason", "QUALIFIED_PAPER")] += 1
            challenger[challenger_plan.get("reason", "QUALIFIED_PAPER")] += 1
            rows.append({
                "boundary_ms": boundary,
                "symbol": symbol,
                "baseline_status": baseline_plan["status"],
                "baseline_reason": baseline_plan.get("reason"),
                "challenger_status": challenger_plan["status"],
                "challenger_reason": challenger_plan.get("reason"),
                "challenger_expert": challenger_plan.get("expert"),
                "challenger_direction": challenger_plan.get("direction"),
                "challenger_net_r_if_filled": challenger_plan.get(
                    "weighted_exit_net_r_if_filled"
                ),
            })

    if len(rows) != 24 or sum(baseline.values()) != 24 or (
        sum(challenger.values()) != 24
    ):
        raise ValueError("Incomplete paper comparison")
    return {
        "status": "V7_OFFLINE_TWO_POLICY_PAPER_REPLAY_NO_CLIENT_PUBLICATION",
        "source_commit_operator_pin": original_source_sha,
        "original_manifest_sha256": proof["local_digests_manifest_sha256"],
        "source_cycles": 4,
        "decisions": 24,
        "baseline_qualified": baseline["QUALIFIED_PAPER"],
        "challenger_qualified": challenger["QUALIFIED_PAPER"],
        "baseline_reasons": dict(sorted(baseline.items())),
        "challenger_reasons": dict(sorted(challenger.items())),
        "challenger_policy": POLICY,
        "candidate_rows": rows,
        "retrospective_evaluation_only": True,
        "prospective_trade_accuracy_established": False,
        "exchange_fills_verified": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }


def main():
    p = argparse.ArgumentParser(description="Offline historical V7 comparison; never publish")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--original-source-sha", required=True)
    p.add_argument("--first-boundary-ms", required=True, type=int)
    args = p.parse_args()
    print(json.dumps(compare_saved_pilot(
        args.state_dir,
        original_source_sha=args.original_source_sha,
        first_boundary_ms=args.first_boundary_ms,
    ), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
