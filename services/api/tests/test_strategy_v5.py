from dataclasses import replace
from decimal import Decimal as D

from mv_strategy import Bar, INTERVAL_MS
from mv_strategy.signals import Snapshot
from mv_strategy.strategy_v5 import (
    CANDIDATE_STRATEGY_ID,
    candidate_id,
    evaluate_context_v5,
    evaluate_trigger_v5,
)
from test_strategy_v3 import (
    BOUNDARY,
    long_pullback_context,
    short_breakout_context,
    snap_4h,
)

MIN15 = INTERVAL_MS["15m"]
TRIGGER_OPEN = BOUNDARY
ORIGIN_15M = TRIGGER_OPEN - 600 * MIN15


def snap_15m(
    time,
    *,
    open_,
    high,
    low,
    close,
    ema20,
    ema50="101",
    sma200="102",
    atr="2",
    lineage=None,
):
    bar = Bar(
        time,
        time + MIN15 - 1,
        D(open_),
        D(high),
        D(low),
        D(close),
        D("100"),
    )
    return Snapshot(
        "15m",
        bar,
        D(ema20),
        D(ema50),
        D(sma200),
        D(atr),
        (time - ORIGIN_15M) // MIN15 + 1,
        ORIGIN_15M,
        lineage or f"15m-{time}",
    )


def short_trigger_context(kind="pullback"):
    structure = []
    for n in range(12, 1, -1):
        time = TRIGGER_OPEN - n * MIN15
        structure.append(
            snap_15m(
                time,
                open_="100.2",
                high="101",
                low="99",
                close="100",
                ema20="100",
            )
        )

    if kind == "pullback":
        previous = snap_15m(
            TRIGGER_OPEN - MIN15,
            open_="99.8",
            high="100.5",
            low="99.5",
            close="100.2",
            ema20="100",
        )
        current = snap_15m(
            TRIGGER_OPEN,
            open_="100.2",
            high="100.4",
            low="98.8",
            close="99.2",
            ema20="99.6",
        )
    elif kind == "breakout":
        previous = snap_15m(
            TRIGGER_OPEN - MIN15,
            open_="99.8",
            high="100.2",
            low="99.2",
            close="99.5",
            ema20="100",
        )
        current = snap_15m(
            TRIGGER_OPEN,
            open_="100",
            high="100.2",
            low="98.4",
            close="98.6",
            ema20="99.5",
        )
    else:
        raise ValueError(kind)

    structure.append(previous)
    return current, previous, structure


def test_v5_arms_v4_trend_context_without_requiring_1h_entry_trigger():
    current, previous, confirmation, structure = long_pullback_context()
    armed = evaluate_context_v5(current, previous, confirmation, structure)
    assert armed.outcome == "ARMED"
    assert armed.reason == "CONTEXT_ARMED"
    assert armed.direction == "long"
    assert armed.regime == "established"


def test_v5_keeps_v4_completed_4h_alignment_as_a_hard_context_requirement():
    current, previous, _, structure = short_breakout_context()
    blocked = evaluate_context_v5(
        current,
        previous,
        snap_4h("long"),
        structure,
    )
    assert blocked.outcome == "NO_CONTEXT"
    assert blocked.reason == "4H_TREND_NOT_ALIGNED"
    assert blocked.direction == "short"


def test_v5_accepts_completed_15m_pullback_trigger_only_after_context_is_armed():
    current, previous, structure = short_trigger_context("pullback")
    trigger = evaluate_trigger_v5("short", current, previous, structure)
    assert trigger.outcome == "TRIGGER"
    assert trigger.reason == "RULES_PASSED"
    assert trigger.direction == "short"
    assert trigger.trigger_type == "pullback_continuation_15m"
    assert all(check["passed"] for check in trigger.checks)


def test_v5_accepts_completed_15m_structural_breakout_without_requiring_pullback():
    current, previous, structure = short_trigger_context("breakout")
    trigger = evaluate_trigger_v5("short", current, previous, structure)
    assert trigger.outcome == "TRIGGER"
    assert trigger.trigger_type == "momentum_breakout_15m"
    assert trigger.structure_level == D("99")
    assert all(check["passed"] for check in trigger.checks)


def test_v5_rejects_weak_15m_candle_instead_of_turning_every_15m_bar_into_signal():
    current, previous, structure = short_trigger_context("breakout")
    weak = replace(
        current,
        bar=replace(
            current.bar,
            open=D("99.75"),
            high=D("99.9"),
            low=D("99.6"),
            close=D("99.7"),
        ),
        ema20=D("99.8"),
    )
    trigger = evaluate_trigger_v5("short", weak, previous, structure)
    assert trigger.outcome == "NO_TRIGGER"
    assert trigger.reason == "NO_15M_PULLBACK_OR_BREAKOUT_TRIGGER"


def test_v5_trigger_requires_contiguous_15m_history():
    current, previous, structure = short_trigger_context("pullback")
    broken_previous = snap_15m(
        TRIGGER_OPEN - 2 * MIN15,
        open_="99.8",
        high="100.5",
        low="99.5",
        close="100.2",
        ema20="100",
    )
    trigger = evaluate_trigger_v5(
        "short",
        current,
        broken_previous,
        structure,
    )
    assert trigger.outcome == "BLOCKED_DATA"
    assert trigger.reason == "NONCONTIGUOUS_PREVIOUS_15M"


def test_v5_candidate_identity_is_deterministic_and_versions_trigger_time():
    first = candidate_id("BTCUSDT", BOUNDARY - INTERVAL_MS["1h"], BOUNDARY)
    same = candidate_id("BTCUSDT", BOUNDARY - INTERVAL_MS["1h"], BOUNDARY)
    later = candidate_id(
        "BTCUSDT",
        BOUNDARY - INTERVAL_MS["1h"],
        BOUNDARY + MIN15,
    )
    assert CANDIDATE_STRATEGY_ID == "MV-TREND-DUAL-v5-candidate"
    assert first == same
    assert first != later
