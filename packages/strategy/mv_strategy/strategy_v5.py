"""Research candidate for MV V5: 4H regime + 1H context + completed 15m entry trigger."""
from dataclasses import dataclass
from decimal import Decimal

from .indicators import INTERVAL_MS, confirmation_open_time
from .signals import Snapshot, canonical_hash
from .strategy_v3 import (
    BREAKOUT_BODY_MIN,
    BREAKOUT_CLOSE_LOCATION_MIN,
    BREAKOUT_DISTANCE_MIN,
    BREAKOUT_SOURCE_EXTENSION_MAX,
    PULLBACK_BODY_MIN,
    PULLBACK_CLOSE_LOCATION_MIN,
    PULLBACK_DEPTH_MAX,
    PULLBACK_RECLAIM_MIN,
    PULLBACK_SOURCE_EXTENSION_MAX,
    RECENT_RUN_BARS,
    RECENT_RUN_MAX,
    STRUCTURE_BARS,
)

CANDIDATE_STRATEGY_ID = "MV-TREND-DUAL-v5-candidate"
CANDIDATE_RISK_ID = "RISK-ATR14-SCALED-TP-v5-candidate"

TRIGGER_TIMEFRAME = "15m"
ARM_MIN_SOURCE_EXTENSION_ATR = -PULLBACK_DEPTH_MAX
ARM_MAX_SOURCE_EXTENSION_ATR = BREAKOUT_SOURCE_EXTENSION_MAX
ARM_MAX_RECENT_RUN_ATR = RECENT_RUN_MAX


@dataclass(frozen=True)
class ArmedContext:
    outcome: str
    reason: str
    direction: str | None
    regime: str | None
    checks: list[dict]
    recent_run_anchor: Decimal | None = None
    recent_run_atr: Decimal | None = None
    source_extension_atr: Decimal | None = None


@dataclass(frozen=True)
class EntryTrigger:
    outcome: str
    reason: str
    direction: str
    trigger_type: str | None
    checks: list[dict]
    structure_level: Decimal | None = None
    recent_run_anchor: Decimal | None = None
    recent_run_atr: Decimal | None = None
    source_extension_atr: Decimal | None = None


def candidate_id(symbol: str, context_open_time: int, trigger_open_time: int) -> str:
    return canonical_hash(
        [
            CANDIDATE_STRATEGY_ID,
            "binance-usdm",
            symbol,
            "1h-context",
            context_open_time,
            "15m-trigger",
            trigger_open_time,
        ]
    )


def _check(name: str, passed: bool, value: Decimal | str | None = None, minimum: Decimal | None = None, maximum: Decimal | None = None):
    row = {"id": name, "passed": bool(passed)}
    if value is not None:
        row["value"] = str(value)
    if minimum is not None:
        row["minimum"] = str(minimum)
    if maximum is not None:
        row["maximum"] = str(maximum)
    return row


def _directional(direction: str) -> Decimal:
    if direction == "long":
        return Decimal(1)
    if direction == "short":
        return Decimal(-1)
    raise ValueError("direction must be long or short")


def _regime(current: Snapshot, previous: Snapshot, confirmation: Snapshot, direction: str):
    sign = _directional(direction)
    one_fast = sign * (current.ema20 - current.ema50) > 0
    one_full = one_fast and sign * (current.ema50 - current.sma200) > 0
    one_slope = sign * (current.ema50 - previous.ema50) > 0
    one_price_sma = sign * (current.bar.close - current.sma200) > 0
    one_emerging = one_fast and one_slope and one_price_sma

    four_fast = sign * (confirmation.ema20 - confirmation.ema50) > 0
    four_close = sign * (confirmation.bar.close - confirmation.ema20) > 0
    four_full = four_fast and sign * (confirmation.ema50 - confirmation.sma200) > 0 and four_close
    four_emerging = four_fast and four_close

    one_ready = one_full or one_emerging
    four_ready = four_full or four_emerging
    regime = "established" if one_full and four_full else "emerging" if one_ready and four_ready else None

    checks = [
        _check(f"{direction}.ema20_ema50_1h", one_fast),
        _check(f"{direction}.established_1h", one_full),
        _check(f"{direction}.ema50_slope_1h", one_slope),
        _check(f"{direction}.price_sma200_1h", one_price_sma),
        _check(f"{direction}.ema20_ema50_4h", four_fast),
        _check(f"{direction}.ema20_side_4h", four_close),
        _check(f"{direction}.established_4h", four_full),
    ]
    return one_ready, four_ready, regime, checks


