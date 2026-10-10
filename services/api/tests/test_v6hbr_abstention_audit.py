"""Mathematical gate is shadow-only and cannot rewrite BTC cohort membership."""
from copy import deepcopy

from app.research.v6hbr_abstention_audit import audit_mathematical_abstention

T = 1775016000000
M = 60_000


def _row(identity, at, *, net="0.5", status="TP3"):
    return {
        "id": identity,
        "symbol": "BTCUSDT",
        "at_ms": at,
        "direction": "long",
        "setup_type": "momentum_breakout",
        "regime": "established",
        "lane": "v4_base",
        "outcome": {
            "status": status,
            "terminal_at_ms": at + 10 * M if status == "TP3" else None,
            "net_realized_r": net if status == "TP3" else None,
        },
    }


def test_shadow_gate_counts_without_changing_real_cohort_decisions():
    rows = [_row("baseline", T), _row("candidate", T + 60*M)]
    cohorts = {
        "V4": {"accepted_ids": ["baseline"]},
        "H": {"accepted_ids": ["baseline", "candidate"]},
        "B": {"accepted_ids": ["candidate"]},
        "R": {"accepted_ids": ["candidate"]},
    }
    before = deepcopy((rows, cohorts))
    report = audit_mathematical_abstention(rows, cohorts)
    assert (rows, cohorts) == before
    assert report["v4_terminally_resolved_reference_history"] == 1
    assert report["cohorts"]["V4"]["original_accepted_count_UNCHANGED"] == 1
    assert report["cohorts"]["H"]["original_accepted_count_UNCHANGED"] == 2
    assert report["cohorts"]["H"]["mathematically_research_eligible"] == 0
    assert report["cohorts"]["H"]["would_abstain_without_validated_history"] == 2
    assert report["cohorts"]["H"]["reasons"]["INSUFFICIENT_INDEPENDENT_EVIDENCE"] == 2


def test_a_later_outcome_cannot_be_a_past_label():
    rows = [_row("baseline", T), _row("candidate", T + M)]
    # The candidate arrives before baseline has matured, even though the
    # evaluator was handed an eventual profitable future terminal result.
    cohorts = {name: {"accepted_ids": ["candidate"]}
               for name in ("V4", "H", "B", "R")}
    cohorts["V4"]["accepted_ids"] = ["baseline"]
    report = audit_mathematical_abstention(rows, cohorts)
    assert report["cohorts"]["H"]["reasons"] == {
        "INSUFFICIENT_INDEPENDENT_EVIDENCE": 1
    }


def test_open_baseline_does_not_fake_terminal_profit():
    rows = [_row("unfinished", T, status="OPEN_UNRESOLVED"),
            _row("candidate", T + 60*M)]
    cohorts = {
        "V4": {"accepted_ids": ["unfinished"]},
        "H": {"accepted_ids": ["candidate"]},
        "B": {"accepted_ids": ["candidate"]},
        "R": {"accepted_ids": ["candidate"]},
    }
    report = audit_mathematical_abstention(rows, cohorts)
    assert report["v4_terminally_resolved_reference_history"] == 0
    assert report["cohorts"]["B"]["mathematically_research_eligible"] == 0
