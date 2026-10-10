"""Pre-trade edge research gate never learns from future signals or trades."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research.v6hbr_math_abstention import (
    DAY_MS, evaluate_abstention
)

START = int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp() * 1000)
MINUTE = 60_000


def outcomes(net="0.5", *, days=25, per_day=4):
    rows = []
    for day in range(days):
        for j in range(per_day):
            published = START + day*DAY_MS + (j+2)*60*MINUTE
            rows.append({
                "id": f"reference-{day}-{j}",
                "published_at_ms": published,
                "terminal_at_ms": published+30*MINUTE,
                "direction": "long",
                "setup_type": "momentum_breakout",
                "regime": "established",
                "status": "TP3" if str(net).startswith(("0", "1", "2", "3", "4"))
                            else "STOP",
                "net_realized_r": net,
            })
    return rows


def evaluate(rows, when=None):
    return evaluate_abstention(
        signal_at_ms=when or START+26*DAY_MS,
        direction="long", setup_type="momentum_breakout",
        regime="established", prior_outcomes=rows,
    )


def test_missing_or_sparse_evidence_always_abstains():
    for rows in ([], outcomes(days=2), outcomes(days=19, per_day=4)):
        report = evaluate(rows)
        assert report["decision"] == "ABSTAIN"
        assert report["reason"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE"
        assert report["not_live_certified"]


def test_synthetic_positive_history_only_enables_more_research():
    rows = outcomes()
    before = deepcopy(rows)
    report = evaluate(rows)
    assert rows == before
    assert report["observed_resolved"] == 100
    assert report["distinct_utc_days"] == 25
    assert report["net_mean_r_lower_bootstrap"] == "0.5"
    assert report["decision"] == "RESEARCH_ELIGIBLE_FOR_FURTHER_INDEPENDENT_TEST"
    assert report["not_live_certified"]


def test_synthetic_all_loss_history_abstains():
    report = evaluate(outcomes("-0.5"))
    assert report["decision"] == "ABSTAIN"
    assert report["reason"] == "NO_SUPPORTED_NET_EDGE_AFTER_STRESS"
    assert report["net_mean_r_lower_bootstrap"] == "-0.5"


def test_future_data_and_unsettled_results_cannot_change_decision():
    rows = outcomes()
    reference = evaluate(rows)
    now = START+26*DAY_MS
    for future_r in ("200", "-100"):
        future = {
            **rows[0],
            "id": "future",
            "published_at_ms": now - DAY_MS,
            "terminal_at_ms": now + MINUTE,
            "net_realized_r": future_r,
        }
        still_open = {
            **rows[1], "id": "not-closed", "terminal_at_ms": None,
            "net_realized_r": "999999999",
        }
        next_signal = {
            **rows[2], "id": "tomorrow",
            "published_at_ms": now+DAY_MS,
            "terminal_at_ms": now+DAY_MS+MINUTE,
            "net_realized_r": future_r,
        }
        result = evaluate(rows + [future, still_open, next_signal], when=now)
        assert result == reference


def test_unbounded_loss_tail_fails_closed_no_winsorizing():
    rows = outcomes()
    rows[0]["net_realized_r"] = "-8"
    assert evaluate(rows)["reason"] == "UNCERTIFIED_TAIL_RISK"


def test_future_outcomes_with_invalid_results_do_not_pollute_history():
    rows = outcomes()
    future = {**rows[0], "id": "pending", "terminal_at_ms": START + 27*DAY_MS,
              "net_realized_r": "NOT_A_NUMBER"}
    assert evaluate(rows + [future]) == evaluate(rows)


def test_duplicated_identity_or_bad_timestamps_are_refused():
    rows = outcomes()
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate(rows + [rows[0]])
    rows[0]["terminal_at_ms"] = rows[0]["published_at_ms"]
    with pytest.raises(ValueError, match="chronology"):
        evaluate(rows)


def test_other_setup_or_regime_does_not_leak_a_positive_edge():
    rows = outcomes()
    for row in rows:
        row["regime"] = "emerging"
    report = evaluate(rows)
    assert report["reason"] == "INSUFFICIENT_INDEPENDENT_EVIDENCE"


def test_stale_observations_are_not_evidence_for_tomorrows_market():
    rows = outcomes()
    report = evaluate(rows, when=START+39*DAY_MS)
    assert report["reason"] == "RECENT_RESULTS_STALE"


def test_same_day_crowd_cannot_impersonate_independent_history():
    rows = outcomes(days=25, per_day=4)
    for j in range(20):
        p = START + 2*DAY_MS + (8+j)*MINUTE
        rows.append({
            **rows[0],
            "id": f"correlated-{j}",
            "published_at_ms": p,
            "terminal_at_ms": p + MINUTE,
        })
    report = evaluate(rows)
    assert report["reason"] == "SAME_DAY_CONCENTRATION"


def test_stop_side_or_fee_model_missing_cannot_claim_profit():
    rows = outcomes()
    rows[0]["net_realized_r"] = None
    with pytest.raises(ValueError, match="lacks cost-adjusted"):
        evaluate(rows)
    rows = outcomes()
    rows[0]["net_realized_r"] = "NaN"
    with pytest.raises(ValueError, match="Nonfinite"):
        evaluate(rows)
