"""V6HBR fixed shadow accuracy goal and coverage accounting (research only).

All original rule-qualified candidates are retained; shadow masks may reject
them based ONLY on features available at original signal publication.
No policy is optimized or selected based on these retrospective outcomes.

The April–May development split cannot certify the 80% goal. All masks and
criteria must be frozen before June–July validation data are first evaluated.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D
from datetime import datetime, timezone
from collections import defaultdict

from .v6hbr_directional_accuracy import wilson_95

HORIZON = "60"
TARGET_FRACTION = D("0.80")
MIN_OBSERVED = 100
MIN_DISTINCT_UTC_DAYS = 20
MIN_DISTINCT_PUBLICATION_BOUNDARIES = 60
MIN_MARKETS = 10
MIN_RETAINED_COVERAGE = D("0.20")

SUPPORTED = "DIRECTION_SUPPORTED_OVER_HURDLE"
OPPOSITE = "DIRECTION_OPPOSITE_OVER_HURDLE"
NEUTRAL = "NEUTRAL_WITHIN_HURDLE"
ALLOWED_OUTCOMES = frozenset((SUPPORTED, OPPOSITE, NEUTRAL))

POLICIES = (
    "ALL_ORIGINAL_CANDIDATES",
    "REJECT_15_IST_HOUR_ONLY",
    "ESTABLISHED_TREND_ONLY",
    "REJECT_15_IST_AND_REQUIRE_ESTABLISHED",
    "LONG_DIRECTION_ONLY",
)


def _policy_keeps(row: dict, policy: str) -> bool:
    """Decision-time fields only; outcomes and forward data are unavailable."""
    hour = row["ist_entry_hour"]
    regime = row["regime"]
    direction = row["direction"]
    if not isinstance(hour, str) or len(hour) != 5 or hour[-3:] != ":00":
        raise ValueError("Malformed candidate IST hour")
    hh = hour[:2]
    if not hh.isdigit() or not 0 <= int(hh) <= 23:
        raise ValueError("Unknown IST entry hour")
    if regime not in ("established", "emerging") or direction not in ("long", "short"):
        raise ValueError("Unexpected historical regime or direction")
    if policy == "ALL_ORIGINAL_CANDIDATES":
        return True
    if policy == "REJECT_15_IST_HOUR_ONLY":
        return hour != "15:00"
    if policy == "ESTABLISHED_TREND_ONLY":
        return regime == "established"
    if policy == "REJECT_15_IST_AND_REQUIRE_ESTABLISHED":
        return hour != "15:00" and regime == "established"
    if policy == "LONG_DIRECTION_ONLY":
        return direction == "long"
    raise ValueError("Unsupported frozen candidate selection experiment")


def _classification(row: dict) -> str | None:
    result = row["horizons"][HORIZON]
    if result["status"] == "CENSORED":
        return None
    if result["status"] != "OBSERVED":
        raise ValueError("Unsupported 60-minute reference observation")
    label = result["direction_classification"]
    if label not in ALLOWED_OUTCOMES:
        raise ValueError("Unsupported forward-direction classification")
    return label


def _detail(rows: list[dict], total_input: int) -> dict:
    observed = [x for x in rows if _classification(x) is not None]
    counts = Counter(_classification(x) for x in observed)
    n = len(observed)
    supported = counts[SUPPORTED]
    opposite = counts[OPPOSITE]
    neutral = counts[NEUTRAL]
    if n != supported + opposite + neutral:
        raise ValueError("Candidate accounting did not reconcile")
    low, high = wilson_95(supported, n)
    publication_boundaries = {(r["at_ms"]) for r in rows}
    days = {r["utc_day"] for r in rows}
    markets = {r["symbol"] for r in rows}
    frac = D(supported) / n if n else None
    eligible = (
        n >= MIN_OBSERVED
        and len(days) >= MIN_DISTINCT_UTC_DAYS
        and len(publication_boundaries) >= MIN_DISTINCT_PUBLICATION_BOUNDARIES
        and len(markets) >= MIN_MARKETS
        and D(len(rows)) / total_input >= MIN_RETAINED_COVERAGE
        and frac is not None and frac >= TARGET_FRACTION
        and low is not None and D(low) >= TARGET_FRACTION
    ) if total_input else False
    return {
        "candidate_references": len(rows),
        "observed_60m": n,
        "censored_60m": len(rows) - n,
        "correct_60m": supported,
        "wrong_60m": opposite,
        "neutral_60m": neutral,
        "correct_fraction_all_observed": str(frac) if frac is not None else None,
        "wrong_fraction_all_observed": str(D(opposite) / n) if n else None,
        "correct_fraction_decisive_only_NOT_PROMOTION_METRIC": (
            str(D(supported) / (supported + opposite)) if supported + opposite else None
        ),
        "marginal_wilson95_correct_fraction_NOT_INDEPENDENCE_ADJUSTED": [low, high],
        "retained_coverage_fraction_original": (
            str(D(len(rows)) / total_input) if total_input else None
        ),
        "distinct_utc_days": len(days),
        "distinct_publication_boundaries": len(publication_boundaries),
        "distinct_markets": len(markets),
        "meets_numerical_research_screen_NOT_LIVE_CERTIFICATION": eligible,
    }


def audit_80pct_shadow_research(labeled: list[dict]) -> dict:
    """Review all fixed decision-time masks, preserving rejected-good outcomes.

    The masks are descriptive April–May post-hoc hypotheses; identical results
    on this already inspected period have ZERO independent validation value.
    """
    if not isinstance(labeled, list):
        raise ValueError("Expected explicit frozen research candidate list")
    identities = set()
    for row in labeled:
        identity = (
            row["symbol"], row["at_ms"], row["lane"],
            row["setup_type"], row["direction"],
        )
        if identity in identities:
            raise ValueError("Duplicate directional reference identity")
        identities.add(identity)
        _classification(row)
        _policy_keeps(row, POLICIES[0])
        if not isinstance(row["at_ms"], int) or row["at_ms"] <= 0:
            raise ValueError("Malformed publication timestamp")
        actual_day = datetime.fromtimestamp(
            row["at_ms"] / 1000, timezone.utc
        ).date().isoformat()
        if row["utc_day"] != actual_day:
            raise ValueError("Candidate UTC day does not match publication")

    evaluations = {}
    n = len(labeled)
    for policy in POLICIES:
        kept = [r for r in labeled if _policy_keeps(r, policy)]
        rejected = [r for r in labeled if not _policy_keeps(r, policy)]
        if len(kept) + len(rejected) != n:
            raise ValueError("Coverage contradiction")
        evaluations[policy] = {
            "retained": _detail(kept, n),
            "rejected_counterfactual_NOT_BOOKED": _detail(rejected, n),
        }
    return {
        "status": "APRIL_MAY_EXPLORATORY_SHADOW_POLICY_AUDIT_NOT_TRADING_CERTIFICATION",
        "target_correct_fraction": str(TARGET_FRACTION),
        "horizon_minutes": 60,
        "required_min_observed": MIN_OBSERVED,
        "required_min_distinct_utc_days": MIN_DISTINCT_UTC_DAYS,
        "required_min_distinct_publication_boundaries": MIN_DISTINCT_PUBLICATION_BOUNDARIES,
        "required_min_markets": MIN_MARKETS,
        "required_min_retained_coverage_fraction": str(MIN_RETAINED_COVERAGE),
        "research_masks": evaluations,
        "promotion_decision": "NO_GO_DEVELOPMENT_SET_ALREADY_INSPECTED",
        "limitations": [
            "80% is a user-defined research target, not a forecast or attainable guarantee",
            "Percent correct counts every observed neutral as not correct; unresolved remains censored",
            "Wilson interval treats observations independently and is optimistic under shared market shocks",
            "The numerical screen is NOT a valid significance test or live trading readiness criterion",
            "April–May masks were specified after reviewing outcomes and cannot be scored as out of sample",
            "Selection of real trades requires separate accepted orders, 1m fill and cost replay",
            "Never tune, trade or certify strategy from this scorecard alone",
        ],
    }
