"""Historical V7Sonic price-reference evaluation; NOT executions or PnL.

Use only full 1-minute candles starting at the first WHOLE minute after
the recorded five-minute decision boundary. The partial 09:05 candle
cannot prove whether a 09:05:02 decision entered before its 30s expiry.

No network, Telegram, filesystem or exchange-order side effects.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import json
from typing import Any

STEP_MS = 60_000
WINDOW_BARS = 120
HORIZONS = (15, 30, 60, 120)
_MAX_BODY_BYTES = 256_000
_ALLOWED = frozenset(("SOLUSDT", "DOGEUSDT"))


def _positive_price(value: Any) -> Decimal:
    if type(value) not in (str, int, float):
        raise ValueError("Unsupported price representation")
    try:
        out = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Malformed price") from None
    if not out.is_finite() or out <= 0:
        raise ValueError("Nonpositive or nonfinite price")
    return out


def full_post_decision_minute_bars(symbol: str, boundary_ms: int, raw: bytes) -> list[dict]:
    """Require 120 consecutive, CLOSED 1m candles from boundary+1m onward."""
    if (symbol not in _ALLOWED or type(boundary_ms) is not int or
            boundary_ms <= 0 or boundary_ms % (5 * STEP_MS) or
            not isinstance(raw, bytes) or
            not 2 <= len(raw) <= _MAX_BODY_BYTES):
        raise ValueError("Invalid post-decision reference request")
    try:
        rows = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Malformed historical candle JSON") from None
    if not isinstance(rows, list) or len(rows) != WINDOW_BARS:
        raise ValueError("Missing complete 120-minute historical price window")

    result = []
    for idx, item in enumerate(rows):
        opening = boundary_ms + (idx + 1) * STEP_MS
        if (not isinstance(item, list) or len(item) != 12 or
                type(item[0]) is not int or item[0] != opening or
                type(item[6]) is not int or item[6] != opening + STEP_MS - 1):
            raise ValueError("Out-of-order, future, missing or partial 1m candle")
        o, h, l, c = (_positive_price(item[i]) for i in (1, 2, 3, 4))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Inconsistent original historical OHLC")
        # Source volume and trade-counter shape must exist; not assume
        # these are authenticated, executed or arbitrage-free prices.
        _positive_or_zero(item[5])
        result.append({"open_ms": opening, "open": o, "high": h, "low": l, "close": c})
    return result


def _positive_or_zero(value: Any) -> Decimal:
    if type(value) not in (str, int, float):
        raise ValueError("Malformed candle volume")
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Malformed candle volume") from None
    if not d.is_finite() or d < 0:
        raise ValueError("Invalid candle volume")
    return d


def score_reference_path(candidate: dict, bars: list[dict]) -> dict:
    """Directional excursions in model-risk units, NEVER realized trade PnL.

    A 1m bar touching the initial SL and TP1 is ambiguous. No entry/fill
    is inferred because the decision expired inside the OMITTED 09:05 bar.
    """
    if (not isinstance(candidate, dict) or
            candidate.get("symbol") not in _ALLOWED or
            candidate.get("direction") != "LONG" or
            candidate.get("expert") != "breakout" or
            not isinstance(bars, list) or len(bars) != WINDOW_BARS):
        raise ValueError("Unsupported or incomplete historical V7 paper reference")
    entry, sl, tp1, tp2 = (
        _positive_price(candidate.get(k))
        for k in ("entry", "stop_loss", "take_profit_1", "take_profit_2")
    )
    if not sl < entry < tp1 < tp2:
        raise ValueError("Invalid reference LONG stop/target geometry")
    r = entry - sl
    positive_peak = max(b["high"] for b in bars)
    negative_trough = min(b["low"] for b in bars)

    first = "NONE_WITHIN_120_FULL_POST_DECISION_MINUTES"
    first_bar = None
    touched_sl = False
    touched_tp1 = False
    touched_tp2 = False
    for i, bar in enumerate(bars):
        if any(not isinstance(bar.get(x), Decimal) for x in ("low", "high", "close")):
            raise ValueError("Malformed full-minute input bar")
        sl_hit, tp1_hit, tp2_hit = (
            bar["low"] <= sl, bar["high"] >= tp1, bar["high"] >= tp2
        )
        touched_sl |= sl_hit
        touched_tp1 |= tp1_hit
        touched_tp2 |= tp2_hit
        if first_bar is None and (sl_hit or tp1_hit):
            first_bar = i + 1
            if sl_hit and tp1_hit:
                first = "AMBIGUOUS_SL_AND_TP1_SAME_ONE_MINUTE_CANDLE"
            elif sl_hit:
                first = "INITIAL_STOP_REFERENCE_TOUCHED_FIRST"
            else:
                first = "INITIAL_TP1_REFERENCE_TOUCHED_FIRST"
    horizon_scores = {}
    for n in HORIZONS:
        close = bars[n - 1]["close"]
        reference_r = (close - entry) / r
        horizon_scores[str(n)] = {
            "close": str(close),
            "reference_r_from_model_entry": str(reference_r),
            "directional_close_above_model_entry": close > entry,
        }
    return {
        "symbol": candidate["symbol"],
        "direction": "LONG",
        "expert": "breakout",
        "entry_reference": str(entry),
        "stop_reference": str(sl),
        "tp1_reference": str(tp1),
        "tp2_reference": str(tp2),
        "risk_unit_quote_per_coin": str(r),
        "first_reference_barrier_event": first,
        "first_event_post_decision_full_minute_index": first_bar,
        "any_stop_reference_touch": touched_sl,
        "any_tp1_reference_touch": touched_tp1,
        "any_tp2_reference_touch": touched_tp2,
        "maximum_favorable_excursion_reference_r": str((positive_peak-entry)/r),
        "maximum_adverse_excursion_reference_r": str((entry-negative_trough)/r),
        "horizon_closes_in_full_post_decision_minutes": horizon_scores,
        "entry_fill_proven": False,
        "initial_30_second_entry_window_observable": False,
        "realized_return_or_profit_claim": False,
        "status": "HISTORICAL_PRICE_REFERENCE_ONLY_DO_NOT_TRADE",
    }
