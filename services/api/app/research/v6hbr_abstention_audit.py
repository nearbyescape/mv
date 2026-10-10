"""As-of, counterfactual *shadow* evaluation of a mathematical abstention gate.

No portfolio mutation: original V4/H/B/R decisions, result accounting and
next-trade eligibility remain unchanged. Gate is evaluated separately on
candidate cohort accepted references. The only observation ledger is the V4
baseline's earlier *matured* proxy outcomes, never rejected hindsight winners.
BTC-only development is expected to fail the minimum sample gate.

DO NOT train this against August-September holdout or promote to live.
"""
from __future__ import annotations

from collections import Counter

from .v6hbr_math_abstention import evaluate_abstention
from .v6hbr_portfolio_replay import CLOSED
from .v6hbr_setup_taxonomy import validated_setup_type


def audit_mathematical_abstention(priced: list[dict],
                                 cohorts: dict[str, dict]) -> dict:
    ids = {r["id"]: r for r in priced}
    if len(ids) != len(priced):
        raise ValueError("Duplicate research candidate")
    if set(cohorts) != {"V4", "H", "B", "R"}:
        raise ValueError("Exactly four research cohorts required")
    ledger = []
    for candidate in cohorts["V4"]["accepted_ids"]:
        row = ids[candidate]
        validated_setup_type(row["setup_type"], row["lane"])
        out = row.get("outcome")
        if out is None:
            raise ValueError("Baseline accepted an unpriced reference")
        if out["status"] not in CLOSED:
            continue
        ledger.append({
            "id": candidate,
            "published_at_ms": row["at_ms"],
            "terminal_at_ms": out["terminal_at_ms"],
            "direction": row["direction"],
            "setup_type": row["setup_type"],
            "regime": row["regime"],
            "status": out["status"],
            "net_realized_r": out["net_realized_r"],
        })
    by_cohort = {}
    for cohort, report in cohorts.items():
        reasons = Counter()
        count_research_eligible = 0
        for candidate in report["accepted_ids"]:
            row = ids[candidate]
            validated_setup_type(row["setup_type"], row["lane"])
            gate = evaluate_abstention(
                signal_at_ms=row["at_ms"],
                direction=row["direction"],
                setup_type=row["setup_type"],
                regime=row["regime"],
                prior_outcomes=ledger,
            )
            reasons[gate["reason"]] += 1
            count_research_eligible += (
                gate["decision"] == "RESEARCH_ELIGIBLE_FOR_FURTHER_INDEPENDENT_TEST"
            )
        by_cohort[cohort] = {
            "original_accepted_count_UNCHANGED": len(report["accepted_ids"]),
            "mathematically_research_eligible": count_research_eligible,
            "would_abstain_without_validated_history": (
                len(report["accepted_ids"]) - count_research_eligible
            ),
            "reasons": dict(sorted(reasons.items())),
        }
    return {
        "status": "ASOF_SHADOW_ABSTENTION_NOT_NEW_PRODUCTION_COHORT",
        "v4_terminally_resolved_reference_history": len(ledger),
        "cohorts": by_cohort,
        "limitations": [
            "All normal V4/H/B/R published-reference decisions remain unchanged",
            "History consists of BTC-only baseline reference trades, not live Lighter fills",
            "Future terminal results are invisible until after their recorded end time",
            "Minimum 80 matched net trades across 20 UTC days is generally unreachable in this BTC-only pilot",
            "An abstaining score is not a demonstration of a superior profitable strategy",
        ],
    }
