"""Fail-closed V6HBR *research release-readiness* assessment.

No DB access, shell, Docker, GitHub API, deployment or strategy selection.
Passing this checklist does NOT deploy anything; it means a human may review
an evidence-backed release candidate. Every evidence boolean must be backed by
independently reviewed artifacts and provenance, not invented values.

Confidence interval of live-market expectancy and actual venue feasibility
cannot be inferred from the existing BTC April–May single-symbol cost proxy.
"""
from __future__ import annotations

from decimal import Decimal as D, InvalidOperation
from collections.abc import Mapping

MIN_VALIDATION_RESOLVED = 100
MIN_VALIDATION_SYMBOLS = 10
MIN_HOLDOUT_RESOLVED = 100
MIN_HOLDOUT_SYMBOLS = 10

PROOF_KEYS = (
    "immutable_source_archive_verified",
    "gh_ci_passed_for_exact_sha",
    "vps_regressions_passed_for_exact_sha",
    "recent_v4_failures_independently_audited",
    "complete_multisymbol_chronological_replay",
    "no_future_data_leakage_verified",
    "scenario_spread_slippage_fees_funding_verified",
    "cross_symbol_portfolio_risk_and_mtm_drawdown_audited",
    "no_unsafe_base_signal_crowdout",
    "asof_venue_tick_liquidity_and_order_filters_verified",
    "safe_rollback_and_operator_alert_plan_verified",
    "holdout_rules_frozen_before_unsealing",
    "validation_and_holdout_independent",
)
REQUIRED_METRICS = (
    "validation_resolved",
    "validation_symbols",
    "holdout_resolved",
    "holdout_symbols",
    "validation_net_r_after_costs",
    "holdout_net_r_after_costs",
    "validation_lower95_mean_net_r",
    "holdout_lower95_mean_net_r",
    "validation_stressed_net_r_after_costs",
    "holdout_stressed_net_r_after_costs",
    "candidate_mtm_max_drawdown_r",
    "baseline_mtm_max_drawdown_r",
)


def _number(value, field: str) -> D:
    # bool is a subclass of int, but cannot count as numerical evidence.
    if isinstance(value, bool):
        raise ValueError(field + " requires a numeric measured value")
    try:
        number = D(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(field + " must be a finite numeric measurement") from exc
    if not number.is_finite():
        raise ValueError(field + " must be a finite numeric measurement")
    return number


def assess_release_readiness(evidence: Mapping | None) -> dict:
    """Require independent positive *net* evidence without issuing trades.

    The thresholds are minimum research quality-control gates, not a forecast
    of signal accuracy. A satisfying self-reported manifest still needs
    independent inspection and explicit human approval for any production change.
    """
    reasons = []
    if not isinstance(evidence, Mapping):
        return {
            "decision": "NO_GO_FOR_LIVE_V6HBR",
            "reasons": ["EVIDENCE_MANIFEST_MISSING"],
            "can_auto_deploy": False,
            "can_claim_high_accuracy": False,
        }
    if evidence.get("schema") != 1:
        reasons.append("EVIDENCE_SCHEMA_NOT_VERIFIED")
    if evidence.get("candidate") != "V6HBR":
        reasons.append("CANDIDATE_IDENTITY_NOT_VERIFIED")
    sha = evidence.get("reviewed_commit_sha")
    if not (isinstance(sha, str) and len(sha) == 40
            and all(ch in "0123456789abcdef" for ch in sha)):
        reasons.append("REVIEWED_COMMIT_SHA_INVALID")
    if evidence.get("source_hashes_frozen") is not True:
        reasons.append("FROZEN_SOURCE_PROVENANCE_NOT_VERIFIED")
    if evidence.get("production_modified_by_research") is not False:
        reasons.append("RESEARCH_PRODUCTION_NONMUTATION_NOT_VERIFIED")
    for proof in PROOF_KEYS:
        if evidence.get(proof) is not True:
            reasons.append("MISSING_INDEPENDENT_PROOF:" + proof)
    if evidence.get("strategy_selected_using_holdout") is not False:
        reasons.append("HOLDOUT_CONTAMINATION_NOT_EXCLUDED")

    if evidence.get("data_scope") != "INDEPENDENT_MULTI_SYMBOL_VALIDATION_AND_HOLDOUT":
        reasons.append("INSUFFICIENT_DATA_SCOPE")
    # Always report rather than silently default any unmeasured metric to zero.
    values = {}
    for field in REQUIRED_METRICS:
        if field not in evidence:
            reasons.append("MISSING_METRIC:" + field)
            continue
        try:
            values[field] = _number(evidence[field], field)
        except ValueError:
            reasons.append("INVALID_METRIC:" + field)
    for field, bound in (
        ("validation_resolved", MIN_VALIDATION_RESOLVED),
        ("validation_symbols", MIN_VALIDATION_SYMBOLS),
        ("holdout_resolved", MIN_HOLDOUT_RESOLVED),
        ("holdout_symbols", MIN_HOLDOUT_SYMBOLS),
    ):
        value = values.get(field)
        if value is not None and (
            value != value.to_integral_value() or value < bound
        ):
            reasons.append("INSUFFICIENT_INDEPENDENT_SAMPLE:" + field)
    for field in (
        "validation_net_r_after_costs",
        "holdout_net_r_after_costs",
        "validation_lower95_mean_net_r",
        "holdout_lower95_mean_net_r",
        "validation_stressed_net_r_after_costs",
        "holdout_stressed_net_r_after_costs",
    ):
        value = values.get(field)
        if value is not None and value <= 0:
            reasons.append("NET_EXPECTANCY_NOT_DEMONSTRATED:" + field)
    candidate_dd = values.get("candidate_mtm_max_drawdown_r")
    baseline_dd = values.get("baseline_mtm_max_drawdown_r")
    if candidate_dd is not None and candidate_dd < 0:
        reasons.append("INVALID_CANDIDATE_DRAWDOWN")
    if baseline_dd is not None and baseline_dd < 0:
        reasons.append("INVALID_BASELINE_DRAWDOWN")
    if (candidate_dd is not None and baseline_dd is not None
            and candidate_dd > baseline_dd):
        reasons.append("DRAWDOWN_WORSE_THAN_V4")

    if evidence.get("operator_signoff") is not True:
        reasons.append("OPERATOR_SIGNOFF_MISSING")
    if evidence.get("independent_reviewer_signoff") is not True:
        reasons.append("INDEPENDENT_REVIEW_MISSING")

    return {
        "decision": ("ELIGIBLE_FOR_MANUAL_RELEASE_REVIEW_ONLY"
                     if not reasons else "NO_GO_FOR_LIVE_V6HBR"),
        "reasons": sorted(set(reasons)),
        "can_auto_deploy": False,
        "can_claim_high_accuracy": False,
        "policy": {
            "minimum_validation_resolved": MIN_VALIDATION_RESOLVED,
            "minimum_validation_symbols": MIN_VALIDATION_SYMBOLS,
            "minimum_holdout_resolved": MIN_HOLDOUT_RESOLVED,
            "minimum_holdout_symbols": MIN_HOLDOUT_SYMBOLS,
            "requires_positive_lower95_mean_net_r_after_costs": True,
            "requires_positive_stressed_scenario_r": True,
            "requires_nonworse_mtm_drawdown_vs_v4": True,
        },
        "limitations": [
            "Self-declared evidence is not an independent source of truth",
            "Research metrics alone cannot guarantee win rate or future net profitability",
            "This assessment never authorizes unattended deployment or trading",
        ],
    }
