"""Offline audit of *actual published* MV V4 signal analytics rows.

Accepted input is an explicitly exported, sanitized list of already recorded
SignalOutcome fields. NO database access, SSH, networking, Telegram payloads,
or user/venue credentials. This is reference analytics, NOT actual user fills.
Always separate source revisions, unfinished and short-observation records.

Adverse/favorable milestones are persisted by the production analytics worker;
ties within a candle count adverse-first, never optimistic favorable-first.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D, InvalidOperation
import json

STRATEGY = "MV-TREND-DUAL-v4"
MINUTE = 60_000
HOUR = 60 * MINUTE
RESOLVED = frozenset((
    "target", "tp3", "stop", "protected_be", "protected_tp1", "ambiguous"
))
ALLOWED = RESOLVED | {"open", "source_revised"}
REQUIRED = (
    "strategy", "symbol", "direction", "setup_type", "trend_regime",
    "published_at", "first_observed_minute", "status", "observed_bars",
    "source_revised", "intrabar_ambiguous", "favorable_050_at",
    "adverse_050_at", "mae_r", "mfe_r", "conservative_r",
)


def _decimal(value, field: str) -> D:
    try:
        result = D(str(value))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid " + field) from exc
    if not result.is_finite():
        raise ValueError("Nonfinite " + field)
    return result


def _fraction(n, d):
    return str(D(n) / d) if d else None


def _group(rows: list[dict]) -> dict:
    n = len(rows)
    observed = [r for r in rows if r["observed_bars"] > 0]
    qualified = [r for r in observed if not r["source_revised"]]
    resolved = [r for r in qualified if r["status"] in RESOLVED]
    with_r = [r["conservative_r"] for r in resolved]
    losses = [v for v in with_r if v < 0]
    wins = [v for v in with_r if v > 0]
    adverse_first = sum(r["first"] == "ADVERSE_FIRST" for r in qualified)
    early = sum(r["early_adverse_first"] for r in qualified)
    return {
        "published_reference_count": n,
        "observed_reference_count": len(observed),
        "usable_nonrevised_observed_count": len(qualified),
        "source_revised_count": sum(r["source_revised"] for r in rows),
        "open_unresolved_count": sum(r["status"] == "open" for r in rows),
        "resolved_count": len(resolved),
        "negative_resolved_count": len(losses),
        "positive_resolved_count": len(wins),
        "flat_resolved_count": len(with_r) - len(losses) - len(wins),
        "negative_fraction_of_resolved": _fraction(len(losses), len(resolved)),
        "adverse_0p5r_first_or_tied": adverse_first,
        "adverse_first_fraction_of_observed_nonrevised": _fraction(
            adverse_first, len(qualified)
        ),
        "adverse_0p5r_first_in_first_60m": early,
        "early_adverse_first_fraction_of_observed_nonrevised": _fraction(
            early, len(qualified)
        ),
        "mean_resolved_reference_r": (
            str(sum(with_r, D(0)) / len(with_r)) if with_r else None
        ),
        "median_observed_mae_r": (
            str(sorted(r["mae_r"] for r in qualified)[len(qualified)//2])
            if len(qualified) % 2 else
            str((sorted(r["mae_r"] for r in qualified)[len(qualified)//2 - 1] +
                 sorted(r["mae_r"] for r in qualified)[len(qualified)//2]) / 2)
            if qualified else None
        ),
        "intrabar_ambiguous_count": sum(
            r["intrabar_ambiguous"] for r in rows
        ),
    }


def analyze_live_v4(records: list[dict], *, start_ms: int, end_ms: int) -> dict:
    """Summarize only time-scoped MV V4 published reference analytics.

    Not intended for deriving a new live rule from the same evaluation sample.
    Observed and resolved denominators are intentionally distinct.
    """
    if (type(start_ms) is not int or type(end_ms) is not int
            or not 0 < start_ms < end_ms or end_ms - start_ms > 31 * 24 * HOUR):
        raise ValueError("Explicit <=31-day UTC study window required")
    if type(records) is not list or len(records) > 100_000:
        raise ValueError("Invalid finite record batch")
    rows = []
    for raw in records:
        if not isinstance(raw, dict) or any(k not in raw for k in REQUIRED):
            raise ValueError("Missing required sanitized signal-outcome fields")
        if raw["strategy"] != STRATEGY:
            raise ValueError("Non-V4 strategy outcome in V4 analysis")
        pub = raw["published_at"]
        if type(pub) is not int or pub < start_ms or pub >= end_ms:
            raise ValueError("Outcome outside the explicit time window")
        first = raw["first_observed_minute"]
        if type(first) is not int or first < pub or first % MINUTE:
            raise ValueError("Invalid first observed minute")
        status = raw["status"]
        if status not in ALLOWED:
            raise ValueError("Unrecognized production outcome status")
        if (raw["direction"] not in ("long", "short")
                or not raw["symbol"] or not raw["setup_type"]
                or raw["trend_regime"] not in ("established", "emerging")
                or type(raw["observed_bars"]) is not int
                or raw["observed_bars"] < 0
                or type(raw["source_revised"]) is not bool
                or type(raw["intrabar_ambiguous"]) is not bool):
            raise ValueError("Invalid direction/regime/evidence flags")
        if raw["source_revised"] and status not in ("source_revised", "open"):
            raise ValueError("Source-revised row not excluded from resolved sample")
        favorable, adverse = raw["favorable_050_at"], raw["adverse_050_at"]
        for field, t in (("favorable_050_at", favorable),
                         ("adverse_050_at", adverse)):
            if t is not None and (type(t) is not int or t < first or t % MINUTE):
                raise ValueError("Invalid " + field)
        if not raw["observed_bars"] and (favorable is not None or adverse is not None):
            raise ValueError("Milestones without observed bars")
        r = (_decimal(raw["conservative_r"], "conservative_r")
             if raw["conservative_r"] is not None else None)
        if status in RESOLVED and r is None:
            raise ValueError("Resolved trade without conservative R")
        if status not in RESOLVED and r is not None:
            raise ValueError("Unresolved/revised trade cannot book terminal R")
        mae = _decimal(raw["mae_r"], "mae_r")
        mfe = _decimal(raw["mfe_r"], "mfe_r")
        if mae < 0 or mfe < 0:
            raise ValueError("Negative magnitude MFE/MAE")
        first_event = (
            "ADVERSE_FIRST" if adverse is not None
            and (favorable is None or adverse <= favorable) else
            "FAVORABLE_FIRST" if favorable is not None else "NONE"
        )
        rows.append({
            "symbol": raw["symbol"],
            "direction": raw["direction"],
            "setup_type": raw["setup_type"],
            "trend_regime": raw["trend_regime"],
            "utc_day": datetime.fromtimestamp(pub / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "status": status,
            "source_revised": raw["source_revised"],
            "observed_bars": raw["observed_bars"],
            "first": first_event,
            "early_adverse_first": (
                first_event == "ADVERSE_FIRST"
                and adverse is not None
                and adverse <= first + HOUR
            ),
            "conservative_r": r,
            "mae_r": mae,
            "mfe_r": mfe,
            "intrabar_ambiguous": raw["intrabar_ambiguous"],
        })
    dimensions = {
        "by_day_utc": "utc_day",
        "by_symbol": "symbol",
        "by_direction": "direction",
        "by_setup": "setup_type",
        "by_trend_regime": "trend_regime",
    }
    groups = {}
    for label, field in dimensions.items():
        members = defaultdict(list)
        for row in rows:
            members[row[field]].append(row)
        groups[label] = {
            key: _group(batch) for key, batch in sorted(members.items())
        }
    return {
        "status": "PRODUCTION_V4_REFERENCE_OUTCOME_FORENSIC_NOT_USER_FILL_PNL",
        "strategy": STRATEGY,
        "window_start_utc_ms": start_ms,
        "window_end_exclusive_utc_ms": end_ms,
        "overall": _group(rows),
        **groups,
        "limitations": [
            "Production signal_outcomes are market-reference analytics, not actual operator fill P&L",
            "MFE/MAE and +/-0.5R event times are from 1m candle ranges, not ordered intrabar ticks",
            "Same-minute adverse/favorable ties count adverse-first",
            "Short-observation and unresolved cases are not assumed successful",
            "No causal conclusion on BTC regime, setup or trend can be made without auditing source evidence",
            "No automated access to live VPS records is provided by this pure analysis module",
        ],
    }


def main():
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Offline MV V4 production analytics forensic")
    parser.add_argument("--input", required=True, help="Sanitized SignalOutcome JSON list (no secrets)")
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    args = parser.parse_args()
    records = json.loads(Path(args.input).read_text(encoding="utf-8"))
    print(json.dumps(
        analyze_live_v4(records, start_ms=args.start_ms, end_ms=args.end_ms),
        sort_keys=True, indent=2,
    ))


if __name__ == "__main__":
    main()
