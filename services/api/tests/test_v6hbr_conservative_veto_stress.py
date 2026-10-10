"""Chronological veto experiments: block obvious predecision risk, not winners in hindsight."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D

import pytest

from app.research.v6hbr_conservative_veto_stress import (
    audit_conservative_veto_stress, veto_reason
)
from app.research.v6hbr_portfolio_replay import simulate_cohort

T = int(datetime(2026, 4, 1, 4, tzinfo=timezone.utc).timestamp() * 1000)
DAY = 86_400_000
HOUR = 3_600_000


def row(name, at, *, regime="established", setup="momentum_breakout",
        extension="0.5", net="-1"):
    return {
        "id": name, "symbol": name + "USDT", "lane": "v4_base",
        "at_ms": at, "context_open_ms": at - HOUR,
        "direction": "long", "setup_type": setup, "regime": regime,
        "recent_run_atr": "1.0", "source_extension_atr": extension,
        "balanced_confirmed": True,
        "outcome": {
            "status": "TP3" if D(net) > 0 else "STOP",
            "terminal_at_ms": at + HOUR,
            "net_realized_r": net,
            "adverse_050_at_ms": None,
            "favorable_050_at_ms": None,
            "exits": [],
        }
    }


def study(rows):
    original = {
        name: simulate_cohort(
            rows, name, risk_unit=D(1), max_aggregate_risk=D(10)
        ) for name in ("V4", "H", "B", "R")
    }
    result = audit_conservative_veto_stress(
        rows, original, risk_unit=D(1), max_aggregate_risk=D(10)
    )
    return original, result


def test_established_only_and_anti_chase_recompute_whole_cohorts():
    rows = [
        row("emerging", T, regime="emerging", net="-1"),
        row("extended", T+DAY, extension="1.5", net="-1"),
        row("healthy", T+2*DAY, setup="pullback_continuation",
            extension="0.7", net="1.2"),
    ]
    before = deepcopy(rows)
    original, stress = study(rows)
    assert rows == before
    assert original["V4"]["accepted_references"] == 3
    assert original["V4"]["resolved_net_r_sum"] == "-0.8"
    comparisons = stress["experiments"]
    established = comparisons["ESTABLISHED_REGIME_ONLY"]["cohorts"]["V4"]
    assert established["accepted_after_veto"] == 2
    assert established["net_r_after_veto_resolved_only"] == "0.2"
    breakout = comparisons["BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR"]["cohorts"]["H"]
    assert breakout["accepted_after_veto"] == 2
    assert breakout["net_r_after_veto_resolved_only"] == "0.2"
    combination = comparisons["ESTABLISHED_AND_NO_EXTENDED_BREAKOUT"]["cohorts"]["R"]
    assert combination["accepted_after_veto"] == 1
    assert combination["net_r_after_veto_resolved_only"] == "1.2"
    assert combination["original_accepted_missing"] == 2
    assert combination["newly_freed_capacity_acceptances"] == 0


def test_future_outcome_is_not_an_input_to_veto():
    candidate = row("breaker", T, regime="established", extension="1.2")
    original = veto_reason(candidate, "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR")
    candidate["outcome"]["net_realized_r"] = "100"
    assert veto_reason(candidate, "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR") == original
    assert original == "RESEARCH_LATE_BREAKOUT_EMA_EXTENSION"


def test_missing_asof_extension_fails_closed_instead_of_fallback():
    r = row("missing", T)
    del r["source_extension_atr"]
    with pytest.raises(ValueError, match="extension"):
        veto_reason(r, "ESTABLISHED_REGIME_ONLY")


def test_unrecognized_variant_is_never_silently_accepted():
    with pytest.raises(ValueError, match="experiment"):
        veto_reason(row("x", T), "TUNED_ON_HOLDOUT")


def test_premarked_ineligible_event_remains_disqualified_and_unmodified():
    r = row("blocked", T, regime="emerging")
    r["preliminary_reason"] = "UNAVAILABLE_SOURCE"
    before = deepcopy(r)
    _, out = study([r])
    assert r == before
    assert out["experiments"]["ESTABLISHED_REGIME_ONLY"][
        "cohorts"]["V4"]["rejections"]["UNAVAILABLE_SOURCE"] == 1



def test_real_15m_breakout_rescue_is_rejected_if_trigger_overextended():
    """Real rescue rank_extension is trigger 15m ATR, not an hourly feature."""
    r = row("rescue-breakout", T, extension="1.25")
    r["lane"] = "15m_rescue"
    r["setup_type"] = "momentum_breakout_15m"
    assert veto_reason(r, "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR") == (
        "RESEARCH_LATE_BREAKOUT_EMA_EXTENSION"
    )
    original, counterfactual = study([r])
    assert original["H"]["accepted_ids"] == ["rescue-breakout"]
    assert original["V4"]["accepted_ids"] == []
    changed = counterfactual["experiments"][
        "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR"
    ]["cohorts"]["H"]
    assert changed["accepted_after_veto"] == 0
    assert changed["original_accepted_missing"] == 1


def test_valid_15m_pullback_rescue_not_treated_as_breakout():
    r = row("rescue-pullback", T, extension="1.25")
    r["lane"] = "15m_rescue"
    r["setup_type"] = "pullback_continuation_15m"
    assert veto_reason(r, "BREAKOUT_EMA_EXTENSION_AT_MOST_ONE_ATR") is None


def test_mismatched_strategy_lane_is_not_pooled_with_hourly_v4():
    r = row("mismatch", T)
    r["lane"] = "15m_rescue"
    with pytest.raises(ValueError, match="V4 hourly setup"):
        veto_reason(r, "ESTABLISHED_REGIME_ONLY")
