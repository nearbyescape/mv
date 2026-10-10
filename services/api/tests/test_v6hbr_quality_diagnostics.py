"""V6HBR quality scorecard never selects candidates using their future returns."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.research.v6hbr_quality_diagnostics import quality_report

T = int(datetime(2026, 4, 1, 4, tzinfo=timezone.utc).timestamp() * 1000)
JUNE = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
M = 60_000


def trade(ident, at, *, lane="v4_base", net="1.2", gross="1.5",
          fees="0.2", funding="0.1", terminal=10, status="TP3",
          direction="long", regime="established"):
    return {
        "id": ident,
        "at_ms": at,
        "lane": lane,
        "direction": direction,
        "regime": regime,
        "outcome": {
            "status": status,
            "entry_at_ms": at + M,
            "terminal_at_ms": at + terminal * M if status == "TP3" else None,
            "gross_realized_r": gross,
            "fee_debit_r": fees,
            "funding_debit_r": funding,
            "net_realized_r": net if status == "TP3" else None,
            "intraminute_stop_first_ties": 0,
        },
    }


def cohorts(priced, ids):
    index = {x["id"]: x for x in priced}
    reports = {}
    for name, accepted in ids.items():
        resolved = [index[i] for i in accepted
                    if index[i]["outcome"]["status"] == "TP3"]
        unresolved = [i for i in accepted
                      if index[i]["outcome"]["status"] == "OPEN_UNRESOLVED"]
        reports[name] = {
            "accepted_ids": accepted,
            "resolved_references": len(resolved),
            "unresolved_references": len(unresolved),
            "resolved_net_r_sum": str(sum(
                (D(r["outcome"]["net_realized_r"]) for r in resolved), D(0)
            )),
        }
    return reports


def data():
    rows = [
        trade("gain", T),
        trade("loss", T + 15*M, lane="15m_rescue", net="-1.1",
              gross="-1.0", fees="0.1", funding="0",
              direction="short", regime="emerging"),
        trade("open", T + 30*M, lane="15m_rescue",
              status="OPEN_UNRESOLVED"),
        trade("rejected", T + 45*M, lane="15m_rescue",
              net="100", gross="100", fees="0", funding="0"),
    ]
    chosen = {
        "V4": ["gain"], "H": ["gain", "loss", "open"],
        "B": ["gain"], "R": ["gain", "loss"],
    }
    return rows, cohorts(rows, chosen)


def test_posthoc_metrics_use_only_settled_accepted_and_do_not_mutate():
    rows, policies = data()
    before = deepcopy((rows, policies))
    report = quality_report(rows, policies, end_exclusive_ms=JUNE)
    assert (rows, policies) == before
    assert report["status"] == "POST_HOC_COST_SCENARIO_QUALITY_NOT_LIVE_TRADING_PNL"
    h = report["cohorts"]["H"]
    stats = h["overall"]
    assert h["accepted_count"] == 3
    assert h["unresolved_count_excluded_from_pnl"] == 1
    assert stats["resolved_count"] == 2
    assert stats["positive_count"] == 1
    assert stats["negative_count"] == 1
    assert stats["resolved_net_r_sum"] == "0.1"
    assert stats["resolved_fee_debit_r_sum"] == "0.3"
    assert stats["resolved_funding_debit_r_sum"] == "0.1"
    assert h["terminal_only_drawdown"]["closed_peak_to_trough_drawdown_r"] == "1.1"
    assert h["terminal_only_drawdown"]["classification"].startswith("CLOSED_TERMINAL")
    assert h["by_group"]["lane"]["v4_base"]["resolved_count"] == 1
    assert h["by_group"]["lane"]["15m_rescue"]["resolved_count"] == 1
    assert list(h["by_entry_month_utc"]) == ["2026-04"]


def test_cost_sensitivity_is_conditional_on_fixed_entry_and_exit_paths():
    rows, policies = data()
    report = quality_report(rows, policies, end_exclusive_ms=JUNE)
    costs = report["cohorts"]["H"]["fixed_trade_fee_funding_multiplier_grid"]
    assert len(costs) == 9
    grid = {(e["fee_multiplier"], e["funding_multiplier"]):
            e["hypothetical_resolved_net_r_sum"] for e in costs}
    assert grid[("1", "1")] == "0.1"
    assert grid[("0", "0")] == "0.5"
    assert grid[("2", "2")] == "-0.3"
    # The 100R rejected hypothetical winner cannot leak into the results.
    rows[-1]["outcome"]["gross_realized_r"] = "2000"
    rows[-1]["outcome"]["net_realized_r"] = "2000"
    assert (quality_report(rows, policies, end_exclusive_ms=JUNE)
            ["cohorts"]["H"]["overall"]["resolved_net_r_sum"]) == "0.1"


def test_missing_entries_and_unresolved_are_not_reclassified_as_wins():
    rows, policies = data()
    rows[2]["outcome"]["net_realized_r"] = "5"
    with pytest.raises(ValueError, match="Unresolved"):
        quality_report(rows, policies, end_exclusive_ms=JUNE)
    rows[2]["outcome"]["net_realized_r"] = None
    empty = {k: {"accepted_ids": [], "resolved_references": 0,
                 "unresolved_references": 0, "resolved_net_r_sum": "0"}
             for k in ("V4", "H", "B", "R")}
    report = quality_report(rows, empty, end_exclusive_ms=JUNE)
    assert report["cohorts"]["V4"]["overall"]["resolved_count"] == 0
    assert report["cohorts"]["V4"]["overall"]["positive_fraction"] is None
    assert report["cohorts"]["V4"]["terminal_only_drawdown"]["closed_peak_to_trough_drawdown_r"] == "0"


def test_bad_terminal_time_and_bad_reconciliation_fail_closed():
    rows, policies = data()
    rows[0]["outcome"]["terminal_at_ms"] = JUNE + M
    with pytest.raises(ValueError, match="out-of-window"):
        quality_report(rows, policies, end_exclusive_ms=JUNE)
    rows[0]["outcome"]["terminal_at_ms"] = T + 10*M
    rows[0]["outcome"]["fee_debit_r"] = "-0.2"
    with pytest.raises(ValueError, match="reconciliation"):
        quality_report(rows, policies, end_exclusive_ms=JUNE)


def test_candidate_count_and_accounting_must_reconcile():
    rows, policies = data()
    policies["V4"]["resolved_net_r_sum"] = "100"
    with pytest.raises(ValueError, match="contradicts"):
        quality_report(rows, policies, end_exclusive_ms=JUNE)
    rows, policies = data()
    policies["B"]["unresolved_references"] = 1
    with pytest.raises(ValueError, match="Unresolved count"):
        quality_report(rows, policies, end_exclusive_ms=JUNE)



def test_quality_exact_net_reconciles_chronological_and_lane_grouped_decimals():
    """Reproduces the VPS production-history rounding class, not real fills."""
    from app.research.v6hbr_decimal_reconciliation import exact_reference_sum

    net_amounts = [
        "1.999999999999999999999999999",
        "0.0000000000000000000000000001",
        "-1.999999999999999999999999999",
    ]
    data_rows = [
        trade(
            "base-win", T, net=net_amounts[0], gross=net_amounts[0],
            fees="0", funding="0",
        ),
        trade(
            "rescue-tiny", T + 20*M, lane="15m_rescue",
            net=net_amounts[1], gross=net_amounts[1],
            fees="0", funding="0",
        ),
        trade(
            "base-loss", T + 40*M, net=net_amounts[2], gross=net_amounts[2],
            fees="0", funding="0",
        ),
    ]
    original_net = exact_reference_sum(net_amounts)
    assert original_net == D("1E-28")
    observed_ids = [r["id"] for r in data_rows]
    policies = {
        name: {
            "accepted_ids": observed_ids[:],
            "resolved_references": 3,
            "unresolved_references": 0,
            "resolved_net_r_sum": str(original_net),
        } for name in ("V4", "H", "B", "R")
    }
    result = quality_report(data_rows, policies, end_exclusive_ms=JUNE)
    for name, cohort in result["cohorts"].items():
        assert D(cohort["overall"]["resolved_net_r_sum"]) == original_net, name
        assert D(cohort["terminal_only_drawdown"]["resolved_closed_net_r_sum"]) == original_net
        assert exact_reference_sum(
            D(s["resolved_net_r_sum"])
            for s in cohort["by_group"]["lane"].values()
        ) == original_net
        baseline = next(
            r for r in cohort["fixed_trade_fee_funding_multiplier_grid"]
            if r["fee_multiplier"] == "1" and r["funding_multiplier"] == "1"
        )
        assert D(baseline["hypothetical_resolved_net_r_sum"]) == original_net
    # Corrupt an independently supplied portfolio result and prove there is
    # no fuzzy epsilon that could mask a real difference.
    policies["H"]["resolved_net_r_sum"] = "0"
    with pytest.raises(ValueError, match=r"cohort=H.*discrepancy=1E-28"):
        quality_report(data_rows, policies, end_exclusive_ms=JUNE)


def test_quality_fixed_cost_one_by_one_uses_recorded_booked_net():
    """The no-change cost scenario must equal the original booked ledger."""
    from app.research.v6hbr_quality_diagnostics import _cost_sensitivity

    # Deliberately supply a fee/gross/net triple created under finite 28-digit
    # execution rounding. Its recorded net is the source of truth.
    records = [{
        "gross": D("1.999999999999999999999999999"),
        "fees": D("0.0000000000000000000000000001"),
        "funding": D("0"),
        "net": D("1.999999999999999999999999999"),
    }]
    grid = _cost_sensitivity(records)
    fixed = next(x for x in grid if
                 x["fee_multiplier"] == "1" and x["funding_multiplier"] == "1")
    assert D(fixed["hypothetical_resolved_net_r_sum"]) == records[0]["net"]
