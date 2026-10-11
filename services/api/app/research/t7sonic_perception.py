"""T7Sonic causal OHLCV perception foundation — OFFLINE RESEARCH ONLY.

No API/database/exchange/network/import side effects, order, prediction, or
signal publication. Input is an *externally verified* time-stamped series;
this module validates completeness and point-in-time availability, not the
truthfulness of an upstream publisher. All candles MUST be completed before
as_of_ms. Order-book, tick and funding data are deliberately not imputed.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256
import json

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}
REQUIRED_FRAMES = tuple(INTERVAL_MS)
MIN_BARS = {"1m": 35, "5m": 45, "15m": 35, "1h": 45, "4h": 35}
MAX_INPUT_BARS = 5000
DECIMAL_ZERO = D(0)
EPSILON = D("0.000000000001")


def decimal_number(value, name: str) -> D:
    if isinstance(value, bool):
        raise ValueError("Invalid bool for " + name)
    try:
        number = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid " + name) from exc
    if not number.is_finite():
        raise ValueError("Nonfinite " + name)
    return number


def _clean(value: D) -> str:
    return format(value.normalize(), "f")


@dataclass(frozen=True)
class Bar:
    open_ms: int
    opening: D
    high: D
    low: D
    close: D
    volume: D

    @classmethod
    def parse(cls, obj: dict, frame: str) -> "Bar":
        if not isinstance(obj, dict):
            raise ValueError("Candle must be an explicit mapping")
        fields = frozenset(("open_ms", "open", "high", "low", "close", "volume"))
        if set(obj) != fields:
            raise ValueError("Candle schema mismatch: extra or missing fields")
        t = obj["open_ms"]
        if type(t) is not int or t < 0 or t % INTERVAL_MS[frame]:
            raise ValueError("Invalid aligned candle open_ms")
        o, h, l, c, v = (
            decimal_number(obj[key], key)
            for key in ("open", "high", "low", "close", "volume")
        )
        if not (0 < l <= min(o, c) <= max(o, c) <= h and v >= 0):
            raise ValueError("Invalid OHLCV price geometry or negative volume")
        return cls(t, o, h, l, c, v)


def validate_frame(candles: list[dict], frame: str, as_of_ms: int) -> tuple[Bar, ...]:
    if frame not in REQUIRED_FRAMES:
        raise ValueError("Unsupported T7Sonic frame")
    if not isinstance(candles, list) or not MIN_BARS[frame] <= len(candles) <= MAX_INPUT_BARS:
        raise ValueError("Missing, undersized or oversized completed OHLCV frame")
    if type(as_of_ms) is not int or as_of_ms <= 0:
        raise ValueError("Invalid decision boundary")
    bars = tuple(Bar.parse(x, frame) for x in candles)
    interval = INTERVAL_MS[frame]
    for older, newer in zip(bars, bars[1:]):
        if newer.open_ms - older.open_ms != interval:
            raise ValueError("Gap, overlap or duplicate candle in " + frame)
    latest_boundary = bars[-1].open_ms + interval
    if latest_boundary > as_of_ms:
        raise ValueError("Lookahead: incomplete candle observed at decision")
    if as_of_ms - latest_boundary >= interval:
        raise ValueError("Stale " + frame + " market frame at decision")
    return bars


def _ema(values: tuple[D, ...], length: int) -> D:
    if len(values) < length or length < 2:
        raise ValueError("Insufficient data for EMA")
    alpha = D(2) / D(length + 1)
    level = sum(values[:length], DECIMAL_ZERO) / length
    for value in values[length:]:
        level += alpha * (value - level)
    return level


def _atr(bars: tuple[Bar, ...], length: int = 14) -> D:
    if len(bars) < length + 1:
        raise ValueError("Insufficient ATR warmup")
    tr = []
    for prev, item in zip(bars, bars[1:]):
        tr.append(max(
            item.high - item.low,
            abs(item.high - prev.close),
            abs(item.low - prev.close),
        ))
    result = sum(tr[:length], DECIMAL_ZERO) / length
    for value in tr[length:]:
        result = (result * (length - 1) + value) / length
    if result <= 0:
        raise ValueError("Zero-volatility price series cannot support ATR-normalized signals")
    return result


def summarize_frame(bars: tuple[Bar, ...], frame: str) -> dict:
    if frame not in REQUIRED_FRAMES or len(bars) < MIN_BARS[frame]:
        raise ValueError("Insufficient frame information")
    close = tuple(b.close for b in bars)
    atr = _atr(bars)
    fast, slow = _ema(close, 8), _ema(close, 21)
    prev_window = bars[-21:-1]
    upper = max(b.high for b in prev_window)
    lower = min(b.low for b in prev_window)
    width = upper - lower
    last = bars[-1]
    average_volume = sum((b.volume for b in prev_window), DECIMAL_ZERO) / len(prev_window)
    all_vol = sum((b.volume for b in bars[-20:]), DECIMAL_ZERO)
    vwap = (
        sum(((b.high + b.low + b.close) / 3 * b.volume for b in bars[-20:]), DECIMAL_ZERO) / all_vol
        if all_vol > 0 else None
    )
    normalized_position = ((last.close - lower) / width) if width > 0 else D("0.5")
    return {
        "frame": frame,
        "last_completed_boundary_ms": last.open_ms + INTERVAL_MS[frame],
        "last_close": _clean(last.close),
        "atr14": _clean(atr),
        "atr_fraction_of_price": _clean(atr / last.close),
        "fast_ema8_minus_slow_ema21_atr": _clean((fast - slow) / atr),
        "price_minus_ema21_atr": _clean((last.close - slow) / atr),
        "range_20_completed_atr": _clean(width / atr),
        "position_vs_prev20_range": _clean(normalized_position),
        "previous20_high": _clean(upper),
        "previous20_low": _clean(lower),
        "close_above_previous20_high": last.close > upper,
        "close_below_previous20_low": last.close < lower,
        "rejected_new_high": last.high > upper and last.close < upper,
        "rejected_new_low": last.low < lower and last.close > lower,
        "last_body_atr": _clean((last.close - last.opening) / atr),
        "last_close_change_atr": _clean((last.close - bars[-2].close) / atr),
        "volume_vs_previous20": (
            _clean(last.volume / average_volume) if average_volume > 0 else None
        ),
        "vwap20": _clean(vwap) if vwap is not None else None,
    }


def perceive_symbol(snapshot: dict) -> dict:
    """Build reproducible, multi-timeframe as-of features from closed bars.

    Each OHLCV stream must be contiguous, complete and fresh for this
    decision boundary. Input cannot directly prescribe 'trend' or 'signal'.
    """
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "symbol", "as_of_ms", "bars"
    }:
        raise ValueError("T7Sonic symbol snapshot contract mismatch")
    symbol, as_of_ms, raw = snapshot["symbol"], snapshot["as_of_ms"], snapshot["bars"]
    if not isinstance(symbol, str) or not (6 <= len(symbol) <= 24) or (
        not symbol.isascii() or not symbol.isupper() or
        not symbol.endswith("USDT") or not symbol.replace("_", "").isalnum()
    ):
        raise ValueError("Unexpected perpetual-market symbol")
    if not isinstance(raw, dict) or set(raw) != set(REQUIRED_FRAMES):
        raise ValueError("Require exactly five T7Sonic OHLCV frame streams")
    views = {}
    for frame in REQUIRED_FRAMES:
        bars = validate_frame(raw[frame], frame, as_of_ms)
        views[frame] = summarize_frame(bars, frame)
    canonical = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return {
        "schema": 1, "symbol": symbol, "as_of_ms": as_of_ms,
        "feature_source_sha256": sha256(canonical).hexdigest(),
        "frames": views,
        "input_provenance_status": "OPERATOR_SUPPLIED_REQUIRES_ARCHIVE_SOURCE_AUDIT",
        "prediction_probabilities_available": False,
    }


def breadth_context(perceptions: list[dict]) -> dict:
    """Cross-symbol market breadth at an identical cutoff, never a future peer.

    Breadth is descriptive, not a trading signal or an unvalidated probability.
    Missing members are visible rather than counted as bearish/neutral.
    """
    if not perceptions:
        raise ValueError("Empty market state")
    as_of = perceptions[0]["as_of_ms"]
    symbols = set()
    for p in perceptions:
        symbol = p["symbol"]
        if symbol in symbols:
            raise ValueError("Duplicate market in breadth sample")
        symbols.add(symbol)
        if p["as_of_ms"] != as_of:
            raise ValueError("Cross-market as_of mismatch: future/older peers")
        if set(p["frames"]) != set(REQUIRED_FRAMES):
            raise ValueError("Incomplete peer market features")
    positives_15m = sum(
        decimal_number(p["frames"]["15m"]["last_close_change_atr"], "peer change") > 0
        for p in perceptions
    )
    bullish_1h = sum(
        decimal_number(p["frames"]["1h"]["fast_ema8_minus_slow_ema21_atr"], "peer trend") > 0
        for p in perceptions
    )
    return {
        "as_of_ms": as_of,
        "markets_observed": len(perceptions),
        "expected_full_universe": 30,
        "full_universe_complete": len(perceptions) == 30,
        "symbols": sorted(symbols),
        "fraction_positive_15m_change": _clean(D(positives_15m) / len(perceptions)),
        "fraction_bullish_1h_ema_alignment": _clean(D(bullish_1h) / len(perceptions)),
        "coverage_limitation": "Partial-universe breadth cannot certify whole-market risk-on/off"
        if len(perceptions) < 30 else None,
    }
