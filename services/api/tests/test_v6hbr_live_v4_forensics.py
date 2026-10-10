"""The recent V4 audit must respect real production outcome timestamp conventions."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research.v6hbr_live_v4_forensics import analyze_live_v4

START = int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp() * 1000)
MINUTE = 60_000
END = START + 4 * 24 * 60 * MINUTE


def outcome(i, *, symbol="BTCUSDT", direction="long", status="stop",
            revised=False, adverse=2, favorable=None, observed=5, r="-1"):
    p = START + (i + 1) * 60 * MINUTE
    first = p + MINUTE
    return {
        "strategy": "MV-TREND-DUAL-v4", "symbol": symbol,
        "direction": direction, "setup_type": "momentum_breakout",
        "trend_regime": "established", "published_at": p,
        "first_observed_minute": first, "status": status,
        "observed_bars": observed, "source_revised": revised,
        "intrabar_ambiguous": False,
        # Production stores last millisecond of the finished candle.
        "adverse_050_at": first + adverse * MINUTE - 1 if adverse is not None else None,
        "favorable_050_at": first + favorable * MINUTE - 1 if favorable is not None else None,
        "mae_r": "0.7", "mfe_r": "0.6",
        "conservative_r": r,
    }


def test_recent_signal_opposition_is_separate_from_terminal_loss():
    rows = [
        outcome(1, r="-1", adverse=1, favorable=4),
        outcome(2, symbol="ETHUSDT", status="tp3", direction="short",
                r="1.55", favorable=1, adverse=5),
        outcome(3, symbol="SOLUSDT", status="tp3", r="1.55",
                adverse=1, favorable=2),
    ]
    before = deepcopy(rows)
    result = analyze_live_v4(rows, start_ms=START, end_ms=END)
    assert rows == before
    assert result["overall"]["published_reference_count"] == 3
    assert result["overall"]["resolved_count"] == 3
    assert result["overall"]["negative_resolved_count"] == 1
    assert result["overall"]["adverse_0p5r_first_or_tied"] == 2
    assert result["overall"]["adverse_0p5r_first_in_first_60m"] == 2
    assert result["by_symbol"]["ETHUSDT"]["adverse_0p5r_first_or_tied"] == 0
    assert result["by_direction"]["short"]["positive_resolved_count"] == 1


def test_source_revised_settled_signal_is_not_used_as_validated_trade():
    regular = outcome(1)
    revised = outcome(2, revised=True, r="-1")
    result = analyze_live_v4([regular, revised], start_ms=START, end_ms=END)
    overall = result["overall"]
    assert overall["published_reference_count"] == 2
    assert overall["source_revised_count"] == 1
    assert overall["usable_nonrevised_observed_count"] == 1
    assert overall["resolved_count"] == 1


def test_unresolved_and_unobserved_are_not_false_wins():
    open_row = outcome(1, status="open", r=None, adverse=None, favorable=None)
    empty = outcome(2, status="open", r=None, adverse=None, favorable=None,
                    observed=0)
    result = analyze_live_v4([open_row, empty], start_ms=START, end_ms=END)
    assert result["overall"]["published_reference_count"] == 2
    assert result["overall"]["resolved_count"] == 0
    assert result["overall"]["open_unresolved_count"] == 2
    assert result["overall"]["negative_fraction_of_resolved"] is None
    assert result["overall"]["mean_resolved_reference_r"] is None


def test_same_minute_tie_is_conservatively_adverse_first():
    row = outcome(1, adverse=1, favorable=1)
    result = analyze_live_v4([row], start_ms=START, end_ms=END)
    assert result["overall"]["adverse_0p5r_first_or_tied"] == 1


def test_reject_bogus_strategy_time_and_milestone_evidence():
    row = outcome(1)
    row["strategy"] = "MV-TREND-DUAL-v3"
    with pytest.raises(ValueError, match="Non-V4"):
        analyze_live_v4([row], start_ms=START, end_ms=END)
    row["strategy"] = "MV-TREND-DUAL-v4"
    row["adverse_050_at"] = row["first_observed_minute"] - 1
    with pytest.raises(ValueError, match="adverse_050_at"):
        analyze_live_v4([row], start_ms=START, end_ms=END)
    row["adverse_050_at"] = None
    row["observed_bars"] = 0
    row["favorable_050_at"] = row["first_observed_minute"] + 1
    with pytest.raises(ValueError, match="Milestones without"):
        analyze_live_v4([row], start_ms=START, end_ms=END)


def test_no_implicit_window_or_too_large_data_request():
    with pytest.raises(ValueError, match="31-day"):
        analyze_live_v4([], start_ms=START, end_ms=START + 40 * 24 * 60 * MINUTE)
