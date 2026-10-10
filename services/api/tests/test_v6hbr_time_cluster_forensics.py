"""Explore time clusters WITHOUT using outcomes to change candidate selection."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research.v6hbr_time_cluster_forensics import (
    hour_and_cross_market_forensics,
    SUPPORTED, OPPOSITE, NEUTRAL
)

Q = 900_000


def instant(month, day):
    # 09:45 UTC => 15:15 IST
    return int(datetime(2026, month, day, 9, 45,
                        tzinfo=timezone.utc).timestamp() * 1000)


def row(symbol, t, outcome=OPPOSITE, *, direction="long", lane="15m_rescue"):
    return {
        "symbol": symbol, "at_ms": t,
        "utc_day": datetime.fromtimestamp(t/1000,timezone.utc).date().isoformat(),
        "ist_entry_hour": "15:00",
        "lane": lane,
        "direction": direction,
        "setup_type": "pullback_continuation_15m" if lane == "15m_rescue"
                      else "pullback_continuation",
        "horizons": {"60": {
            "status": "OBSERVED",
            "direction_classification": outcome,
            "signed_mark_bps": "-116" if outcome == OPPOSITE else "34",
        }},
    }


def test_market_shared_wrong_way_entries_not_independent_utc_days():
    may = instant(5,4)
    april = instant(4,15)
    records = [
        row("BTCUSDT", may),
        row("ETHUSDT", may),
        row("BTCUSDT", april, SUPPORTED),
        row("ETHUSDT", april, NEUTRAL),
    ]
    before = deepcopy(records)
    x = hour_and_cross_market_forensics(records)
    assert records == before
    assert x["status"].startswith("EXPLORATORY")
    h = x["by_ist_hour"]["15:00"]
    overall = h["overall_60m"]
    assert overall["candidates"] == 4
    assert overall["distinct_utc_days"] == 2
    assert overall["distinct_publication_boundaries"] == 2
    assert overall["max_one_utc_day_candidate_count"] == 2
    assert overall["opposite_60m"] == 2
    assert overall["supported_60m"] == 1
    assert overall["neutral_60m"] == 1
    assert h["by_utc_month_60m"]["2026-04"]["candidates"] == 2
    assert h["by_utc_month_60m"]["2026-05"]["opposite_60m"] == 2
    assert h["by_direction_60m"]["long"]["candidates"] == 4
    assert h["by_direction_60m"]["short"]["candidates"] == 0
    shared = x["simultaneous_multi_symbol"]
    assert shared["unique_shared_publication_boundaries"] == 2
    assert shared["candidate_observations_sharing_multi_symbol_boundary"] == 4
    assert shared["shared_publications_with_two_or_more_wrong"] == 1
    assert shared["worst_shared_publications_first_12"][0]["at_ms"] == may
    assert {s["symbol"] for s in shared["worst_shared_publications_first_12"][0]["cases"]} == {
        "BTCUSDT", "ETHUSDT"
    }


def test_single_coin_reports_no_false_cross_coin_independence():
    a = hour_and_cross_market_forensics([row("BTCUSDT", instant(5,4))])
    assert a["simultaneous_multi_symbol"][
        "unique_shared_publication_boundaries"
    ] == 0
    assert a["by_ist_hour"]["15:00"]["overall_60m"]["candidates"] == 1


def test_censored_cannot_be_classified_as_a_60m_loss():
    case = row("BTCUSDT", instant(5, 4))
    case["horizons"]["60"] = {"status": "CENSORED", "reason": "RESEARCH_CUTOFF"}
    s = hour_and_cross_market_forensics([case])[
        "by_ist_hour"]["15:00"]["overall_60m"]
    assert s["candidates"] == 1
    assert s["observed_60m"] == 0
    assert s["censored_60m"] == 1
    assert s["supported_fraction_of_observed"] is None


def test_invalid_hour_and_forward_label_fail_closed():
    case = row("BTCUSDT", instant(5,4))
    case["ist_entry_hour"] = "14:00"
    with pytest.raises(ValueError, match="Inconsistent"):
        hour_and_cross_market_forensics([case])
    case["ist_entry_hour"] = "15:00"
    case["horizons"]["60"]["direction_classification"] = "INVALID_OUTCOME"
    with pytest.raises(ValueError, match="classification"):
        hour_and_cross_market_forensics([case])