def evaluate_context_v5(current: Snapshot, previous: Snapshot | None, confirmation: Snapshot | None, structure: list[Snapshot] | None) -> ArmedContext:
    current.validate()
    if current.timeframe != "1h" or current.count < 500:
        return ArmedContext("BLOCKED_DATA", "WARMUP_1H", None, None, [])
    if previous is None:
        return ArmedContext("BLOCKED_DATA", "MISSING_PREVIOUS_1H", None, None, [])
    previous.validate()
    if (
        previous.timeframe != "1h"
        or previous.bar.open_time + INTERVAL_MS["1h"] != current.bar.open_time
        or previous.history_origin != current.history_origin
    ):
        return ArmedContext("BLOCKED_DATA", "NONCONTIGUOUS_PREVIOUS_1H", None, None, [])
    if confirmation is None:
        return ArmedContext("BLOCKED_DATA", "WAITING_EXPECTED_4H", None, None, [])
    confirmation.validate()
    expected_confirmation = confirmation_open_time(current.bar.close_time + 1)
    if (
        confirmation.timeframe != "4h"
        or confirmation.bar.open_time != expected_confirmation
    ):
        return ArmedContext("BLOCKED_DATA", "WAITING_EXPECTED_4H", None, None, [])
    if confirmation.count < 500:
        return ArmedContext("BLOCKED_DATA", "WARMUP_4H", None, None, [])
    if not structure or len(structure) != STRUCTURE_BARS:
        return ArmedContext("BLOCKED_DATA", "MISSING_STRUCTURE_HISTORY", None, None, [])
    expected_times = [
        current.bar.open_time - n * INTERVAL_MS["1h"]
        for n in range(STRUCTURE_BARS, 0, -1)
    ]
    for snap, expected_time in zip(structure, expected_times):
        if snap is None:
            return ArmedContext("BLOCKED_DATA", "MISSING_STRUCTURE_HISTORY", None, None, [])
        snap.validate()
        if (
            snap.timeframe != "1h"
            or snap.bar.open_time != expected_time
            or snap.history_origin != current.history_origin
        ):
            return ArmedContext("BLOCKED_DATA", "NONCONTIGUOUS_STRUCTURE_HISTORY", None, None, [])
    if (
        structure[-1].bar.open_time != previous.bar.open_time
        or structure[-1].lineage != previous.lineage
    ):
        return ArmedContext("BLOCKED_DATA", "STRUCTURE_PREVIOUS_MISMATCH", None, None, [])
    if current.atr <= 0:
        return ArmedContext("BLOCKED_DATA", "NONPOSITIVE_ATR", None, None, [])

    long_one, long_four, long_regime, long_checks = _regime(current, previous, confirmation, "long")
    short_one, short_four, short_regime, short_checks = _regime(current, previous, confirmation, "short")

    if long_one:
        direction, four_ready, regime, checks = "long", long_four, long_regime, long_checks
    elif short_one:
        direction, four_ready, regime, checks = "short", short_four, short_regime, short_checks
    else:
        return ArmedContext("NO_CONTEXT", "TREND_REGIME_NOT_READY", None, None, [*long_checks, *short_checks])

    if not four_ready or regime is None:
        return ArmedContext("NO_CONTEXT", "4H_TREND_NOT_ALIGNED", direction, None, checks)

    sign = _directional(direction)
    recent = structure[-RECENT_RUN_BARS:]
    recent_run_anchor = min(s.bar.low for s in recent) if direction == "long" else max(s.bar.high for s in recent)
    recent_run_atr = sign * (current.bar.close - recent_run_anchor) / current.atr
    source_extension = sign * (current.bar.close - current.ema20) / current.atr

    recent_check = _check(
        f"{direction}.context_recent_run_atr",
        recent_run_atr <= ARM_MAX_RECENT_RUN_ATR,
        recent_run_atr,
        maximum=ARM_MAX_RECENT_RUN_ATR,
    )
    extension_check = _check(
        f"{direction}.context_source_extension_atr",
        ARM_MIN_SOURCE_EXTENSION_ATR <= source_extension <= ARM_MAX_SOURCE_EXTENSION_ATR,
        source_extension,
        minimum=ARM_MIN_SOURCE_EXTENSION_ATR,
        maximum=ARM_MAX_SOURCE_EXTENSION_ATR,
    )
    checks = [*checks, recent_check, extension_check]

    if not recent_check["passed"]:
        return ArmedContext(
            "NO_CONTEXT", "1H_RECENT_RUN_OVEREXTENDED", direction, regime, checks,
            recent_run_anchor, recent_run_atr, source_extension
        )
    if not extension_check["passed"]:
        return ArmedContext(
            "NO_CONTEXT", "1H_CONTEXT_EXTENSION_OUT_OF_RANGE", direction, regime, checks,
            recent_run_anchor, recent_run_atr, source_extension
        )

    return ArmedContext(
        "ARMED", "CONTEXT_ARMED", direction, regime, checks,
        recent_run_anchor, recent_run_atr, source_extension
    )


