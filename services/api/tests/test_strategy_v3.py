from dataclasses import replace
from decimal import Decimal as D

import pytest

from mv_strategy import Bar, INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import Snapshot, Quote, PriceFilter, PlanRejected, decision_id
from mv_strategy.strategy_v2 import live_decision_id as v2_decision_id
from mv_strategy.strategy_v3 import (
    LIVE_STRATEGY_ID,
    LiveSetup,
    build_plan_v3,
    evaluate_setup_v3,
    live_decision_id,
)

STEP = INTERVAL_MS["1h"]
BOUNDARY = 1791046800000
SOURCE_OPEN = BOUNDARY - STEP
ORIGIN_1H = SOURCE_OPEN - 600 * STEP
CONF_OPEN = confirmation_open_time(BOUNDARY)
ORIGIN_4H = CONF_OPEN - 600 * INTERVAL_MS["4h"]


def snap_1h(time, *, open_, high, low, close, ema20, ema50, sma200, atr="2", lineage=None):
    bar = Bar(time, time + STEP - 1, D(open_), D(high), D(low), D(close), D(100))
    return Snapshot(
        "1h",
        bar,
        D(ema20),
        D(ema50),
        D(sma200),
        D(atr),
        (time - ORIGIN_1H) // STEP + 1,
        ORIGIN_1H,
        lineage or f"1h-{time}",
    )


def snap_4h(direction):
    if direction == "short":
        values = ("100", "101", "102", "98")
    else:
        values = ("100", "99", "98", "102")
    ema20, ema50, sma200, close = values
    bar = Bar(
        CONF_OPEN,
        CONF_OPEN + INTERVAL_MS["4h"] - 1,
        D("100"),
        D("103"),
        D("97"),
        D(close),
        D(400),
    )
    return Snapshot(
        "4h",
        bar,
        D(ema20),
        D(ema50),
        D(sma200),
        D("3"),
        (CONF_OPEN - ORIGIN_4H) // INTERVAL_MS["4h"] + 1,
        ORIGIN_4H,
        f"4h-{CONF_OPEN}",
    )


def short_breakout_context():
    structure = []
    for n in range(12, 1, -1):
        time = SOURCE_OPEN - n * STEP
        structure.append(
            snap_1h(
                time,
                open_="100.2",
                high="101",
                low="99",
                close="100",
                ema20="100.8",
                ema50="101.5",
                sma200="102.5",
            )
        )
    previous = snap_1h(
        SOURCE_OPEN - STEP,
        open_="100",
        high="100.5",
        low="98.8",
        close="99",
        ema20="100.5",
        ema50="101.2",
        sma200="102.2",
    )
    structure.append(previous)
    current = snap_1h(
        SOURCE_OPEN,
        open_="101",
        high="101.5",
        low="97.5",
        close="98",
        ema20="100",
        ema50="101",
        sma200="102",
    )
    return current, previous, snap_4h("short"), structure


def long_pullback_context():
    structure = []
    for n in range(12, 1, -1):
        time = SOURCE_OPEN - n * STEP
        structure.append(
            snap_1h(
                time,
                open_="99.8",
                high="104",
                low="99",
                close="100",
                ema20="99.5",
                ema50="98.5",
                sma200="97.5",
            )
        )
    previous = snap_1h(
        SOURCE_OPEN - STEP,
        open_="100.2",
        high="100.5",
        low="99.2",
        close="99.5",
        ema20="100",
        ema50="99",
        sma200="98",
    )
    structure.append(previous)
    current = snap_1h(
        SOURCE_OPEN,
        open_="99.5",
        high="101",
        low="99",
        close="100.6",
        ema20="100",
        ema50="99.2",
        sma200="98.2",
    )
    return current, previous, snap_4h("long"), structure


def quote(direction="short", now=BOUNDARY + 1000, bid="98.00", ask="98.01"):
    return Quote("BTCUSDT", D(bid), D(ask), D(10), D(10), now - 100, now)


def test_continuous_bear_market_can_publish_breakout_short_without_ema20_retest():
    current, previous, confirmation, structure = short_breakout_context()
    # This is the exact V1 blind spot: the previous close is already below EMA20.
    assert previous.bar.close < previous.ema20
    setup = evaluate_setup_v3(current, previous, confirmation, structure)
    assert setup.outcome == "SHORT_SETUP"
    assert setup.direction == "short"
    assert setup.setup_type == "momentum_breakout"
    assert setup.regime == "established"
    assert setup.structure_level == D("98.8")
    assert all(check["passed"] for check in setup.checks)


def test_quality_pullback_remains_a_separate_valid_setup():
    current, previous, confirmation, structure = long_pullback_context()
    setup = evaluate_setup_v3(current, previous, confirmation, structure)
    assert setup.outcome == "LONG_SETUP"
    assert setup.direction == "long"
    assert setup.setup_type == "pullback_continuation"
    assert setup.regime == "established"


def test_emerging_trend_can_qualify_before_full_sma200_ordering():
    current, previous, confirmation, structure = long_pullback_context()
    # Break full 1H EMA50/SMA200 ordering while retaining rising EMA50 and
    # price above SMA200.  This must use the emerging regime, not established.
    previous = replace(previous, ema50=D("99.0"), sma200=D("99.4"))
    structure = [*structure[:-1], previous]
    current = replace(current, ema50=D("99.2"), sma200=D("99.4"))
    setup = evaluate_setup_v3(current, previous, confirmation, structure)
    assert setup.outcome == "LONG_SETUP"
    assert setup.regime == "emerging"
    ids = {check["id"] for check in setup.checks}
    assert "long.ema50_slope_1h" in ids
    assert "long.price_sma200_1h" in ids
    assert "long.established_1h" not in ids
    assert all(check["passed"] for check in setup.checks)


