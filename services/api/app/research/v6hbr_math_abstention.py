"""Mathematical, strictly as-of V6HBR research-only ABSTAIN gate.

Do not confuse a favorable indicator configuration with measured trading edge.
Require mature, *net-after-cost* reference outcomes from PAST trades with the
same direction, setup and regime. Group the history by UTC trading day so
correlated same-day signals cannot masquerade as independent observations.

One-sided 97.5% day-bootstrap lower bound must exceed a predeclared extra
0.10R adverse cost shock. This is an empirical RESEARCH screen, not a
guarantee or a formally valid confidence sequence under distribution shift.
No production path imports or calls this module.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation
from random import Random
from statistics import fmean

DAY_MS = 86_400_000
MIN_RESOLVED = 80
MIN_DAYS = 20
MAX_HISTORY_DAYS = 90
MAX_STALENESS_DAYS = 7
MAX_SINGLE_DAY_SHARE = D("0.15")
COST_SHOCK_R = D("0.10")
BOOTSTRAPS = 4096
ONE_SIDED_ALPHA = D("0.025")
MINUTE = 60_000


def _num(value: object, label: str) -> D:
    if isinstance(value, bool):
        raise ValueError(label + " must be numeric")
    try:
        number = D(str(value))
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("Invalid " + label) from exc
    if not number.is_finite():
        raise ValueError("Nonfinite " + label)
    return number


def _utc_day(at_ms: int) -> str:
    return datetime.fromtimestamp(at_ms / 1000, tz=timezone.utc).date().isoformat()


def evaluate_abstention(
    *,
    signal_at_ms: int,
    direction: str,
    setup_type: str,
    regime: str,
    prior_outcomes: list[dict],
) -> dict:
    """Evaluate only CLOSED and settled BEFORE the signal decision.

    Future/open trades do not count as evidence and cannot change this result.
    Historical records are labelled references, NOT actual Lighter fills.
    This helper never changes or publishes a trading signal.
    """
    if (type(signal_at_ms) is not int or signal_at_ms <= 0
            or signal_at_ms % MINUTE):
        raise ValueError("Signal must be at a completed full minute")
    if direction not in ("long", "short") or setup_type not in (
        "pullback_continuation", "momentum_breakout"
    ) or regime not in ("established", "emerging"):
        raise ValueError("Unrecognized predeclared research bucket")
    if not isinstance(prior_outcomes, list):
        raise ValueError("Input must be a finite historical list")

    seen = set()
    relevant = []
    for row in prior_outcomes:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Missing audit identity")
        if row["id"] in seen:
            raise ValueError("Duplicate reference outcome identity")
        seen.add(row["id"])
        published, terminal = row.get("published_at_ms"), row.get("terminal_at_ms")
        if type(published) is not int or published < 0:
            raise ValueError("Invalid publication time")
        if terminal is not None and (
            type(terminal) is not int or terminal <= published
        ):
            raise ValueError("Invalid terminal chronology")
        # Any future or still-open outcome is completely invisible here.
        if terminal is None or terminal >= signal_at_ms or published >= signal_at_ms:
            continue
        if terminal < signal_at_ms - MAX_HISTORY_DAYS * DAY_MS:
            continue
        if (row.get("direction"), row.get("setup_type"), row.get("regime")) != (
            direction, setup_type, regime
        ):
            continue
        if row.get("status") not in ("STOP", "PROTECTED_STOP", "TP3"):
            raise ValueError("Only fully resolved historical references allowed")
        if row.get("net_realized_r") is None:
            raise ValueError("Matured trade lacks cost-adjusted result")
        value = _num(row["net_realized_r"], "settled net R")
        # Fail closed for rare tails; NEVER winsorize or pretend outsized
        # negative events are capped. Such data needs separate tail analysis.
        if not D("-4") <= value <= D("4"):
            return {
                "decision": "ABSTAIN",
                "reason": "UNCERTIFIED_TAIL_RISK",
                "observed_resolved": len(relevant),
                "distinct_utc_days": None,
                "net_mean_r_lower_bootstrap": None,
                "cost_shock_r": str(COST_SHOCK_R),
                "not_live_certified": True,
            }
        relevant.append((terminal, _utc_day(published), value))

    days = defaultdict(list)
    for _, date, net in relevant:
        days[date].append(net)
    n, day_count = len(relevant), len(days)
    base = {
        "decision": "ABSTAIN", "observed_resolved": n,
        "distinct_utc_days": day_count,
        "net_mean_r_lower_bootstrap": None,
        "cost_shock_r": str(COST_SHOCK_R),
        "not_live_certified": True,
    }
    if n < MIN_RESOLVED or day_count < MIN_DAYS:
        return {**base, "reason": "INSUFFICIENT_INDEPENDENT_EVIDENCE"}
    if max(len(v) for v in days.values()) * D(1) / n > MAX_SINGLE_DAY_SHARE:
        return {**base, "reason": "SAME_DAY_CONCENTRATION"}
    if signal_at_ms - max(t for t, _, _ in relevant) > MAX_STALENESS_DAYS * DAY_MS:
        return {**base, "reason": "RECENT_RESULTS_STALE"}

    # Equal-day weighting: a flood of same-day correlated signals must not
    # dominate the resulting estimate. This deliberately differs from
    # trade-weighted portfolio PnL; both need independent reporting.
    daily_means = [float(sum(v, D(0)) / len(v))
                   for _, v in sorted(days.items())]
    observed = fmean(daily_means)
    rng = Random(690611)
    simulated = sorted(
        fmean(daily_means[rng.randrange(day_count)] for _ in range(day_count))
        for _ in range(BOOTSTRAPS)
    )
    lower_index = max(0, int(float(ONE_SIDED_ALPHA) * BOOTSTRAPS) - 1)
    lower = D(str(simulated[lower_index]))
    passed = lower > COST_SHOCK_R
    return {
        **base,
        "decision": "RESEARCH_ELIGIBLE_FOR_FURTHER_INDEPENDENT_TEST" if passed else "ABSTAIN",
        "reason": "LOWER_DAY_BOOTSTRAP_EDGE_AFTER_STRESS" if passed
                  else "NO_SUPPORTED_NET_EDGE_AFTER_STRESS",
        "observed_equal_day_mean_net_r": str(D(str(observed))),
        "net_mean_r_lower_bootstrap": str(lower),
        "bootstrap_unit": "UTC_DAY_EQUAL_WEIGHT",
        "bootstrap_replicates": BOOTSTRAPS,
        "one_sided_alpha": str(ONE_SIDED_ALPHA),
        "limitations": [
            "Reference outcomes are not actual trading fills or account PnL",
            "Day bootstrap is an exploratory stationary-day approximation, not an anytime-valid guarantee",
            "Historical selection or repeated testing can invalidate nominal confidence bounds",
            "Signal is NOT publishable based on this screen; independent validation required",
        ],
    }
