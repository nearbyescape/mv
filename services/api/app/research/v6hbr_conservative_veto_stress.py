"""Pre-registered V6HBR conservative *veto-only* research experiments.

Purpose: quantify whether enforcing established 1h+4h trend, avoiding late
extended breakout entries, or combining both could actually IMPROVE net R.
These are simple causal filters using decision-time row fields only.
Unlike subtracting loser trades post hoc, EACH experiment independently
re-runs the full chronological portfolio reducer, so stopping a candidate
may release capacity for later V4 setups.

THRESHOLDS ARE FROZEN, NEVER FIT HERE. Development results cannot choose the
live rule; all out-of-sample validation and operator signoff remain mandatory.
"""
from __future__ import annotations

from decimal import Decimal as D, InvalidOperation

from .v6hbr_portfolio_replay import simulate_cohort

EXPERIMENTS = (
    "ESTABLISHED_REGIME_ONLY",
    "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR",
    "ESTABLISHED_AND_NO_EXTENDED_BREAKOUT",
)
MAX_BREAKOUT_EXTENSION_ATR = D("1.00")
VETO_REGIME = "RESEARCH_NOT_ESTABLISHED_REGIME"
VETO_EXTENSION = "RESEARCH_LATE_BREAKOUT_EMA_EXTENSION"


def _extension(row: dict) -> D:
    try:
        value = D(str(row["source_extension_atr"]))
    except (TypeError, ValueError, KeyError, InvalidOperation) as exc:
        raise ValueError("Missing or invalid at-decision EMA extension") from exc
    if not value.is_finite():
        raise ValueError("Nonfinite at-decision EMA extension")
    return value


def veto_reason(row: dict, experiment: str) -> str | None:
    """Fields read are known at publication: trend regime, setup and ATR.

    No outcome, future candle, terminal time, MFE/MAE or later trade status
    may affect this deterministic veto.
    """
    if experiment not in EXPERIMENTS:
        raise ValueError("Unrecognized predeclared experiment")
    if row["regime"] not in ("emerging", "established"):
        raise ValueError("Invalid trend regime")
    if row["setup_type"] not in ("momentum_breakout", "pullback_continuation"):
        raise ValueError("Invalid candidate setup")
    extension = _extension(row)
    if experiment in (
        "ESTABLISHED_REGIME_ONLY", "ESTABLISHED_AND_NO_EXTENDED_BREAKOUT"
    ) and row["regime"] != "established":
        return VETO_REGIME
    if experiment in (
        "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR",
        "ESTABLISHED_AND_NO_EXTENDED_BREAKOUT",
    ) and row["setup_type"] == "momentum_breakout" and extension > MAX_BREAKOUT_EXTENSION_ATR:
        return VETO_EXTENSION
    return None


def audit_conservative_veto_stress(
    priced: list[dict], baseline_cohorts: dict[str, dict],
    *, risk_unit: D, max_aggregate_risk: D
) -> dict:
    """Run independently priced and chronologically selected policy variants.

    Input pricing is FIXED and identical; candidate outcomes are only read by
    the unchanged portfolio reducer for already accepted positions.
    """
    if set(baseline_cohorts) != {"V4", "H", "B", "R"}:
        raise ValueError("V4/H/B/R baseline results required")
    before = {r["id"]: r for r in priced}
    if len(before) != len(priced):
        raise ValueError("Duplicate reference ID")
    results = {}
    for exp in EXPERIMENTS:
        changed = []
        veto_counts = {VETO_REGIME: 0, VETO_EXTENSION: 0}
        for original in priced:
            veto = veto_reason(original, exp)
            if original.get("preliminary_reason"):
                veto = None  # original disqualification always takes precedence
            if veto is not None:
                veto_counts[veto] += 1
            changed.append({
                **original,
                "preliminary_reason": original.get("preliminary_reason") or veto,
            })
        outcomes = {}
        for cohort in ("V4", "H", "B", "R"):
            report = simulate_cohort(
                changed, cohort, risk_unit=risk_unit,
                max_aggregate_risk=max_aggregate_risk,
            )
            original = baseline_cohorts[cohort]
            original_ids = set(original["accepted_ids"])
            alternative_ids = set(report["accepted_ids"])
            outcomes[cohort] = {
                "accepted_after_veto": report["accepted_references"],
                "resolved_after_veto": report["resolved_references"],
                "unresolved_after_veto": report["unresolved_references"],
                "net_r_after_veto_resolved_only": report["resolved_net_r_sum"],
                "original_net_r_resolved_only": original["resolved_net_r_sum"],
                "change_in_resolved_net_r_not_total_equity": str(
                    D(report["resolved_net_r_sum"]) -
                    D(original["resolved_net_r_sum"])
                ),
                "original_accepted_missing": len(original_ids - alternative_ids),
                "newly_freed_capacity_acceptances": len(alternative_ids - original_ids),
                "original_accepted_missing_ids": sorted(original_ids - alternative_ids),
                "newly_accepted_ids": sorted(alternative_ids - original_ids),
                "rejections": report["rejections"],
            }
        results[exp] = {
            "fixed_predecision_veto_counts": veto_counts,
            "cohorts": outcomes,
        }
    return {
        "status": "FIXED_RESEARCH_COUNTERFACTUALS_NOT_LIVE_STRATEGY_OPTIMIZATION",
        "extension_limit_atr": str(MAX_BREAKOUT_EXTENSION_ATR),
        "experiments": results,
        "limitations": [
            "Decisions are prospective but the BTC April-May results remain development, not independent validation",
            "Even positive net R here cannot select a final filter without frozen out-of-sample tests",
            "Execution-reference fills use modeled costs, not observed Lighter order book/funding",
            "Original live V4 strategy and baseline V4/H/B/R outcome records remain unchanged",
            "New capacity acceptances may move net R despite unchanged per-candidate outcome references",
        ],
    }