def test_breakout_requires_completed_4h_alignment_and_full_structure_history():
    current, previous, confirmation, structure = short_breakout_context()
    assert evaluate_setup_v3(current, previous, None, structure).reason == "WAITING_EXPECTED_4H"
    assert evaluate_setup_v3(current, previous, confirmation, structure[:-1]).reason == "MISSING_STRUCTURE_HISTORY"
    bullish_4h = snap_4h("long")
    rejected = evaluate_setup_v3(current, previous, bullish_4h, structure)
    assert rejected.outcome == "NO_SETUP"
    assert rejected.reason == "4H_TREND_NOT_ALIGNED"


def test_breakout_does_not_chase_an_overextended_source_candle():
    current, previous, confirmation, structure = short_breakout_context()
    overextended = replace(
        current,
        bar=replace(current.bar, open=D("102"), high=D("102.5"), low=D("95.5"), close=D("96")),
    )
    result = evaluate_setup_v3(overextended, previous, confirmation, structure)
    assert result.outcome == "NO_SETUP"
    assert result.reason == "NO_PULLBACK_OR_BREAKOUT_TRIGGER"
    extension = next(c for c in result.checks if c["id"] == "short.source_extension_atr")
    assert extension["passed"] is False


def test_v3_plan_preserves_two_atr_stop_and_three_scaled_targets_and_rejects_wide_spread():
    current, previous, confirmation, structure = short_breakout_context()
    setup = evaluate_setup_v3(current, previous, confirmation, structure)
    price_filter = PriceFilter(D("0.01"), D(0), D(10000))
    plan = build_plan_v3("BTCUSDT", setup, current, quote(), price_filter, BOUNDARY + 1000)
    assert plan["strategy"] == LIVE_STRATEGY_ID
    assert plan["setup_type"] == "momentum_breakout"
    risk = D(plan["risk_distance"])
    assert D(plan["stop"]) - D(plan["entry"]) == risk
    assert D(plan["entry"]) - D(plan["tp1"]) == D(plan["tp1_r"]) * risk
    assert D(plan["entry"]) - D(plan["tp2"]) == D(plan["tp2_r"]) * risk
    assert D(plan["entry"]) - D(plan["tp3"]) == D(plan["tp3_r"]) * risk
    assert plan["target"] == plan["tp3"]
    assert D(plan["reward_risk"]) == D(plan["tp3_r"])
    assert plan["exit_management"]["tp1_allocation"] == "0.30"
    assert plan["exit_management"]["tp2_allocation"] == "0.30"
    assert plan["exit_management"]["tp3_allocation"] == "0.40"
    assert D(plan["spread_bps"]) < 10

    wide = quote(bid="97.80", ask="98.20")
    with pytest.raises(PlanRejected) as error:
        build_plan_v3("BTCUSDT", setup, current, wide, PriceFilter(D("0.10"), D(0), D(10000)), BOUNDARY + 1000)
    assert error.value.code == "SPREAD_TOO_WIDE"


def test_v3_decision_identity_is_versioned_away_from_v1_and_v2():
    identity = live_decision_id("BTCUSDT", SOURCE_OPEN)
    assert identity != decision_id("BTCUSDT", SOURCE_OPEN)
    assert identity != v2_decision_id("BTCUSDT", SOURCE_OPEN)
    assert identity == live_decision_id("BTCUSDT", SOURCE_OPEN)



def test_v3_recent_six_hour_run_blocks_chased_source():
    current, previous, confirmation, structure = long_pullback_context()
    # Keep EMA extension acceptable while making the last-six-bar anchor too far
    # below the source close. The dedicated recent-run gate must reject it.
    recent = []
    for index, snap in enumerate(structure):
        if index >= len(structure) - 6:
            recent.append(replace(snap, bar=replace(snap.bar, low=D("94"))))
        else:
            recent.append(snap)
    result = evaluate_setup_v3(current, previous, confirmation, recent)
    assert result.outcome == "NO_SETUP"
    check = next(c for c in result.checks if c["id"] == "long.recent_run_atr")
    assert check["passed"] is False
    assert D(check["value"]) > D("2.50")


def test_v3_live_entry_rejects_recent_run_and_ema_extension_chasing():
    current, previous, confirmation, structure = long_pullback_context()
    setup = evaluate_setup_v3(current, previous, confirmation, structure)
    assert setup.outcome == "LONG_SETUP"
    price_filter = PriceFilter(D("0.01"), D(0), D(10000))

    extended_source = replace(
        current,
        ema20=D("98.8"),
        ema50=D("98.0"),
        sma200=D("97.0"),
    )
    with pytest.raises(PlanRejected) as extension:
        build_plan_v3(
            "BTCUSDT",
            setup,
            extended_source,
            quote("long", bid="100.89", ask="100.90"),
            price_filter,
            BOUNDARY + 1000,
        )
    assert extension.value.code == "ENTRY_OVEREXTENDED"

    chased = replace(setup, recent_run_anchor=D("95"))
    with pytest.raises(PlanRejected) as recent_run:
        build_plan_v3(
            "BTCUSDT",
            chased,
            current,
            quote("long", bid="100.69", ask="100.70"),
            price_filter,
            BOUNDARY + 1000,
        )
    assert recent_run.value.code == "RECENT_RUN_OVEREXTENDED"