def _candle_quality(current: Snapshot, direction: str):
    sign = _directional(direction)
    span = current.bar.high - current.bar.low
    if span <= 0 or current.atr <= 0:
        return Decimal(0), Decimal(0), False
    body_atr = abs(current.bar.close - current.bar.open) / current.atr
    close_location = (
        (current.bar.close - current.bar.low) / span
        if direction == "long"
        else (current.bar.high - current.bar.close) / span
    )
    directional_body = sign * (current.bar.close - current.bar.open) > 0
    return body_atr, close_location, directional_body


def evaluate_trigger_v5(direction: str, current: Snapshot, previous: Snapshot | None, structure: list[Snapshot] | None) -> EntryTrigger:
    sign = _directional(direction)
    current.validate()
    if current.timeframe != TRIGGER_TIMEFRAME or current.count < 500:
        return EntryTrigger("BLOCKED_DATA", "WARMUP_15M", direction, None, [])
    if previous is None:
        return EntryTrigger("BLOCKED_DATA", "MISSING_PREVIOUS_15M", direction, None, [])
    previous.validate()
    if (
        previous.timeframe != TRIGGER_TIMEFRAME
        or previous.bar.open_time + INTERVAL_MS[TRIGGER_TIMEFRAME] != current.bar.open_time
        or previous.history_origin != current.history_origin
    ):
        return EntryTrigger("BLOCKED_DATA", "NONCONTIGUOUS_PREVIOUS_15M", direction, None, [])
    if not structure or len(structure) != STRUCTURE_BARS:
        return EntryTrigger("BLOCKED_DATA", "MISSING_15M_STRUCTURE_HISTORY", direction, None, [])
    expected_times = [
        current.bar.open_time - n * INTERVAL_MS[TRIGGER_TIMEFRAME]
        for n in range(STRUCTURE_BARS, 0, -1)
    ]
    for snap, expected_time in zip(structure, expected_times):
        if snap is None:
            return EntryTrigger("BLOCKED_DATA", "MISSING_15M_STRUCTURE_HISTORY", direction, None, [])
        snap.validate()
        if (
            snap.timeframe != TRIGGER_TIMEFRAME
            or snap.bar.open_time != expected_time
            or snap.history_origin != current.history_origin
        ):
            return EntryTrigger("BLOCKED_DATA", "NONCONTIGUOUS_15M_STRUCTURE_HISTORY", direction, None, [])
    if (
        structure[-1].bar.open_time != previous.bar.open_time
        or structure[-1].lineage != previous.lineage
    ):
        return EntryTrigger("BLOCKED_DATA", "15M_STRUCTURE_PREVIOUS_MISMATCH", direction, None, [])
    if current.atr <= 0 or previous.atr <= 0:
        return EntryTrigger("BLOCKED_DATA", "NONPOSITIVE_ATR", direction, None, [])

    body_atr, close_location, directional_body = _candle_quality(current, direction)
    source_extension = sign * (current.bar.close - current.ema20) / current.atr

    micro_fast = sign * (current.ema20 - current.ema50) > 0
    micro_slope = sign * (current.ema20 - previous.ema20) > 0
    micro_checks = [
        _check(f"{direction}.15m_ema20_ema50", micro_fast),
        _check(f"{direction}.15m_ema20_slope", micro_slope),
    ]

    recent = structure[-RECENT_RUN_BARS:]
    recent_run_anchor = min(s.bar.low for s in recent) if direction == "long" else max(s.bar.high for s in recent)
    recent_run_atr = sign * (current.bar.close - recent_run_anchor) / current.atr
    recent_check = _check(
        f"{direction}.15m_recent_run_atr",
        recent_run_atr <= RECENT_RUN_MAX,
        recent_run_atr,
        maximum=RECENT_RUN_MAX,
    )

    previous_on_pullback_side = sign * (previous.ema20 - previous.bar.close) >= 0
    pullback_depth = abs(previous.bar.close - previous.ema20) / previous.atr
    reclaim_strength = sign * (current.bar.close - current.ema20) / current.atr
    pullback_checks = [
        _check(f"{direction}.15m_pullback_side", previous_on_pullback_side),
        _check(f"{direction}.15m_pullback_depth_atr", previous_on_pullback_side and pullback_depth <= PULLBACK_DEPTH_MAX, pullback_depth, maximum=PULLBACK_DEPTH_MAX),
        _check(f"{direction}.15m_reclaim_strength_atr", reclaim_strength >= PULLBACK_RECLAIM_MIN, reclaim_strength, minimum=PULLBACK_RECLAIM_MIN),
        _check(f"{direction}.15m_directional_body", directional_body),
        _check(f"{direction}.15m_body_atr", body_atr >= PULLBACK_BODY_MIN, body_atr, minimum=PULLBACK_BODY_MIN),
        _check(f"{direction}.15m_close_location", close_location >= PULLBACK_CLOSE_LOCATION_MIN, close_location, minimum=PULLBACK_CLOSE_LOCATION_MIN),
        _check(f"{direction}.15m_source_extension_atr", 0 < source_extension <= PULLBACK_SOURCE_EXTENSION_MAX, source_extension, maximum=PULLBACK_SOURCE_EXTENSION_MAX),
    ]
    pullback_ok = (
        recent_check["passed"]
        and all(item["passed"] for item in micro_checks)
        and all(item["passed"] for item in pullback_checks)
    )

    structure_level = max(s.bar.high for s in structure) if direction == "long" else min(s.bar.low for s in structure)
    breakout_distance = sign * (current.bar.close - structure_level) / current.atr
    breakout_checks = [
        _check(f"{direction}.15m_structure_break", breakout_distance >= BREAKOUT_DISTANCE_MIN, breakout_distance, minimum=BREAKOUT_DISTANCE_MIN),
        _check(f"{direction}.15m_directional_body", directional_body),
        _check(f"{direction}.15m_body_atr", body_atr >= BREAKOUT_BODY_MIN, body_atr, minimum=BREAKOUT_BODY_MIN),
        _check(f"{direction}.15m_close_location", close_location >= BREAKOUT_CLOSE_LOCATION_MIN, close_location, minimum=BREAKOUT_CLOSE_LOCATION_MIN),
        _check(f"{direction}.15m_source_extension_atr", 0 < source_extension <= BREAKOUT_SOURCE_EXTENSION_MAX, source_extension, maximum=BREAKOUT_SOURCE_EXTENSION_MAX),
    ]
    breakout_ok = (
        recent_check["passed"]
        and all(item["passed"] for item in micro_checks)
        and all(item["passed"] for item in breakout_checks)
    )

    if breakout_ok:
        return EntryTrigger(
            "TRIGGER", "RULES_PASSED", direction, "momentum_breakout_15m",
            [recent_check, *micro_checks, *breakout_checks], structure_level,
            recent_run_anchor, recent_run_atr, source_extension
        )
    if pullback_ok:
        return EntryTrigger(
            "TRIGGER", "RULES_PASSED", direction, "pullback_continuation_15m",
            [recent_check, *micro_checks, *pullback_checks], None,
            recent_run_anchor, recent_run_atr, source_extension
        )
    return EntryTrigger(
        "NO_TRIGGER", "NO_15M_PULLBACK_OR_BREAKOUT_TRIGGER", direction, None,
        [recent_check, *micro_checks, *pullback_checks, *breakout_checks], structure_level,
        recent_run_anchor, recent_run_atr, source_extension
    )
