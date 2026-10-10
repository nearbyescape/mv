"""Forward directional reference accuracy from immutable candidate events."""
from datetime import datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from app.research.v6hbr_directional_accuracy import (
    label_directional_events, summarize_directional_accuracy,
    directional_accuracy_study, wilson_95,
)

T = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp())*1000
Q = 900_000
HOUR = 3_600_000


def candle(t, o="100", h="102", l="99", c="101"):
    bar = SimpleNamespace(
        open_time=t, close_time=t+Q-1, open=D(o), high=D(h),
        low=D(l), close=D(c),
    )
    return SimpleNamespace(bar=bar)


def hour(t, close="100", atr="2"):
    return SimpleNamespace(
        bar=SimpleNamespace(close_time=t+HOUR-1, close=D(close)),
        atr=D(atr),
    )


def event(t=T, direction="long", lane="v4_base"):
    return {
        "symbol": "BTCUSDT", "at_ms": t,
        "direction": direction, "lane": lane,
        "context_open_ms": t-HOUR,
        "regime": "established", "setup_type": "momentum_breakout",
    }


def run(ev=None, bars=None, end=None, source=None):
    ev = ev or event()
    bars = bars or {T: candle(T)}
    source = source or {T-HOUR: hour(T-HOUR)}
    return label_directional_events(
        [ev], bars, source, end_exclusive_ms=end or T+Q
    )[0]


def test_long_direction_reversal_and_same_candle_adverse_first():
    out = run()
    h = out["horizons"]["15"]
    assert h["status"] == "OBSERVED"
    assert h["direction_classification"] == "DIRECTION_SUPPORTED_OVER_HURDLE"
    assert h["signed_mark_bps"] == "100"
    assert h["signed_mark_after_illustrative_hurdle_bps"] == "90"
    assert h["first_0p5atr_event"] == "ADVERSE_FIRST"
    assert h["max_adverse_atr"] == "0.5"
    assert h["max_favorable_atr"] == "1"
    assert out["horizons"]["30"]["status"] == "CENSORED"


def test_short_wrong_way_after_mark_and_0p5atr_adverse():
    out = run(ev=event(direction="short"))
    h = out["horizons"]["15"]
    assert h["direction_classification"] == "DIRECTION_OPPOSITE_OVER_HURDLE"
    assert h["signed_mark_bps"] == "-100"
    assert h["max_adverse_atr"] == "1"
    assert h["max_favorable_atr"] == "0.5"
    assert h["first_0p5atr_event"] == "ADVERSE_FIRST"


def test_neutral_move_is_not_silently_counted_correct():
    out = run(bars={T: candle(T, h="100.1", l="99.9", c="100.05")})
    assert out["horizons"]["15"]["direction_classification"] == "NEUTRAL_WITHIN_HURDLE"
    summary = summarize_directional_accuracy([out])
    assert summary["15"]["direction_supported_over_hurdle"] == 0
    assert summary["15"]["direction_neutral"] == 1
    assert summary["15"]["supported_fraction_of_all_observed"] == "0"
    assert summary["30"]["observed_count"] == 0
    assert summary["30"]["marginal_wilson95_supported_fraction"] == [None, None]


def test_missing_forward_candle_fails_closed_no_interpolation():
    data = {T: candle(T), T+2*Q: candle(T+2*Q)}
    with pytest.raises(ValueError, match="Missing or non-causal"):
        run(bars=data, end=T+3*Q)


def test_first_next_bar_missing_is_not_a_censored_success():
    with pytest.raises(ValueError, match="Missing first"):
        run(bars={T+Q: candle(T+Q)})


def test_unknown_source_and_future_source_raise():
    with pytest.raises(ValueError, match="1h source"):
        run(source={})
    future = {T-HOUR: hour(T-HOUR+HOUR)}
    with pytest.raises(ValueError, match="1h source"):
        run(source=future)


def test_illegal_duplicate_identifiers_rejected():
    one = event()
    with pytest.raises(ValueError, match="Duplicate"):
        label_directional_events(
            [one, one], {T: candle(T)}, {T-HOUR: hour(T-HOUR)},
            end_exclusive_ms=T+Q,
        )


def test_four_forward_horizons_and_censoring_at_exact_cutoff():
    bars = {
        T+i*Q: candle(T+i*Q, o="100", c=str(101+i), h=str(102+i), l="99")
        for i in range(8)
    }
    row = run(bars=bars, end=T+8*Q)
    assert all(row["horizons"][k]["status"] == "OBSERVED" for k in ("15","30","60","120"))
    truncated = run(bars=bars, end=T+7*Q)
    assert truncated["horizons"]["60"]["status"] == "OBSERVED"
    assert truncated["horizons"]["120"]["status"] == "CENSORED"


def test_grouping_and_wilson_bounds_are_not_imaginary_accuracy():
    correct = run()
    wrong = run(ev=event(direction="short"))
    result = directional_accuracy_study([correct, wrong])
    assert result["candidate_count"] == 2
    assert result["overall"]["15"]["direction_supported_over_hurdle"] == 1
    assert result["overall"]["15"]["direction_opposite_over_hurdle"] == 1
    assert result["overall"]["15"]["supported_fraction_of_all_observed"] == "0.5"
    assert result["by_lane"]["v4_base"]["15"]["observed_count"] == 2
    assert result["by_direction"]["long"]["15"]["direction_supported_over_hurdle"] == 1
    assert result["by_direction"]["short"]["15"]["direction_opposite_over_hurdle"] == 1
    low, high = wilson_95(1, 2)
    assert 0 < float(low) < 0.5 < float(high) < 1
    assert len(result["directional_evidence_sha256"]) == 64


def test_mixed_ohlc_invalid_geometry_is_not_labeled():
    with pytest.raises(ValueError, match="Invalid forward OHLCV"):
        run(bars={T: candle(T, h="99.9", l="99", c="101")})


def test_historical_candidate_generation_cannot_be_changed_by_future_prices():
    e = event()
    src = {T-HOUR: hour(T-HOUR)}
    before = dict(e)
    first = label_directional_events([e], {T: candle(T, c="101")}, src,
                                     end_exclusive_ms=T+Q)
    second = label_directional_events([e], {T: candle(T, c="99")}, src,
                                      end_exclusive_ms=T+Q)
    assert e == before
    assert first[0]["at_ms"] == second[0]["at_ms"] == T
    assert first[0]["direction"] == second[0]["direction"] == "long"
    assert first[0]["horizons"]["15"]["direction_classification"] != (
        second[0]["horizons"]["15"]["direction_classification"]
    )
