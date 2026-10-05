from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction
import pytest

from mv_strategy import Bar, INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import Snapshot, Quote, PriceFilter, PlanRejected, build_plan, evaluate_setup, decision_id

STEP = INTERVAL_MS["1h"]
BOUNDARY = 1791046800000


def snapshot(timeframe="1h", previous=False, direction="long"):
    open_time = BOUNDARY - STEP * (2 if previous else 1) if timeframe == "1h" else confirmation_open_time(BOUNDARY)
    count = 500 if previous else 501
    fast, slow, trend = (D("100"), D("99"), D("98")) if direction == "long" else (D("100"), D("101"), D("102"))
    close = D("99.9") if previous and direction == "long" else D("100.1") if previous else D("100.1") if direction == "long" else D("99.9")
    bar = Bar(open_time, open_time + INTERVAL_MS[timeframe] - 1, close, D(103), D(97), close, D(1))
    return Snapshot(timeframe, bar, fast, slow, trend, D("0.62"), count, open_time - (count - 1) * INTERVAL_MS[timeframe], "test-lineage")


def quote(now=BOUNDARY + 1000, bid="99.85", ask="100.10"):
    return Quote("BTCUSDT", D(bid), D(ask), D(1), D(2), now - 100, now)


@pytest.mark.parametrize("direction", ["long", "short"])
def test_mirrored_reclaims_require_exact_completed_4h(direction):
    source, previous, confirmation = snapshot(direction=direction), snapshot(previous=True, direction=direction), snapshot("4h", direction=direction)
    result = evaluate_setup(source, previous, confirmation)
    assert result.outcome == direction.upper() + "_SETUP"
    assert result.direction == direction
    assert all(check["passed"] for check in result.checks if check["id"].startswith(direction + "."))
    assert evaluate_setup(source, previous, None).reason == "WAITING_EXPECTED_4H"
    older = replace(confirmation, bar=replace(confirmation.bar, open_time=confirmation.bar.open_time - INTERVAL_MS["4h"], close_time=confirmation.bar.close_time - INTERVAL_MS["4h"]), history_origin=confirmation.history_origin - INTERVAL_MS["4h"])
    assert evaluate_setup(source, previous, older).reason == "WAITING_EXPECTED_4H"


@pytest.mark.parametrize("change", ["steady", "equal_order", "equal_close", "wick_only", "mixed"])
def test_steady_trends_equality_wicks_and_mixed_order_produce_no_setup(change):
    source, previous = snapshot(), snapshot(previous=True)
    if change == "steady":
        previous = replace(previous, bar=replace(previous.bar, close=D("100.2")))
    elif change == "equal_order":
        source = replace(source, ema50=source.ema20)
    elif change in ("equal_close", "wick_only"):
        source = replace(source, bar=replace(source.bar, close=D(100) if change == "equal_close" else D("99.9")))
    else:
        source = replace(source, sma200=D(101))
    assert evaluate_setup(source, previous, snapshot("4h")).outcome == "NO_SETUP"


def test_previous_equality_qualifies_but_4h_close_equality_does_not():
    previous = snapshot(previous=True)
    previous = replace(previous, bar=replace(previous.bar, close=previous.ema20))
    assert evaluate_setup(snapshot(), previous, snapshot("4h")).outcome == "LONG_SETUP"
    confirmation = snapshot("4h")
    confirmation = replace(confirmation, bar=replace(confirmation.bar, close=confirmation.ema20))
    assert evaluate_setup(snapshot(), previous, confirmation).reason == "4H_CONFIRMATION_FAILED"


