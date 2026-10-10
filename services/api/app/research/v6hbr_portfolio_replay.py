"""Isolated chronological V6HBR V4/H/B/R portfolio-policy reducer.

Requires externally priced, time-stamped execution-reference scenarios.
Candidate selection only reads outcomes of ALREADY published earlier entries
and only at timestamps available at the current decision. Neither candidate
future returns nor the final holdout can drive ranking or risk decisions.

This is a research component, not certified cross-margin or live execution.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal as D
from zoneinfo import ZoneInfo

HOUR = 3_600_000
CIRCUIT_WINDOW = 2 * HOUR
CIRCUIT_PAUSE = 2 * HOUR
IST = ZoneInfo("Asia/Kolkata")
CLOSED = frozenset(("STOP", "PROTECTED_STOP", "TP3"))


def _decimal(value, label: str) -> D:
    try:
        result = D(str(value))
    except (ValueError, ArithmeticError) as exc:
        raise ValueError(f"Invalid {label}") from exc
    if not result.is_finite():
        raise ValueError(f"Nonfinite {label}")
    return result


def _sort_key(row):
    return (
        row["at_ms"],
        _decimal(row["recent_run_atr"], "recent_run_atr"),
        _decimal(row["source_extension_atr"], "source_extension_atr"),
        0 if row["regime"] == "established" else 1,
        row["symbol"], row["id"],
    )


def _validate(rows, risk_unit: D, max_aggregate_risk: D):
    if risk_unit <= 0 or max_aggregate_risk < risk_unit:
        raise ValueError("Explicit positive risk budget required")
    identities = set()
    for row in rows:
        if row["id"] in identities:
            raise ValueError("Duplicate candidate identity")
        identities.add(row["id"])
        if (
            type(row["at_ms"]) is not int
            or row["at_ms"] < 0
            or row["at_ms"] % (15 * 60_000)
            or row["lane"] not in ("v4_base", "15m_rescue")
            or row["direction"] not in ("long", "short")
            or row["regime"] not in ("established", "emerging")
            or not row["symbol"]
        ):
            raise ValueError("Invalid candidate or closed-candle boundary")
        _sort_key(row)
        if row.get("preliminary_reason"):
            continue
        outcome = row.get("outcome")
        if outcome is None:
            raise ValueError("Priced candidate lacks execution outcome")
        status = outcome.get("status")
        if status not in (CLOSED | {"OPEN_UNRESOLVED", "NO_FILL_REFERENCE"}):
            raise ValueError("Unsupported execution outcome status")
        if status in CLOSED:
            t = outcome.get("terminal_at_ms")
            if type(t) is not int or t <= row["at_ms"]:
                raise ValueError("Invalid terminal event chronology")
            _decimal(outcome["net_realized_r"], "net_realized_r")
        elif outcome.get("net_realized_r") is not None:
            raise ValueError("Unresolved trade cannot book terminal net R")
        for milestone in ("adverse_050_at_ms", "favorable_050_at_ms"):
            if milestone not in outcome:
                raise ValueError("Missing circuit-breaker milestone evidence")
            at = outcome[milestone]
            if at is not None and (type(at) is not int or at <= row["at_ms"]):
                raise ValueError("Milestone precedes publication")
    return rows


def _paused(accepted: list[dict], direction: str, now: int) -> bool:
    """V4-style two adverse-first 0.5R events in a trailing 120m window."""
    events = []
    for prior in accepted:
        if prior["direction"] != direction:
            continue
        out = prior["outcome"]
        adverse = out["adverse_050_at_ms"]
        favorable = out["favorable_050_at_ms"]
        if adverse is None or adverse > now:
            continue
        if favorable is not None and favorable < adverse:
            continue
        events.append((adverse, prior))
    events.sort(key=lambda item: (item[0], item[1]["id"]))
    for trigger, _ in events:
        if not trigger <= now < trigger + CIRCUIT_PAUSE:
            continue
        members = sum(
            at <= trigger and trigger - CIRCUIT_WINDOW <= row["at_ms"] <= trigger
            for at, row in events
        )
        if members >= 2:
            return True
    return False


def _running_fraction(row, now: int) -> D:
    """Conservative partial-exit risk occupancy; no margin/leverage assumption."""
    out = row["outcome"]
    if out["status"] in CLOSED and out["terminal_at_ms"] <= now:
        return D(0)
    remaining = D(1)
    for event in out.get("exits", []):
        # Minute exit timestamps become usable only AFTER the full minute ends.
        if event["at_ms"] + 60_000 <= now:
            remaining -= _decimal(event["fraction"], "partial fraction")
    if remaining < 0 or remaining > 1:
        raise ValueError("Invalid remaining trade fraction")
    return remaining


def simulate_cohort(
    rows: list[dict],
    cohort: str,
    *,
    risk_unit: D,
    max_aggregate_risk: D,
    max_active_same_direction: int = 6,
) -> dict:
    """Run a cohort in its own prospective state; no cross-cohort interaction.

    Risk units are operator-provided simulation assumptions, not MV defaults.
    """
    if cohort not in ("V4", "H", "B", "R"):
        raise ValueError("Unknown research cohort")
    risk_unit = _decimal(risk_unit, "risk unit")
    max_aggregate_risk = _decimal(max_aggregate_risk, "aggregate risk")
    if type(max_active_same_direction) is not int or max_active_same_direction < 1:
        raise ValueError("Invalid active reference cap")
    _validate(rows, risk_unit, max_aggregate_risk)
    accepted: list[dict] = []
    audit = []
    seen: set[tuple[str, str, str]] = set()
    for row in sorted(rows, key=_sort_key):
        at = row["at_ms"]
        clock = datetime.fromtimestamp(at / 1000, timezone.utc).astimezone(IST)
        reason = row.get("preliminary_reason")
        if not 9 <= clock.hour < 23:
            reason = reason or "OUTSIDE_IST_SESSION"
        if cohort == "V4" and row["lane"] != "v4_base":
            reason = reason or "NOT_V4_LANE"
        if cohort == "B" and row["regime"] == "emerging":
            if row.get("balanced_reason") is not None:
                reason = reason or row["balanced_reason"]
            elif not row.get("balanced_confirmed", False):
                reason = reason or "BALANCED_15M_UNVERIFIED"
        if not reason and row["outcome"]["status"] == "NO_FILL_REFERENCE":
            reason = "NO_FILL_REFERENCE"
        key = (clock.date().isoformat(), row["symbol"], row["direction"])
        active = [
            prior for prior in accepted
            if _running_fraction(prior, at) > 0
        ]
        active_direction = [x for x in active if x["direction"] == row["direction"]]
        if not reason and key in seen:
            reason = "SAME_DIRECTION_SIGNAL_THIS_SESSION"
        if not reason and any(x["symbol"] == row["symbol"] for x in active):
            reason = "SYMBOL_ALREADY_ACTIVE"
        if not reason and _paused(accepted, row["direction"], at):
            reason = "DIRECTIONAL_CIRCUIT_BREAKER"
        if not reason and len(active_direction) >= max_active_same_direction:
            reason = "ACTIVE_DIRECTIONAL_EXPOSURE_LIMIT"
        if not reason and (
            sum((_running_fraction(x, at) * risk_unit for x in active), D(0))
            + risk_unit > max_aggregate_risk
        ):
            reason = "PROXY_AGGREGATE_RISK_CAP"
        if not reason:
            if cohort == "V4":
                same_bucket = sum(
                    x["direction"] == row["direction"]
                    and x["context_open_ms"] == row["context_open_ms"]
                    for x in accepted
                )
                if same_bucket >= 2:
                    reason = "V4_SOURCE_CONCENTRATION_LIMIT"
            else:
                recent = [
                    prior for prior in accepted
                    if prior["direction"] == row["direction"]
                    and at - HOUR < prior["at_ms"] <= at
                ]
                if len(recent) >= 2:
                    reason = "ROLLING_MARKET_DIRECTION_CONCENTRATION_LIMIT"
                if cohort == "R" and row["lane"] == "15m_rescue":
                    if sum(x["lane"] == "15m_rescue" for x in recent) >= 1:
                        reason = "RESCUE_LANE_ROLLING_LIMIT"
        if reason is None:
            seen.add(key)
            accepted.append(row)
        audit.append({
            "id": row["id"],
            "at_ms": at,
            "symbol": row["symbol"],
            "lane": row["lane"],
            "direction": row["direction"],
            "decision": "ACCEPTED_REFERENCE" if reason is None else reason,
            "prior_accepted_ids": [x["id"] for x in accepted if x["at_ms"] < at],
        })

    closed = [
        x for x in accepted
        if x["outcome"]["status"] in CLOSED
    ]
    unresolved = [x for x in accepted if x["outcome"]["status"] == "OPEN_UNRESOLVED"]
    net = sum((_decimal(x["outcome"]["net_realized_r"], "net R") for x in closed), D(0))
    return {
        "cohort": cohort,
        "status": "PROXY_PORTFOLIO_RESEARCH_NOT_CERTIFIED",
        "total_input_candidates": len(rows),
        "accepted_references": len(accepted),
        "resolved_references": len(closed),
        "unresolved_references": len(unresolved),
        "resolved_net_r_sum": str(net),
        "resolved_net_r_mean": str(net / len(closed)) if closed else None,
        "rejections": dict(sorted(Counter(
            x["decision"] for x in audit if x["decision"] != "ACCEPTED_REFERENCE"
        ).items())),
        "accepted_ids": [x["id"] for x in accepted],
        "audit": audit,
        "limitations": [
            "Outcomes are scenario-based Binance OHLCV references, not Lighter fills",
            "Risk units require explicit operator assumptions; not cross-margin certification",
            "Unresolved positions are excluded from terminal net R, not assumed winners",
            "BTC-only cannot establish 30-symbol Reserved crowd-out or correlation benefit",
        ],
    }
