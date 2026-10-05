from copy import deepcopy
from decimal import localcontext
from fractions import Fraction as F

import pytest
from mv_strategy.trade_diagnostics import diagnose, bucket

SPEC = {"atr_fraction_edges": ["0.01", "0.02"], "ema_gap_atr_edges": ["0.5", "1"], "aligned_ema50_slope_atr_edges": ["0", "0.05"]}


def trade(pnl="4", r="1", direction="long"):
    return {"symbol": "BTCUSDT", "direction": direction, "exit_reason": "ema50_exit", "source_close": 7_200_000,
            "net_pnl": pnl, "gross_pnl": str(int(pnl)+2), "fees": "3", "funding_pnl": "1", "net_r": r,
            "quantity": "2", "initial_risk_usdt": "4", "mae_observed": "1", "mfe_observed": "2",
            "evidence": {"source": {"open_time": 3_600_000, "atr": "2", "ema20": "99", "ema50": "95", "ohlcv": {"close": "100"}},
                         "previous": {"open_time": 0, "ema50": "94.9"}}}


def test_exact_cohort_boundaries_direction_and_independent_summary():
    rows = [trade(), trade("-2", "-0.5", "short")]
    result = diagnose(rows, SPEC)
    summary = result["summary"]
    assert summary["trades"] == 2
    assert F(summary["net_pnl"]) == 2 and F(summary["expectancy_usdt"]) == 1
    assert F(summary["expectancy_r"]) == F(".25") and F(summary["win_rate"]) == F(".5")
    assert F(summary["profit_factor"]) == 2
    assert F(summary["average_mae_r_observed"]) == F(".5")
    assert F(summary["average_mfe_r_observed"]) == 1
    assert summary["observed_at_least_1r"] == 2 and summary["losers_observed_at_least_1r"] == 1
    assert result["dimensions"]["atr_fraction"][0]["cohort"] == "2"
    assert result["dimensions"]["ema_gap_atr"][0]["cohort"] == "2"
    assert [r["cohort"] for r in result["dimensions"]["aligned_ema50_slope_atr"]] == ["0", "2"]
    for cohorts in result["dimensions"].values():
        assert sum(r["trades"] for r in cohorts) == 2
        assert sum(F(r["net_pnl"]) for r in cohorts) == 2


def test_diagnostics_do_not_depend_on_future_outcomes_to_classify_entries():
    before, after = trade(), trade()
    after.update(net_pnl="-200", net_r="-50", mae_observed="100", mfe_observed="0", exit_reason="stop")
    original, changed = diagnose([before], SPEC), diagnose([after], SPEC)
    for dimension in ("atr_fraction", "ema_gap_atr", "aligned_ema50_slope_atr"):
        assert original["dimensions"][dimension][0]["cohort"] == changed["dimensions"][dimension][0]["cohort"]


def test_empty_and_no_loss_are_honest_and_caller_precision_has_no_effect():
    empty = diagnose([], SPEC)["summary"]
    assert empty["trades"] == 0 and empty["expectancy_r"] is None and empty["profit_factor"] is None
    with localcontext() as context:
        context.prec = 5
        low = diagnose([trade()], SPEC)
    with localcontext() as context:
        context.prec = 50
        high = diagnose([trade()], SPEC)
    assert low == high and low["summary"]["profit_factor"] is None


@pytest.mark.parametrize("change", ["float", "nan", "risk", "atr", "future", "negative_excursion", "thresholds"])
def test_malformed_financial_evidence_cannot_become_diagnostics(change):
    row, spec = trade(), deepcopy(SPEC)
    if change == "float": row["net_pnl"] = 1.2
    elif change == "nan": row["net_pnl"] = "NaN"
    elif change == "risk": row["initial_risk_usdt"] = "0"
    elif change == "atr": row["evidence"]["source"]["atr"] = "0"
    elif change == "future": row["evidence"]["previous"]["open_time"] = 7_200_000
    elif change == "negative_excursion": row["mfe_observed"] = "-1"
    else: spec["ema_gap_atr_edges"] = ["1", "0.5"]
    with pytest.raises(ValueError): diagnose([row], spec)
