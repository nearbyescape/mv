"""Entry-direction failure diagnosis: no future leakage or invented full windows."""
from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from copy import deepcopy

import pytest

from app.research.v6hbr_entry_adversity import entry_adversity_report

MIN = 60_000
START = int(datetime(2026, 4, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)


def minute(t, h=100, l=100):
    return SimpleNamespace(open_time=t, open=D(100), high=D(str(h)),
                           low=D(str(l)), close=D(100))


def candidate(identity, t, *, direction="long", lane="v4_base",
              status="TP3", terminal=3, entry=100, risk=2):
    return {
        "id": identity, "lane": lane, "direction": direction, "at_ms": t - MIN,
        "outcome": {
            "status": status,
            "entry_at_ms": t,
            "terminal_at_ms": t + terminal * MIN if status == "TP3" else None,
            "entry_price_scenario": str(entry),
            "risk_distance_at_fill": str(risk),
            "net_realized_r": "0.1" if status == "TP3" else None,
        },
    }


def cohorts(ids):
    return {name: {"accepted_ids": list(values)}
            for name, values in ids.items()}


def test_adverse_first_then_reversal_truncates_15_30_60_minute_windows():
    bars = [
        minute(START, h=100.2, l=98.8),  # -0.6 R adverse first
        minute(START+MIN, h=101.5, l=99.0),  # +0.75 R later
        minute(START+2*MIN, h=101.8, l=99.6),
    ]
    rows = [candidate("1", START)]
    chosen = cohorts({"V4":["1"], "H":["1"], "B":["1"], "R":["1"]})
    before = deepcopy(chosen)
    out = entry_adversity_report(
        rows, bars, chosen, end_exclusive_ms=START+3*MIN
    )
    assert chosen == before
    for cohort in ("V4", "H", "B", "R"):
        observation = out["cohorts"][cohort]["windows"]["15"]["overall"]
        assert observation["accepted_entry_references"] == 1
        assert observation["complete_window_count"] == 0
        assert observation["closed_before_window_end"] == 1
        assert observation["adverse_first_or_same_minute_tie"] == 1
        assert observation["adverse_first_fraction_of_all_observed_entries"] == "1"
        detail = out["cohorts"][cohort]["entry_details"][0]["windows"]["15"]
        assert detail["observed_minutes"] == 3
        assert detail["max_adverse_r"] == "0.6"
        assert detail["max_favorable_r"] == "0.9"
        assert detail["first_0p5r_event"] == "ADVERSE_FIRST"


def test_same_candle_adverse_and_favorable_tie_is_adverse_first():
    bars = [minute(START, h=101.5, l=98.7)]
    rows = [candidate("same", START, terminal=1)]
    chosen = cohorts({name:["same"] for name in ("V4","H","B","R")})
    out = entry_adversity_report(rows, bars, chosen,
                                 end_exclusive_ms=START+MIN)
    detail = out["cohorts"]["V4"]["entry_details"][0]["windows"]["15"]
    assert detail["first_0p5r_event"] == "ADVERSE_FIRST"
    assert detail["adverse_0p5r_observed"]
    assert detail["favorable_0p5r_observed"]


def test_short_adverse_move_detected_as_price_rises():
    bars = [minute(START, h=101.2, l=99.8)]
    rows = [candidate("short", START, direction="short", terminal=1)]
    chosen = cohorts({name:["short"] for name in ("V4","H","B","R")})
    out = entry_adversity_report(rows, bars, chosen,
                                 end_exclusive_ms=START+MIN)
    detail = out["cohorts"]["R"]["entry_details"][0]["windows"]["15"]
    assert detail["first_0p5r_event"] == "ADVERSE_FIRST"
    assert detail["max_adverse_r"] == "0.6"


def test_open_unresolved_near_dataset_cutoff_is_marked_censored():
    t = START
    bars = [minute(t), minute(t+MIN)]
    rows = [candidate("unfinished", t, status="OPEN_UNRESOLVED")]
    chosen = cohorts({name:["unfinished"] for name in ("V4","H","B","R")})
    out = entry_adversity_report(rows, bars, chosen,
                                 end_exclusive_ms=t+2*MIN)
    obs = out["cohorts"]["H"]["windows"]["60"]["overall"]
    assert obs["complete_window_count"] == 0
    assert obs["dataset_censored_before_window_end"] == 1
    assert obs["neither_threshold"] == 1


def test_missing_minute_for_selected_entry_fails_closed():
    bars = [minute(START), minute(START+2*MIN)]
    rows = [candidate("gap", START)]
    chosen = cohorts({name:["gap"] for name in ("V4","H","B","R")})
    with pytest.raises(ValueError, match="Minute-gap"):
        entry_adversity_report(rows, bars, chosen, end_exclusive_ms=START+3*MIN)


def test_rejected_hindsight_winner_never_contributes_adversity():
    bars = [minute(START, h=103, l=99), minute(START+MIN), minute(START+2*MIN)]
    rows = [candidate("only", START), candidate("unpublished", START)]
    chosen = cohorts({name:["only"] for name in ("V4","H","B","R")})
    out = entry_adversity_report(rows, bars, chosen, end_exclusive_ms=START+3*MIN)
    assert out["cohorts"]["H"]["accepted_count"] == 1
    assert out["cohorts"]["H"]["entry_details"][0]["id"] == "only"


def test_reject_noncausal_terminal_and_missing_approved_execution():
    rows = [candidate("bad", START, terminal=3)]
    chosen = cohorts({name:["bad"] for name in ("V4","H","B","R")})
    rows[0]["outcome"]["terminal_at_ms"] = START+4*MIN
    with pytest.raises(ValueError, match="outside research window"):
        entry_adversity_report(rows, [minute(START)], chosen,
                               end_exclusive_ms=START+MIN)
    rows[0]["outcome"] = None
    with pytest.raises(ValueError, match="lacks executable"):
        entry_adversity_report(rows, [minute(START)], chosen,
                               end_exclusive_ms=START+MIN)
