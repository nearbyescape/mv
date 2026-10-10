"""V6HBR post-hoc entry-direction adversity diagnostics (development only).

Measures how quickly approved reference entries moved toward stop versus TP,
in units of each TRADE'S SCENARIO-FILL risk. It cannot establish that actual
2026 Lighter alerts moved opposite, since it consumes Binance 1m reference
candles and reconstructed hypothetical entries, not operator executions.

Only already-selected cohort identities are analyzed. Candle high/low does not
resolve intraminute order: threshold ties count adverse-first. Windows truncate
at terminal exit and dataset cutoff; truncated windows are never counted as
complete. This module does NOT alter candidate ranking, plan or signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation

from .v6hbr_portfolio_replay import CLOSED

MINUTE = 60_000
WINDOWS_MINUTES = (15, 30, 60)
THRESHOLD = D("0.5")


def _number(value, label: str) -> D:
    try:
        result = D(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid " + label) from exc
    if not result.is_finite():
        raise ValueError("Nonfinite " + label)
    return result


def _ratio(part: int, whole: int) -> str | None:
    return str(D(part) / whole) if whole else None


def _summarize(rows: list[dict], window: int) -> dict:
    complete = [r for r in rows if r["complete_window"]]
    # The earlier terminated trades still contribute observed adversity, but
    # cannot be treated as having a full completed 15/30/60 minute window.
    n = len(rows)
    early = sum(r["closed_before_window_end"] for r in rows)
    cutoff = sum(r["dataset_censored_before_window_end"] for r in rows)
    first = {
        k: sum(r["first_0p5r_event"] == k for r in rows)
        for k in ("ADVERSE_FIRST", "FAVORABLE_FIRST", "NONE")
    }
    median_values = sorted(_number(r["max_adverse_r"], "adverse R") for r in rows)
    median = None
    if median_values:
        i = len(median_values) // 2
        median = str(median_values[i] if len(median_values) % 2 else
                     (median_values[i-1] + median_values[i]) / 2)
    return {
        "horizon_minutes": window,
        "accepted_entry_references": n,
        "complete_window_count": len(complete),
        "closed_before_window_end": early,
        "dataset_censored_before_window_end": cutoff,
        "adverse_0p5r_observed": sum(r["adverse_0p5r_observed"] for r in rows),
        "favorable_0p5r_observed": sum(r["favorable_0p5r_observed"] for r in rows),
        "adverse_first_or_same_minute_tie": first["ADVERSE_FIRST"],
        "favorable_first": first["FAVORABLE_FIRST"],
        "neither_threshold": first["NONE"],
        "adverse_first_fraction_of_all_observed_entries": _ratio(first["ADVERSE_FIRST"], n),
        "fully_observed_adverse_first": sum(
            r["first_0p5r_event"] == "ADVERSE_FIRST" for r in complete
        ),
        "median_max_adverse_r_from_observed_portions": median,
        "caveat": "Early-closed and dataset-censored observations have shorter exposure; their maxima are not full-horizon outcomes",
    }


def entry_adversity_report(
    priced: list[dict], minute_bars: list, cohorts: dict[str, dict],
    *, end_exclusive_ms: int
) -> dict:
    """Only read the approved candidate's observable minute interval.

    Terminal-at-the-end-of-minute convention ensures no post-exit future
    candles are included. The earliest traded minute is included, but no
    same-minute order of high/low is asserted beyond adverse-first ties.
    """
    if type(end_exclusive_ms) is not int or end_exclusive_ms % MINUTE:
        raise ValueError("Invalid analysis end")
    index = {x["id"]: x for x in priced}
    if len(index) != len(priced):
        raise ValueError("Duplicate candidate identity")
    if set(cohorts) != {"V4", "H", "B", "R"}:
        raise ValueError("Exactly four cohorts required")
    minutes = {b.open_time: b for b in minute_bars}
    if len(minutes) != len(minute_bars):
        raise ValueError("Duplicate minute timestamp")
    if not minutes:
        raise ValueError("No minute source data")

    sample = {}
    for ident, row in index.items():
        out = row.get("outcome")
        if out is None:
            continue  # explicitly unfilled/rejected entries are not selected
        if row["direction"] not in ("long", "short"):
            raise ValueError("Unsupported trade direction")
        if out["status"] not in CLOSED | {"OPEN_UNRESOLVED", "NO_FILL_REFERENCE"}:
            raise ValueError("Unrecognized reference execution state")
        if out["status"] == "NO_FILL_REFERENCE":
            continue
        entry_at = out["entry_at_ms"]
        if type(entry_at) is not int or entry_at < row["at_ms"] + MINUTE:
            raise ValueError("Noncausal execution entry time")
        entry = _number(out["entry_price_scenario"], "entry price")
        risk = _number(out["risk_distance_at_fill"], "entry risk distance")
        if entry <= 0 or risk <= 0:
            raise ValueError("Invalid risk geometry")
        terminal = out["terminal_at_ms"] if out["status"] in CLOSED else None
        if terminal is not None and (
            type(terminal) is not int or terminal <= entry_at
            or terminal % MINUTE or terminal > end_exclusive_ms
        ):
            raise ValueError("Terminal time is noncausal or outside research window")
        if entry_at >= end_exclusive_ms:
            raise ValueError("Entry at or after research cutoff")

        sign = D(1) if row["direction"] == "long" else D(-1)
        windows = {}
        for horizon in WINDOWS_MINUTES:
            requested_end = entry_at + horizon * MINUTE
            stop_at = min(requested_end, terminal or end_exclusive_ms,
                          end_exclusive_ms)
            highs = lows = None
            first_adverse = first_favorable = None
            count = 0
            for t in range(entry_at, stop_at, MINUTE):
                if t not in minutes:
                    raise ValueError("Minute-gap: cannot infer entry adversity")
                candle = minutes[t]
                high, low = _number(candle.high, "1m high"), _number(candle.low, "1m low")
                if not 0 < low <= high:
                    raise ValueError("Invalid minute OHLC range")
                highs = high if highs is None else max(highs, high)
                lows = low if lows is None else min(lows, low)
                count += 1
                adverse = (entry - low) / risk if sign > 0 else (high - entry) / risk
                favorable = (high - entry) / risk if sign > 0 else (entry - low) / risk
                if first_adverse is None and adverse >= THRESHOLD:
                    first_adverse = t + MINUTE
                if first_favorable is None and favorable >= THRESHOLD:
                    first_favorable = t + MINUTE
            if count == 0:
                raise ValueError("No executable minute for entry adversity")
            max_adverse = max((entry - lows) / risk if sign > 0 else
                              (highs - entry) / risk, D(0))
            max_favorable = max((highs - entry) / risk if sign > 0 else
                                (entry - lows) / risk, D(0))
            first = (
                "ADVERSE_FIRST" if first_adverse is not None and (
                    first_favorable is None or first_adverse <= first_favorable
                ) else "FAVORABLE_FIRST" if first_favorable is not None else "NONE"
            )
            full = stop_at == requested_end
            windows[str(horizon)] = {
                "observed_minutes": count,
                "complete_window": full,
                "closed_before_window_end": terminal is not None and terminal < requested_end,
                "dataset_censored_before_window_end": (
                    terminal is None and end_exclusive_ms < requested_end
                ),
                "max_adverse_r": str(max_adverse),
                "max_favorable_r": str(max_favorable),
                "adverse_0p5r_observed": first_adverse is not None,
                "favorable_0p5r_observed": first_favorable is not None,
                "first_0p5r_event": first,
                "same_minute_ties_are_adverse_first": True,
            }
        sample[ident] = {
            "id": ident,
            "lane": row["lane"],
            "direction": row["direction"],
            "entry_at_ms": entry_at,
            "entry_month_utc": datetime.fromtimestamp(
                entry_at / 1000, timezone.utc
            ).strftime("%Y-%m"),
            "outcome_status": out["status"],
            "windows": windows,
        }
    result = {}
    for name, report in cohorts.items():
        ids = report["accepted_ids"]
        if len(set(ids)) != len(ids):
            raise ValueError("Duplicate accepted IDs")
        if any(x not in sample for x in ids):
            raise ValueError("Accepted reference lacks executable minute scenario")
        entries = [sample[x] for x in ids]
        by_window = {}
        for horizon in WINDOWS_MINUTES:
            key = str(horizon)
            by_window[key] = {
                "overall": _summarize([x["windows"][key] for x in entries], horizon),
                "by_lane": {
                    lane: _summarize([
                        x["windows"][key] for x in entries if x["lane"] == lane
                    ], horizon) for lane in ("v4_base", "15m_rescue")
                },
                "by_direction": {
                    d: _summarize([
                        x["windows"][key] for x in entries if x["direction"] == d
                    ], horizon) for d in ("long", "short")
                },
            }
        result[name] = {
            "accepted_count": len(entries),
            "windows": by_window,
            "entry_details": entries,
        }
    return {
        "status": "POST_HOC_BINANCE_REFERENCE_ADVERSITY_NOT_LIVE_FILL_ACCURACY",
        "threshold_r": str(THRESHOLD),
        "windows_minutes": list(WINDOWS_MINUTES),
        "cohorts": result,
        "limitations": [
            "Price movements from completed Binance 1m OHLC, not observed Lighter fills or spreads",
            "Opposite movement is only a price excursion relative to scenario entry, not proof of bad forecast",
            "Adverse/favorable both occurring in the same 1m candle are ordered adverse-first",
            "Trades closed before window end are censored; never imply full-horizon exposure",
            "Do not use this diagnostic to revise historical portfolio selections",
            "BTC Apr-May development only; not the user's recent live alerts",
        ],
    }
