"""Accuracy target must not hide neutral calls, rejected winners, or thin volume."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research.v6hbr_80pct_shadow import (
    audit_80pct_shadow_research, POLICIES
)
from app.research.v6hbr_80pct_development import run_study

GOOD = "DIRECTION_SUPPORTED_OVER_HURDLE"
BAD = "DIRECTION_OPPOSITE_OVER_HURDLE"
NEUTRAL = "NEUTRAL_WITHIN_HURDLE"
T = int(datetime(2026, 4, 1, 9, 30, tzinfo=timezone.utc).timestamp() * 1000)


def row(i, label=GOOD, *, hour="15:00", direction="long",
        regime="established", symbol="BTCUSDT", censored=False):
    t = T + i * 86_400_000
    return {
        "symbol": symbol, "at_ms": t,
        "utc_day": datetime.fromtimestamp(t/1000, timezone.utc).date().isoformat(),
        "ist_entry_hour": hour,
        "regime": regime, "lane": "v4_base",
        "setup_type": "pullback_continuation", "direction": direction,
        "horizons": {"60": (
            {"status": "CENSORED", "reason": "RESEARCH_CUTOFF"} if censored else
            {"status": "OBSERVED", "direction_classification": label}
        )},
    }


def test_rejected_correct_calls_remain_visible_and_counts_reconcile():
    rows = [
        row(0, BAD),
        row(1, NEUTRAL),
        row(2, GOOD),
        row(3, GOOD, hour="16:00"),
        row(4, BAD, hour="16:00"),
    ]
    before = deepcopy(rows)
    result = audit_80pct_shadow_research(rows)
    assert rows == before
    all_data = result["research_masks"]["ALL_ORIGINAL_CANDIDATES"]["retained"]
    cut = result["research_masks"]["REJECT_15_IST_HOUR_ONLY"]
    assert all_data["observed_60m"] == 5
    assert all_data["correct_60m"] == 2
    assert all_data["wrong_60m"] == 2
    assert all_data["neutral_60m"] == 1
    assert cut["retained"]["correct_60m"] == 1
    assert cut["retained"]["wrong_60m"] == 1
    assert cut["rejected_counterfactual_NOT_BOOKED"]["correct_60m"] == 2
    assert cut["rejected_counterfactual_NOT_BOOKED"]["neutral_60m"] == 1
    assert result["promotion_decision"].startswith("NO_GO")


def test_80pct_is_not_certified_even_if_retrospective_percent_is_high():
    rows = [
        row(i, GOOD if i < 9 else BAD, hour="16:00")
        for i in range(10)
    ]
    result = audit_80pct_shadow_research(rows)
    score = result["research_masks"]["ALL_ORIGINAL_CANDIDATES"]["retained"]
    assert score["correct_fraction_all_observed"] == "0.9"
    assert score["meets_numerical_research_screen_NOT_LIVE_CERTIFICATION"] is False
    assert result["promotion_decision"] == "NO_GO_DEVELOPMENT_SET_ALREADY_INSPECTED"


def test_censored_not_silently_counted_or_changed_into_winner():
    rows = [row(0, GOOD), row(1, GOOD, censored=True)]
    a = audit_80pct_shadow_research(rows)["research_masks"]["ALL_ORIGINAL_CANDIDATES"]["retained"]
    assert a["candidate_references"] == 2
    assert a["correct_60m"] == 1
    assert a["observed_60m"] == 1
    assert a["censored_60m"] == 1


def test_selection_unaffected_by_any_future_historical_outcome():
    rows = [
        row(0, GOOD, hour="15:00"),
        row(1, BAD, hour="16:00", regime="emerging"),
        row(2, NEUTRAL, hour="17:00", direction="short"),
    ]
    a = audit_80pct_shadow_research(rows)["research_masks"]
    changed = deepcopy(rows)
    for r in changed:
        r["horizons"]["60"]["direction_classification"] = BAD
    b = audit_80pct_shadow_research(changed)["research_masks"]
    assert {
        p: a[p]["retained"]["candidate_references"] for p in POLICIES
    } == {
        p: b[p]["retained"]["candidate_references"] for p in POLICIES
    }


def test_duplicate_and_inconsistent_candidate_day_fail_closed():
    one = row(0)
    with pytest.raises(ValueError, match="Duplicate"):
        audit_80pct_shadow_research([one, deepcopy(one)])
    one["utc_day"] = "2039-01-01"
    with pytest.raises(ValueError, match="does not match"):
        audit_80pct_shadow_research([one])


def test_invalid_observation_and_hour_fail_closed():
    r = row(0)
    r["horizons"]["60"]["direction_classification"] = "MODEL_CORRECT_FOREVER"
    with pytest.raises(ValueError, match="classification"):
        audit_80pct_shadow_research([r])
    r["horizons"]["60"]["direction_classification"] = GOOD
    r["ist_entry_hour"] = "99:00"
    with pytest.raises(ValueError, match="Unknown IST"):
        audit_80pct_shadow_research([r])


def test_standalone_enforces_explicit_subset_not_full_universe(monkeypatch):
    from app.research import v6hbr_80pct_development as runner
    frozen = ["BTCUSDT","ETHUSDT"] + [f"TEST{i:02d}USDT" for i in range(28)]
    monkeypatch.setattr(runner, "load_spec",
                        lambda: ({"symbols": frozen}, "pinned"))
    def fake_audit(root, spec, spec_sha, symbol):
        return {"symbol": symbol, "candidate_count": 1, "v4_base": 1,
                "15m_rescue": 0, "labeled": [row(
                    0, hour="16:00", symbol=symbol
                )]}
    monkeypatch.setattr(runner, "audit_symbol", fake_audit)
    result = run_study("/research", ("BTCUSDT","ETHUSDT"))
    assert result["run_scope"] == "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE"
    assert result["complete_symbol_count"] == 2
    assert result["shadow_target"]["promotion_decision"].startswith("NO_GO")
