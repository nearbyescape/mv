"""Post-hoc V6HBR time-of-day, month-stability and shared-market error audit.

Every entry hour is scanned WITHOUT selecting a best hour to trade.
Cross-symbol simultaneous candidate observations are not independent trials.
Only completed 60-minute reference marks count; censored marks remain censored.

This is DESCRIPTIVE RESEARCH on held development data, never a live rule.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D

from .v6hbr_directional_accuracy import HORIZONS, _ist_hour

HORIZON = "60"
SUPPORTED = "DIRECTION_SUPPORTED_OVER_HURDLE"
OPPOSITE = "DIRECTION_OPPOSITE_OVER_HURDLE"
NEUTRAL = "NEUTRAL_WITHIN_HURDLE"


def _summary(rows: list[dict]) -> dict:
    complete = [
        x for x in rows if x["horizons"][HORIZON]["status"] == "OBSERVED"
    ]
    classes = Counter(
        x["horizons"][HORIZON]["direction_classification"] for x in complete
    )
    if set(classes) - {SUPPORTED, OPPOSITE, NEUTRAL}:
        raise ValueError("Unknown completed forward-direction classification")
    if len(complete) + sum(
        x["horizons"][HORIZON]["status"] == "CENSORED" for x in rows
    ) != len(rows):
        raise ValueError("Unknown forward-direction observation state")
    days = Counter(x["utc_day"] for x in rows)
    n = len(complete)
    return {
        "candidates": len(rows),
        "observed_60m": n,
        "censored_60m": len(rows) - n,
        "supported_60m": classes[SUPPORTED],
        "opposite_60m": classes[OPPOSITE],
        "neutral_60m": classes[NEUTRAL],
        "supported_fraction_of_observed": str(D(classes[SUPPORTED]) / n) if n else None,
        "opposite_fraction_of_observed": str(D(classes[OPPOSITE]) / n) if n else None,
        "distinct_utc_days": len(days),
        "max_one_utc_day_candidate_count": max(days.values(), default=0),
        "distinct_publication_boundaries": len({x["at_ms"] for x in rows}),
    }


def hour_and_cross_market_forensics(labeled: list[dict]) -> dict:
    if not isinstance(labeled, list):
        raise ValueError("Expected list of labeled candidate observations")
    by_hour: dict[str, list[dict]] = defaultdict(list)
    by_publication: dict[int, list[dict]] = defaultdict(list)
    for row in labeled:
        if not isinstance(row, dict) or row.get("utc_day") is None:
            raise ValueError("Candidate label lacks a UTC day")
        hour = _ist_hour(row["at_ms"])
        if row.get("ist_entry_hour") != hour:
            raise ValueError("Inconsistent candidate IST hour")
        by_hour[hour].append(row)
        by_publication[row["at_ms"]].append(row)
    hour_stats = {}
    for hour, observations in sorted(by_hour.items()):
        by_month = defaultdict(list)
        by_direction = defaultdict(list)
        for item in observations:
            month = datetime.fromtimestamp(
                item["at_ms"] / 1000, timezone.utc
            ).strftime("%Y-%m")
            by_month[month].append(item)
            by_direction[item["direction"]].append(item)
        hour_stats[hour] = {
            "overall_60m": _summary(observations),
            "by_utc_month_60m": {
                month: _summary(rows) for month, rows in sorted(by_month.items())
            },
            "by_direction_60m": {
                direction: _summary(by_direction.get(direction, []))
                for direction in ("long", "short")
            },
        }

    coincidences = []
    for t, observations in sorted(by_publication.items()):
        symbols = {r["symbol"] for r in observations}
        if len(symbols) < 2:
            continue
        observed = [
            row for row in observations
            if row["horizons"][HORIZON]["status"] == "OBSERVED"
        ]
        opposing = [
            row for row in observed if row["horizons"][HORIZON][
                "direction_classification"] == OPPOSITE
        ]
        cases = [
            {
                "symbol": r["symbol"], "direction": r["direction"],
                "lane": r["lane"], "setup_type": r["setup_type"],
                "outcome": r["horizons"][HORIZON]["direction_classification"]
                    if r["horizons"][HORIZON]["status"] == "OBSERVED"
                    else "CENSORED",
                "signed_forward_bps": r["horizons"][HORIZON].get("signed_mark_bps"),
            } for r in sorted(observations, key=lambda r: (
                r["symbol"], r["lane"], r["setup_type"]
            ))
        ]
        coincidences.append({
            "at_ms": t,
            "ist_hour": _ist_hour(t),
            "symbol_count": len(symbols),
            "candidate_count": len(observations),
            "opposite_60m_count": len(opposing),
            "cases": cases,
        })
    worst_shared = sorted(
        (x for x in coincidences if x["opposite_60m_count"]),
        key=lambda r: (-r["opposite_60m_count"], -r["symbol_count"], r["at_ms"])
    )
    return {
        "status": "EXPLORATORY_POSTHOC_60M_TIMING_AND_CROSS_MARKET_DEPENDENCE",
        "by_ist_hour": hour_stats,
        "simultaneous_multi_symbol": {
            "unique_shared_publication_boundaries": len(coincidences),
            "candidate_observations_sharing_multi_symbol_boundary": sum(
                x["candidate_count"] for x in coincidences
            ),
            "shared_publications_with_two_or_more_wrong": sum(
                x["opposite_60m_count"] >= 2 for x in coincidences
            ),
            "worst_shared_publications_first_12": worst_shared[:12],
        },
        "limitations": [
            "All timing patterns were inspected after examining development outcomes",
            "No hour-specific veto can be approved using these same observations",
            "UTC days and months are grouped descriptively; May and April are not independent holdouts",
            "BTC and ETH can fail simultaneously because of correlated market moves",
            "Only original rule-qualified candidates, not safety-filtered Telegram alerts or fills",
            "All 15m/30m/120m directional marks are reported in the parallel full accuracy study",
        ],
    }