@pytest.mark.parametrize("direction", ["long", "short"])
def test_independent_fraction_risk_rounding_on_offset_quarter_tick(direction):
    source = snapshot(direction=direction)
    source = replace(source, bar=replace(source.bar, close=D("100.10" if direction == "long" else "99.85")))
    actual = build_plan("BTCUSDT", direction, source, quote(), PriceFilter(D("0.25"), D("0.10"), D(200)), BOUNDARY + 1000)
    entry, atr, origin, tick = Fraction(actual["entry"]), Fraction("0.62"), Fraction("0.10"), Fraction("0.25")
    raw = entry + (2 * atr if direction == "short" else -2 * atr)
    units = (raw - origin) / tick
    rounded_units = -((-units.numerator) // units.denominator) if direction == "short" else units.numerator // units.denominator
    stop = origin + rounded_units * tick
    risk = abs(entry - stop)
    target = entry + (-2 * risk if direction == "short" else 2 * risk)
    assert Fraction(actual["stop"]) == stop and Fraction(actual["target"]) == target
    assert Fraction(actual["risk_distance"]) == risk
    assert actual["frozen_atr"] == "0.62" and D(actual["reward_risk"]) == 2
    assert actual["entry_side"] == ("ask" if direction == "long" else "bid")
    assert actual["quote_time"] != source.bar.close_time


@pytest.mark.parametrize("case,code", [("stale", "STALE_OR_FUTURE_QUOTE"), ("future", "STALE_OR_FUTURE_QUOTE"), ("before_close", "STALE_OR_FUTURE_QUOTE"), ("expired", "EXPIRED_ENTRY_WINDOW"), ("open_source", "SOURCE_NOT_CLOSED"), ("drift", "MISSED_ENTRY_PRICE_DRIFT"), ("lost_side", "ENTRY_LOST_EMA20_SIDE"), ("off_tick", "QUOTE_OFF_TICK_OR_BOUNDS"), ("crossed", "INVALID_QUOTE"), ("zero_liquidity", "INVALID_QUOTE"), ("nan", "INVALID_QUOTE"), ("float", "INVALID_QUOTE"), ("wrong_symbol", "QUOTE_SYMBOL_MISMATCH"), ("bounds", "INVALID_RISK_GEOMETRY_OR_BOUNDS")])
def test_quote_and_risk_guards(case, code):
    now = BOUNDARY + 10_000
    q = quote(now, "100.0", "100.1")
    source = snapshot()
    filters = PriceFilter(D("0.1"), D(0), D(1000))
    if case == "stale": q = replace(q, time=now - 5001)
    elif case == "future": q = replace(q, time=now + 1)
    elif case == "before_close": q = replace(q, time=BOUNDARY - 1)
    elif case == "expired": now = BOUNDARY + 300_000
    elif case == "open_source": now = BOUNDARY - 1
    elif case == "drift": q = replace(q, ask=D("100.5"))
    elif case == "lost_side": q = replace(q, bid=D("99.9"), ask=D(100))
    elif case == "off_tick": q = replace(q, ask=D("100.11"))
    elif case == "crossed": q = replace(q, bid=D(101))
    elif case == "zero_liquidity": q = replace(q, ask_qty=D(0))
    elif case == "nan": q = replace(q, ask=D("NaN"))
    elif case == "float": q = replace(q, ask=100.1)
    elif case == "wrong_symbol": q = replace(q, symbol="ETHUSDT")
    elif case == "bounds": filters = replace(filters, minimum=D(100))
    with pytest.raises(PlanRejected) as rejected:
        build_plan("BTCUSDT", "long", source, q, filters, now)
    assert rejected.value.code == code


def test_exact_quote_age_and_drift_limits_are_inclusive():
    now = BOUNDARY + 10_000
    source = replace(snapshot(), atr=D("0.8"))
    q = replace(quote(now, "100.4", "100.5"), time=now - 5000)
    plan = build_plan("BTCUSDT", "long", source, q, PriceFilter(D("0.1"), D(0), D(1000)), now)
    assert plan["entry_drift"] == "0.4"
    assert plan["expires_at"] == BOUNDARY + 300_000


def test_dedup_identity_is_deterministic_and_specific_to_source_and_coin():
    identity = decision_id("BTCUSDT", BOUNDARY - STEP)
    assert len(identity) == 64 and identity == decision_id("BTCUSDT", BOUNDARY - STEP)
    assert identity != decision_id("ETHUSDT", BOUNDARY - STEP)
    assert identity != decision_id("BTCUSDT", BOUNDARY)
