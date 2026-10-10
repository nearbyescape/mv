"""Post-hoc audit never attributes missing V4 entries to a rescue without a blocker."""
from decimal import Decimal as D

import pytest

from app.research.v6hbr_attribution import diagnose
from app.research.v6hbr_portfolio_replay import simulate_cohort
from test_v6hbr_portfolio_replay import T, Q, HOUR, event, outcome


def report(rows, cohort):
    return simulate_cohort(
        rows, cohort, risk_unit=D(1), max_aggregate_risk=D(10)
    )


def test_exact_rescue_dedupe_displacement_and_lane_net_attribution():
    rows = [
        event(1, T + Q, "15m_rescue"),
        event(2, T + HOUR, "v4_base", symbol="TEST1USDT"),
    ]
    cohorts = {name: report(rows, name) for name in ("V4", "H", "B", "R")}
    result = diagnose(rows, cohorts)
    assert result["cohorts"]["V4"]["accepted_by_lane"] == {"v4_base": 1}
    hybrid = result["cohorts"]["H"]
    assert hybrid["accepted_by_lane"] == {"15m_rescue": 1}
    assert hybrid["missing_v4_base_count"] == 1
    blocker = hybrid["missing_v4_base_details"][0]
    assert blocker["rejection"] == "SAME_DIRECTION_SIGNAL_THIS_SESSION"
    assert blocker["earlier_accepted_rescue_blockers"] == ["1"]
    assert blocker["counterfactual_not_booked"] is True
    assert result["hybrid_reserved_identical_accepted_ids"] is True


def test_balanced_base_filter_is_not_mislabeled_rescue_crowdout():
    rows = [event(1, T, "v4_base", regime="emerging",
                  balanced_reason="BALANCED_15M_NOT_ALIGNED")]
    cohorts = {name: report(rows, name) for name in ("V4", "H", "B", "R")}
    diagnostic = diagnose(rows, cohorts)
    b = diagnostic["cohorts"]["B"]
    assert b["missing_v4_base_count"] == 1
    assert b["missing_v4_base_by_reason"] == {"BALANCED_15M_NOT_ALIGNED": 1}
    assert b["missing_v4_base_with_demonstrated_rescue_blocker"] == 0


def test_new_balanced_rejection_of_triggered_rescue_fails_invariant():
    rows = [
        event(1, T + Q, "15m_rescue", regime="emerging",
              balanced_reason="BALANCED_15M_NOT_ALIGNED",
              balanced_confirmed=False)
    ]
    cohorts = {name: report(rows, name) for name in ("V4", "H", "B", "R")}
    with pytest.raises(ValueError, match="unexpectedly vetoes"):
        diagnose(rows, cohorts)


def test_counterfactual_unresolved_base_is_not_booked():
    rows = [
        event(1, T + Q, "15m_rescue"),
        event(2, T + HOUR, "v4_base", symbol="TEST1USDT",
              outcome=outcome(T + HOUR, status="OPEN_UNRESOLVED", net=None)),
    ]
    cohorts = {name: report(rows, name) for name in ("V4", "H", "B", "R")}
    details = diagnose(rows, cohorts)["cohorts"]["H"]["missing_v4_base_details"]
    assert details[0]["v4_counterfactual_net_r_if_resolved"] is None
    assert details[0]["counterfactual_not_booked"]


def test_fails_closed_on_cohort_net_r_inconsistency():
    rows = [event(1, T, "v4_base")]
    cohorts = {name: report(rows, name) for name in ("V4", "H", "B", "R")}
    cohorts["V4"]["resolved_net_r_sum"] = "999"
    with pytest.raises(ValueError, match="does not reconcile"):
        diagnose(rows, cohorts)
