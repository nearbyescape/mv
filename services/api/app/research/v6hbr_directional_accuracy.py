"""Frozen-data V6HBR directional signal accuracy study, NOT a trade simulator.

Score *every* generated V4 base and completed 15m rescue trigger against
subsequent 15m candles. No future candle is used to GENERATE a candidate;
future prices are used here solely to LABEL the already formed event.
Reference entry is the NEXT 15m open, not a historical executable venue fill.

Outcome questions differ from portfolio profitability: did directional price
move exceed an explicit 10bps illustrative roundtrip hurdle at 15/30/60/120m?
Did +0.5 source 1h ATR occur before -0.5 ATR? Ambiguous candle ties count
adverse first. Outcomes near the end are censored, not silently successes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256
import json
from math import sqrt
from random import Random
from statistics import fmean
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

QUARTER = 900_000
HORIZONS = (15, 30, 60, 120)
COST_BPS = D("10")
EXCURSION_ATR = D("0.5")


def dec(value, label: str) -> D:
    try:
        result = D(str(value))
    except (TypeError, InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid " + label) from exc
    if not result.is_finite():
        raise ValueError("Nonfinite " + label)
    return result


def wilson_95(successes: int, trials: int) -> tuple[str | None, str | None]:
    """Wilson binomial marginal bound; correlations make it optimistic."""
    if not trials:
        return None, None
    if not 0 <= successes <= trials:
        raise ValueError("Invalid Wilson successes")
    z = 1.95996398454005
    phat = successes / trials
    a = z*z/trials
    center = (phat + a/2)/(1+a)
    half = z/(1+a) * sqrt(phat*(1-phat)/trials + a/(4*trials*trials))
    return str(max(0, center-half)), str(min(1, center+half))


def _date(t: int) -> str:
    return datetime.fromtimestamp(t/1000, tz=timezone.utc).date().isoformat()


def _ist_hour(t: int) -> str:
    return f"{datetime.fromtimestamp(t/1000, tz=IST).hour:02d}:00"


def label_directional_events(
    events: list[dict], fifteen: dict, one_hour: dict,
    *, end_exclusive_ms: int, assumed_roundtrip_bps: D = COST_BPS,
) -> list[dict]:
    """Never use an observation before the completed event publication time.

    15m OHLC alone cannot reconstruct order within a candle: if +0.5 ATR and
    -0.5 ATR both occur in the same candle, report ADVERSE_FIRST.
    """
    cost = dec(assumed_roundtrip_bps, "illustrative cost hurdle")
    if cost < 0 or cost > 100:
        raise ValueError("Unsupported cost hurdle")
    if type(end_exclusive_ms) is not int or end_exclusive_ms % QUARTER:
        raise ValueError("Invalid end-exclusive boundary")
    results = []
    ids = set()
    for ev in events:
        t = ev["at_ms"]
        if type(t) is not int or t % QUARTER or t >= end_exclusive_ms:
            raise ValueError("Invalid published 15m boundary")
        if ev["direction"] not in ("long", "short"):
            raise ValueError("Invalid candidate direction")
        if ev["lane"] not in ("v4_base", "15m_rescue"):
            raise ValueError("Invalid candidate lane")
        key = (ev["symbol"], t, ev["lane"], ev["context_open_ms"],
               ev.get("trigger_open_ms"))
        if key in ids:
            raise ValueError("Duplicate candidate evidence")
        ids.add(key)
        source = one_hour.get(ev["context_open_ms"])
        if source is None or source.bar.close_time + 1 > t:
            raise ValueError("1h source unknown at original decision")
        atr = dec(source.atr, "source 1h ATR")
        if atr <= 0:
            raise ValueError("Invalid frozen source 1h ATR")
        if ev["regime"] not in ("emerging", "established"):
            raise ValueError("Invalid regime")
        if ev["setup_type"] not in ("pullback_continuation", "momentum_breakout"):
            raise ValueError("Invalid setup type")

        first = fifteen.get(t)
        if first is None:
            raise ValueError("Missing first forward 15m reference candle")
        bar = first.bar
        if bar.open_time != t or bar.close_time+1 != t+QUARTER:
            raise ValueError("Invalid as-of forward candle boundary")
        entry = dec(bar.open, "forward open reference")
        if entry <= 0:
            raise ValueError("Invalid reference entry")
        sign = D(1) if ev["direction"] == "long" else D(-1)
        # Only original closed source-hour indicators. Not the future entry
        # candle or hindsight outcome. Enables hypotheses about late chasing.
        source_close = dec(source.bar.close, "original 1h close")
        ema20 = dec(source.ema20, "original 1h EMA20")
        ema50 = dec(source.ema50, "original 1h EMA50")
        source_extension = sign * (source_close - ema20) / atr
        ema_separation = sign * (ema20 - ema50) / atr
        horizons = {}
        for horizon in HORIZONS:
            count = horizon // 15
            # End-censored observations must not be called directional losses.
            if t + count * QUARTER > end_exclusive_ms:
                horizons[str(horizon)] = {"status": "CENSORED", "reason": "RESEARCH_CUTOFF"}
                continue
            high, low = None, None
            first_good = first_bad = None
            last_close = None
            for i in range(count):
                when = t + i * QUARTER
                snap = fifteen.get(when)
                if snap is None or snap.bar.open_time != when or (
                    snap.bar.close_time + 1 != when + QUARTER
                ):
                    raise ValueError("Missing or non-causal forward 15m data")
                b = snap.bar
                bh, bl = dec(b.high, "forward high"), dec(b.low, "forward low")
                opening, closing = dec(b.open, "forward open"), dec(b.close, "forward close")
                if not 0 < bl <= min(opening, closing) <= max(opening, closing) <= bh:
                    raise ValueError("Invalid forward OHLCV geometry")
                high = bh if high is None else max(high, bh)
                low = bl if low is None else min(low, bl)
                last_close = closing
                adverse = max((entry-bl)/atr if sign > 0 else (bh-entry)/atr, D(0))
                favorable = max((bh-entry)/atr if sign > 0 else (entry-bl)/atr, D(0))
                if first_bad is None and adverse >= EXCURSION_ATR:
                    first_bad = when + QUARTER
                if first_good is None and favorable >= EXCURSION_ATR:
                    first_good = when + QUARTER
            signed = sign * (last_close-entry)/entry * D(10_000)
            net_hurdle = signed - cost
            if signed > cost:
                classification = "DIRECTION_SUPPORTED_OVER_HURDLE"
            elif signed < -cost:
                classification = "DIRECTION_OPPOSITE_OVER_HURDLE"
            else:
                classification = "NEUTRAL_WITHIN_HURDLE"
            first_excursion = (
                "ADVERSE_FIRST" if first_bad is not None and (
                    first_good is None or first_bad <= first_good
                ) else "FAVORABLE_FIRST" if first_good is not None else "NONE"
            )
            max_adverse = max(
                ((entry-low)/atr if sign > 0 else (high-entry)/atr), D(0)
            )
            max_favorable = max(
                ((high-entry)/atr if sign > 0 else (entry-low)/atr), D(0)
            )
            horizons[str(horizon)] = {
                "status": "OBSERVED",
                "direction_classification": classification,
                "signed_mark_bps": format(signed.normalize(), "f"),
                "signed_mark_after_illustrative_hurdle_bps": format(net_hurdle.normalize(), "f"),
                "max_adverse_atr": str(max_adverse),
                "max_favorable_atr": str(max_favorable),
                "first_0p5atr_event": first_excursion,
                "first_adverse_at_ms": first_bad,
                "first_favorable_at_ms": first_good,
            }
        results.append({
            "symbol": ev["symbol"], "at_ms": t,
            "utc_day": _date(t),
            "ist_entry_hour": _ist_hour(t),
            "direction": ev["direction"], "lane": ev["lane"],
            "setup_type": ev["setup_type"], "regime": ev["regime"],
            "source_atr": str(atr),
            "predecision_source_extension_atr": str(source_extension),
            "predecision_ema20_ema50_separation_atr": str(ema_separation),
            "reference_entry_next_15m_open": str(entry),
            "horizons": horizons,
        })
    return results


def _bootstrap_day_mean(rows: list[dict], horizon: str) -> dict:
    groups = defaultdict(list)
    for item in rows:
        outcome = item["horizons"][horizon]
        if outcome["status"] == "OBSERVED":
            groups[item["utc_day"]].append(
                float(dec(outcome["signed_mark_after_illustrative_hurdle_bps"], "signed mark"))
            )
    if len(groups) < 10:
        return {
            "day_count": len(groups),
            "day_clustered_lower_95_mean_bps": None,
            "day_clustered_upper_95_mean_bps": None,
            "note": "Too few distinct days for exploratory day bootstrap",
        }
    by_day = [fmean(values) for _, values in sorted(groups.items())]
    rng = Random(481516)
    n = len(by_day)
    replicates = sorted(
        fmean(by_day[rng.randrange(n)] for _ in range(n))
        for _ in range(2048)
    )
    return {
        "day_count": n,
        "equal_day_mean_bps": str(fmean(by_day)),
        "day_clustered_lower_95_mean_bps": str(replicates[51]),
        "day_clustered_upper_95_mean_bps": str(replicates[1996]),
        "note": "Exploratory day bootstrap: serial dependence and signal selection can invalidate nominal interval",
    }


def summarize_directional_accuracy(rows: list[dict]) -> dict:
    """All eligible candidate events, never an ex-post cherry-picked cohort."""
    if not isinstance(rows, list):
        raise ValueError("Expect an explicit list of candidate events")
    report = {}
    for horizon in HORIZONS:
        key = str(horizon)
        complete = [r for r in rows if r["horizons"][key]["status"] == "OBSERVED"]
        n = len(complete)
        right = sum(r["horizons"][key]["direction_classification"] ==
                    "DIRECTION_SUPPORTED_OVER_HURDLE" for r in complete)
        opposite = sum(r["horizons"][key]["direction_classification"] ==
                       "DIRECTION_OPPOSITE_OVER_HURDLE" for r in complete)
        adverse_first = sum(r["horizons"][key]["first_0p5atr_event"] ==
                            "ADVERSE_FIRST" for r in complete)
        low, high = wilson_95(right, n)
        report[key] = {
            "observed_count": n,
            "censored_count": len(rows)-n,
            "direction_supported_over_hurdle": right,
            "direction_opposite_over_hurdle": opposite,
            "direction_neutral": n-right-opposite,
            "supported_fraction_of_all_observed": str(D(right)/n) if n else None,
            "opposite_fraction_of_all_observed": str(D(opposite)/n) if n else None,
            "marginal_wilson95_supported_fraction": [low, high],
            "adverse_first_0p5atr_count": adverse_first,
            "adverse_first_fraction_of_all_observed": str(D(adverse_first)/n) if n else None,
            "day_clustered_signed_mark_after_cost_hurdle": _bootstrap_day_mean(rows, key),
        }
    return report


def directional_accuracy_study(labeled: list[dict]) -> dict:
    fields = {
        "by_lane": ("v4_base", "15m_rescue"),
        "by_regime": ("established", "emerging"),
        "by_setup_type": ("pullback_continuation", "momentum_breakout"),
        "by_direction": ("long", "short"),
    }
    report = {
        "status": "REFERENCE_DIRECTIONAL_STUDY_NOT_EXECUTABLE_TRADE_PNL",
        "candidate_count": len(labeled),
        "overall": summarize_directional_accuracy(labeled),
    }
    for field, values in fields.items():
        source = field[3:]
        report[field] = {
            name: summarize_directional_accuracy(
                [r for r in labeled if r[source] == name]
            ) for name in values
        }
    report["by_symbol"] = {
        symbol: summarize_directional_accuracy(
            [r for r in labeled if r["symbol"] == symbol]
        ) for symbol in sorted({r["symbol"] for r in labeled})
    }
    report["by_ist_entry_hour"] = {
        hour: summarize_directional_accuracy([
            r for r in labeled if r["ist_entry_hour"] == hour
        ]) for hour in sorted({r["ist_entry_hour"] for r in labeled})
    }
    # Forensic examples are selected AFTER the fact and must NEVER define
    # a new trading rule without prospective independent validation.
    report["worst_12_opposite_direction_examples_by_horizon"] = {}
    for horizon in HORIZONS:
        key = str(horizon)
        opposite = [
            row for row in labeled
            if row["horizons"][key]["status"] == "OBSERVED"
            and row["horizons"][key]["direction_classification"]
                == "DIRECTION_OPPOSITE_OVER_HURDLE"
        ]
        opposite.sort(key=lambda row: (
            dec(row["horizons"][key]["signed_mark_bps"], "signed mark"),
            row["at_ms"], row["symbol"], row["lane"]
        ))
        report["worst_12_opposite_direction_examples_by_horizon"][key] = [
            {
                "symbol": r["symbol"], "at_ms": r["at_ms"],
                "direction": r["direction"], "lane": r["lane"],
                "setup_type": r["setup_type"], "regime": r["regime"],
                "ist_entry_hour": r["ist_entry_hour"],
                "predecision_source_extension_atr": r["predecision_source_extension_atr"],
                "signed_forward_bps": r["horizons"][key]["signed_mark_bps"],
                "first_0p5atr_event": r["horizons"][key]["first_0p5atr_event"],
                "max_adverse_atr": r["horizons"][key]["max_adverse_atr"],
                "max_favorable_atr": r["horizons"][key]["max_favorable_atr"],
            }
            for r in opposite[:12]
        ]
    # Predeclared decision-time directional screening hypotheses; subset
    # stats are purely descriptive and cannot estimate portfolio PnL.
    # The full chronological portfolio replay is a SEPARATE research stage.
    filters = {
        "ALL_CANDIDATES": lambda r: True,
        "ESTABLISHED_ONLY": lambda r: r["regime"] == "established",
        "NO_SOURCE_EXTENDED_BREAKOUT_OVER_1ATR": (
            lambda r: r["setup_type"] != "momentum_breakout"
            or dec(r["predecision_source_extension_atr"], "source extension") <= D(1)
        ),
        "ESTABLISHED_AND_NO_SOURCE_EXTENDED_BREAKOUT_OVER_1ATR": (
            lambda r: r["regime"] == "established"
            and (r["setup_type"] != "momentum_breakout"
                 or dec(r["predecision_source_extension_atr"], "source extension") <= D(1))
        ),
    }
    report["predeclared_predecision_filter_slices"] = {
        name: {
            "retained": sum(predicate(r) for r in labeled),
            "rejected": sum(not predicate(r) for r in labeled),
            "directional_accuracy_of_retained_candidate_references": (
                summarize_directional_accuracy([
                    r for r in labeled if predicate(r)
                ])
            ),
            "directional_accuracy_of_REJECTED_candidate_references": (
                summarize_directional_accuracy([
                    r for r in labeled if not predicate(r)
                ])
            ),
        }
        for name, predicate in filters.items()
    }
    digest = sha256()
    for item in sorted(labeled, key=lambda r: (
        r["at_ms"], r["symbol"], r["lane"], r["setup_type"]
    )):
        digest.update(json.dumps(
            item, sort_keys=True, separators=(",", ":")
        ).encode()+b"\n")
    report["directional_evidence_sha256"] = digest.hexdigest()
    report["assumptions"] = {
        "next_15m_open_reference": True,
        "illustrative_roundtrip_hurdle_bps": str(COST_BPS),
        "0p5atr_intracandle_tie_order": "ADVERSE_FIRST",
        "analysis_horizons_minutes": list(HORIZONS),
    }
    report["limitations"] = [
        "Forward Binance OHLC snapshots are market references, not observed fills",
        "No leverage, partial exits, funding, venue fees, book depth or portfolio concurrency",
        "Several overlapping signals may share the same price move and UTC-day bootstrap cannot remove all dependence",
        "BTC 15m/4h contradiction and live V4 risk veto require separate parity audit",
        "An after-cost hurdle is not a genuine after-cost execution simulation",
        "Predeclared filter slices do not model portfolio slot reuse, risk, fees or actual fills",
        "Worst-opposite examples are selected with FUTURE outcomes for forensic description only, never valid for rule selection",
        "Time-of-day breakdown involves multiple comparisons and cannot validate a time veto without independent data",
        "Development statistics must not be used to pick a filter and then quoted as independent accuracy",
    ]
    return report
