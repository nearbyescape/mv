"""Post-hoc V6HBR BTC research diagnostics; never part of signal selection.

Explain which baseline entries were absent in each independent cohort,
which accepted rescues demonstrably preceded their rejection, and which
candidate lanes contributed to the cost-scenario reference results.
No policy is changed; outcomes of rejected trades remain COUNTERFACTUAL.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

from .v6hbr_portfolio_replay import CLOSED

IST = ZoneInfo("Asia/Kolkata")
ACCEPTED = "ACCEPTED_REFERENCE"


def _day(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, timezone.utc).astimezone(IST).date().isoformat()


def _num(v) -> D:
    result = D(str(v))
    if not result.is_finite():
        raise ValueError("Nonfinite counterfactual net reference")
    return result


def diagnose(priced: list[dict], cohorts: dict[str, dict]) -> dict:
    """Analyze completed cohort audits without changing their decisions.

    Rescue 'blocker' labeling requires a supported causal link to an accepted
    earlier candidate, not merely that a rescue existed somewhere that day.
    """
    ids = {p["id"]: p for p in priced}
    if len(ids) != len(priced):
        raise ValueError("Duplicate priced candidate IDs")
    if set(cohorts) != {"V4", "H", "B", "R"}:
        raise ValueError("Exactly four independent cohorts are required")
    base_audit = cohorts["V4"]["audit"]
    baseline_ids = {
        x["id"] for x in base_audit
        if x["decision"] == ACCEPTED
    }
    for identity in baseline_ids:
        if ids[identity]["lane"] != "v4_base":
            raise ValueError("V4 baseline published a rescue")
    result = {"cohorts": {}, "balanced_rescue_filter_invariant": {}}
    for cohort, report in cohorts.items():
        audit = report["audit"]
        if len(audit) != len(priced) or {x["id"] for x in audit} != set(ids):
            raise ValueError("Audit does not cover exactly the priced candidate stream")
        by_id = {x["id"]: x for x in audit}
        accepted = [
            ids[x["id"]] for x in audit if x["decision"] == ACCEPTED
        ]
        if set(x["id"] for x in accepted) != set(report["accepted_ids"]):
            raise ValueError("Accepted audit contradicts reported cohort")
        lane_counts = Counter()
        lane_resolved = Counter()
        lane_unresolved = Counter()
        lane_net = {"v4_base": D(0), "15m_rescue": D(0)}
        lane_fees = {"v4_base": D(0), "15m_rescue": D(0)}
        lane_funding = {"v4_base": D(0), "15m_rescue": D(0)}
        lane_positive = Counter()
        lane_negative = Counter()
        for row in accepted:
            lane = row["lane"]
            out = row["outcome"]
            lane_counts[lane] += 1
            if out["status"] in CLOSED:
                lane_resolved[lane] += 1
                value = _num(out["net_realized_r"])
                lane_net[lane] += value
                lane_fees[lane] += _num(out.get("fee_debit_r", 0))
                lane_funding[lane] += _num(out.get("funding_debit_r", 0))
                lane_positive[lane] += value > 0
                lane_negative[lane] += value < 0
            elif out["status"] == "OPEN_UNRESOLVED":
                lane_unresolved[lane] += 1
        ignored_baseline = []
        for baseline in sorted(baseline_ids):
            state = by_id[baseline]
            if state["decision"] == ACCEPTED:
                continue
            row = ids[baseline]
            i = audit.index(state)
            accepted_before = [
                ids[past["id"]] for past in audit[:i] if past["decision"] == ACCEPTED
            ]
            reason = state["decision"]
            linked_rescues = []
            for prior in accepted_before:
                if prior["lane"] != "15m_rescue" or prior["at_ms"] > row["at_ms"]:
                    continue
                matches = (
                    reason == "SAME_DIRECTION_SIGNAL_THIS_SESSION"
                    and (prior["symbol"], prior["direction"], _day(prior["at_ms"]))
                    == (row["symbol"], row["direction"], _day(row["at_ms"]))
                ) or (
                    reason == "SYMBOL_ALREADY_ACTIVE"
                    and prior["symbol"] == row["symbol"]
                    and (
                        prior["outcome"]["status"] not in CLOSED
                        or prior["outcome"]["terminal_at_ms"] > row["at_ms"]
                    )
                ) or (
                    reason == "ROLLING_MARKET_DIRECTION_CONCENTRATION_LIMIT"
                    and prior["direction"] == row["direction"]
                    and row["at_ms"] - 3_600_000 < prior["at_ms"] <= row["at_ms"]
                )
                if matches:
                    linked_rescues.append(prior["id"])
            ignored_baseline.append({
                "v4_base_id": baseline,
                "at_ms": row["at_ms"],
                "rejection": reason,
                "earlier_accepted_rescue_blockers": linked_rescues,
                "has_demonstrated_rescue_blocker": bool(linked_rescues),
                "v4_counterfactual_net_r_if_resolved": (
                    row["outcome"]["net_realized_r"]
                    if row.get("outcome") is not None
                    and row["outcome"]["status"] in CLOSED
                    else None
                ),
                "counterfactual_not_booked": True,
            })
        outcome = {
            "accepted_by_lane": dict(sorted(lane_counts.items())),
            "resolved_by_lane": dict(sorted(lane_resolved.items())),
            "unresolved_by_lane": dict(sorted(lane_unresolved.items())),
            "resolved_net_r_by_lane": {k: str(v) for k, v in lane_net.items()},
            "resolved_fee_debit_r_by_lane": {k: str(v) for k, v in lane_fees.items()},
            "resolved_funding_debit_r_by_lane": {k: str(v) for k, v in lane_funding.items()},
            "resolved_positive_by_lane": dict(sorted(lane_positive.items())),
            "resolved_negative_by_lane": dict(sorted(lane_negative.items())),
            "missing_v4_base_count": len(ignored_baseline),
            "missing_v4_base_with_demonstrated_rescue_blocker": sum(
                item["has_demonstrated_rescue_blocker"] for item in ignored_baseline
            ),
            "missing_v4_base_by_reason": dict(sorted(Counter(
                item["rejection"] for item in ignored_baseline
            ).items())),
            "missing_v4_base_details": ignored_baseline,
        }
        if lane_net["v4_base"] + lane_net["15m_rescue"] != _num(report["resolved_net_r_sum"]):
            raise ValueError("Lane P&L attribution does not reconcile to cohort net R")
        result["cohorts"][cohort] = outcome
    eligible_rescues = [
        row for row in priced
        if row["lane"] == "15m_rescue"
        and row["regime"] == "emerging"
        and not row.get("preliminary_reason")
    ]
    extras = [
        row for row in eligible_rescues if row.get("balanced_reason") is not None
        or not row.get("balanced_confirmed")
    ]
    result["balanced_rescue_filter_invariant"] = {
        "emerging_rescues_priced": len(eligible_rescues),
        "newly_rejected_by_balanced": len(extras),
        "unexpected_rejection_ids": [x["id"] for x in extras],
        "expected_zero_due_to_inherited_trigger_conditions": True,
    }
    if extras:
        raise ValueError("Balanced unexpectedly vetoes a previously valid 15m rescue")
    result["hybrid_reserved_identical_accepted_ids"] = (
        cohorts["H"]["accepted_ids"] == cohorts["R"]["accepted_ids"]
    )
    result["status"] = "POST_HOC_PROXY_DIAGNOSTIC_NOT_CERTIFIED_TRADING_PERFORMANCE"
    return result
