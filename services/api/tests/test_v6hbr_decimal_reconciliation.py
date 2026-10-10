"""Strict ledger equality must survive different Decimal summation orders."""
from decimal import Decimal as D, localcontext

import pytest

from app.research.v6hbr_decimal_reconciliation import exact_reference_sum
from app.research.v6hbr_portfolio_replay import simulate_cohort
from app.research.v6hbr_attribution import diagnose
from test_v6hbr_portfolio_replay import T, HOUR, event, outcome


def test_decimal_sum_is_exact_across_lane_grouping_and_input_order():
    values = [
        "1.999999999999999999999999999",
        "0.0000000000000000000000000001",
        "-1.999999999999999999999999999",
    ]
    with localcontext() as ctx:
        ctx.prec = 28
        naive = sum((D(v) for v in values), D(0))
        assert naive != D("0.0000000000000000000000000001")
    expected = D("1E-28")
    assert exact_reference_sum(values) == expected
    assert exact_reference_sum(list(reversed(values))) == expected
    assert exact_reference_sum(values[0:1] + values[2:3]) + exact_reference_sum(
        values[1:2]
    ) == expected


def test_real_portfolio_and_attribution_both_exactly_reconcile_mixed_lanes():
    rows = [
        event(1, T, "v4_base",
              outcome=outcome(T, net="1.999999999999999999999999999")),
        event(2, T + HOUR, "15m_rescue",
              outcome=outcome(T + HOUR, net="0.0000000000000000000000000001")),
        event(3, T + 2*HOUR, "v4_base",
              outcome=outcome(T + 2*HOUR, net="-1.999999999999999999999999999")),
    ]
    cohorts = {
        name: simulate_cohort(
            rows, name, risk_unit=D(1), max_aggregate_risk=D(10)
        ) for name in ("V4", "H", "B", "R")
    }
    report = diagnose(rows, cohorts)
    assert cohorts["V4"]["resolved_net_r_sum"] == "0"
    for cohort in ("H", "B", "R"):
        assert cohorts[cohort]["accepted_ids"] == ["1", "2", "3"]
        assert D(cohorts[cohort]["resolved_net_r_sum"]) == D("1E-28")
        lane = report["cohorts"][cohort]["resolved_net_r_by_lane"]
        assert D(lane["v4_base"]) == 0
        assert D(lane["15m_rescue"]) == D("1E-28")
        assert D(cohorts[cohort]["resolved_net_r_sum"]) == (
            exact_reference_sum(lane.values())
        )


def test_accounting_real_mismatch_is_never_suppressed():
    rows = [event(1, T, "v4_base")]
    cohorts = {
        name: simulate_cohort(rows, name, risk_unit=D(1), max_aggregate_risk=D(10))
        for name in ("V4", "H", "B", "R")
    }
    cohorts["V4"]["resolved_net_r_sum"] = "0.5000000000000000000000000001"
    with pytest.raises(ValueError, match="discrepancy=-1E-28"):
        diagnose(rows, cohorts)


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", True, object()])
def test_invalid_and_nonfinite_amounts_fail_closed(bad):
    with pytest.raises(ValueError, match="amount"):
        exact_reference_sum([bad])


def test_empty_and_negative_decimal_amounts_preserved():
    assert exact_reference_sum([]) == 0
    assert exact_reference_sum(["-1.4", "0.40"]) == D("-1.00")
