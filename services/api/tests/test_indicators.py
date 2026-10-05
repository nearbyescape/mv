from dataclasses import replace
from decimal import Decimal, localcontext
from fractions import Fraction
import json

import pytest
from mv_strategy import Bar, IndicatorState, INTERVAL_MS, confirmation_open_time

D = Decimal
STEP = INTERVAL_MS["1h"]


def bars(count=510, timeframe="1h"):
    step = INTERVAL_MS[timeframe]
    result = []
    for i in range(count):
        close = D(100) + D(i) / 10 + D(i * i % 71) / 10
        opening = result[-1].close if result else close
        result.append(Bar(i * step, (i + 1) * step - 1, opening, max(opening, close) + 2, min(opening, close) - 2, close, D("123.456")))
    return result


def replay(source):
    state = IndicatorState("1h")
    outputs = [state.advance(bar) for bar in source]
    return state, outputs


def assert_fraction(actual, expected):
    with localcontext() as context:
        context.prec = 60
        exact = D(expected.numerator) / D(expected.denominator)
        assert abs(actual - exact) < D("1e-28")


def test_seed_indices_and_wilder_atr_hand_calculation():
    source = [Bar(i * STEP, (i + 1) * STEP - 1, D(10), D(11), D(9), D(10), D(1)) for i in range(50)]
    state, result = replay(source)
    assert result[12]["atr"] is None
    assert result[13]["atr"] is None  # first true range is candle 1, not candle 0
    assert result[14]["atr"] == D(2)
    assert result[18]["ema20"] is None
    assert result[19]["ema20"] == D(10)
    assert result[48]["ema50"] is None
    assert result[49]["ema50"] == D(10)
    state = IndicatorState("1h")
    for bar in source[:15]:
        state.advance(bar)
    out = state.advance(Bar(15 * STEP, 16 * STEP - 1, D(16), D(17), D(15), D(16), D(1)))
    assert_fraction(out["atr"], Fraction(33, 14))


def test_independent_rational_oracle_over_510_candles():
    source = bars()
    _, output = replay(source)
    closes = [Fraction(b.close) for b in source]
    for period, key in [(20, "ema20"), (50, "ema50")]:
        seed = sum(closes[:period]) / period
        alpha = Fraction(2, period + 1)
        decay = 1 - alpha
        # Expanded weighted sum, independent of the streaming recurrence implementation.
        expected = seed * decay ** (len(source) - period) + alpha * sum(closes[i] * decay ** (len(source) - 1 - i) for i in range(period, len(source)))
        assert_fraction(output[-1][key], expected)
    assert_fraction(output[-1]["sma200"], sum(closes[-200:]) / 200)
    tr = [max(Fraction(b.high - b.low), abs(Fraction(b.high) - closes[i - 1]), abs(Fraction(b.low) - closes[i - 1])) for i, b in enumerate(source) if i]
    expected_atr = sum(tr[:14]) / 14
    for value in tr[14:]:
        expected_atr = (13 * expected_atr + value) / 14
    assert_fraction(output[-1]["atr"], expected_atr)


@pytest.mark.parametrize("split", [1, 14, 15, 19, 20, 49, 50, 199, 200, 499])
def test_checkpoint_resume_is_bit_identical_to_uninterrupted_run(split):
    source = bars()
    full, _ = replay(source)
    partial, _ = replay(source[:split])
    restored = IndicatorState.restore(json.loads(json.dumps(partial.dump())))
    for bar in source[split:]:
        restored.advance(bar)
    assert restored.dump() == full.dump()


def test_reject_gap_duplicate_and_history_reversal_without_mutating_state():
    state, _ = replay(bars(30))
    checkpoint = state.dump()
    for bad in [bars(30)[-1], bars(32)[-1], bars(1)[0]]:
        with pytest.raises(ValueError, match="Non-contiguous"):
            state.advance(bad)
        assert state.dump() == checkpoint


@pytest.mark.parametrize("change", [
    {"close": D("NaN")}, {"high": D("Infinity")}, {"volume": D(-1)}, {"close": D(0)},
    {"open_time": 1}, {"close_time": 0}, {"low": D(150)}, {"close": 100.0}
])
def test_malformed_source_bars_are_rejected(change):
    with pytest.raises(ValueError):
        IndicatorState("1h").advance(replace(bars(1)[0], **change))


def test_precision_is_not_lost_to_float_or_display_rounding():
    source = [Bar(i * STEP, (i + 1) * STEP - 1, D("100000000000.000000123"), D("100000000000.000000133"), D("100000000000.000000113"), D("100000000000.000000123"), D(1)) for i in range(200)]
    _, output = replay(source)
    assert output[-1]["sma200"] == D("100000000000.000000123")
    assert output[-1]["atr"] == D("0.000000020")


@pytest.mark.parametrize("hour, expected_hour", [(1, -4), (4, 0), (7, 0), (8, 4), (23, 16), (24, 20)])
def test_completed_4h_alignment_uses_entry_boundary_not_arrival_order(hour, expected_hour):
    assert confirmation_open_time(hour * STEP) == expected_hour * STEP


def test_checkpoint_version_mismatch_is_rejected():
    state, _ = replay(bars(30))
    saved = state.dump()
    saved["precision"] = 28
    with pytest.raises(ValueError, match="Incompatible"):
        IndicatorState.restore(saved)
