"""V6HBR post-hoc *resolved-trade* quality and cost sensitivity diagnostics.

Runs ONLY after a cohort's entry decisions and individual price-reference
outcomes have been finalized. Does not modify policy, entries or stops.
Not MTM drawdown, not a tradable equity curve, not observed fees/fills.
The 3x3 scenario grid rescales already-debited fees/funding on FIXED trades:
spread, slippage, fill geometry, eligibility, risk caps and funding schedule
are not repriced or re-simulated. Results remain illustrative.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal as D

from .v6hbr_portfolio_replay import CLOSED
from .v6hbr_decimal_reconciliation import exact_reference_sum

LANES = ("v4_base", "15m_rescue")
COST_MULTIPLIERS = (D(0), D(1), D(2))


def _dec(value, label: str) -> D:
    try:
        number = D(str(value))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError("Invalid " + label) from exc
    if not number.is_finite():
        raise ValueError("Nonfinite " + label)
    return number


def _fmt(value: D) -> str:
    return str(value)


def _stats(rows: list[dict]) -> dict:
    """Only terminally resolved accepted references; zero trades means N/A."""
    values = [r["net"] for r in rows]
    positive = [r for r in values if r > 0]
    negative = [r for r in values if r < 0]
    # All cohorts, lanes, regimes and time slices sum exact *booked*
    # amounts. Ambient Decimal context rounding is order-dependent.
    gross = exact_reference_sum(r["gross"] for r in rows)
    fee = exact_reference_sum(r["fees"] for r in rows)
    funding = exact_reference_sum(r["funding"] for r in rows)
    net = exact_reference_sum(values)
    return {
        "resolved_count": len(rows),
        "positive_count": len(positive),
        "negative_count": len(negative),
        "flat_count": len(values) - len(positive) - len(negative),
        "positive_fraction": _fmt(D(len(positive)) / len(rows)) if rows else None,
        "resolved_gross_r_sum": _fmt(gross),
        "resolved_fee_debit_r_sum": _fmt(fee),
        "resolved_funding_debit_r_sum": _fmt(funding),
        "resolved_net_r_sum": _fmt(net),
        "resolved_net_r_mean": _fmt(net / len(rows)) if rows else None,
        "profit_factor_net": (
            _fmt(exact_reference_sum(positive) / -exact_reference_sum(negative))
            if negative else None
        ),
        "mean_positive_net_r": (
            _fmt(exact_reference_sum(positive) / len(positive)) if positive else None
        ),
        "mean_negative_net_r": (
            _fmt(exact_reference_sum(negative) / len(negative)) if negative else None
        ),
        "ambiguous_stop_target_minutes": sum(r["ambiguous"] for r in rows),
        "mean_holding_minutes": (
            _fmt(sum((r["holding_minutes"] for r in rows), D(0)) / len(rows))
            if rows else None
        ),
    }


def _terminal_drawdown(rows: list[dict]) -> dict:
    """Close-only, terminal-receipt ordering; NOT intra-position drawdown."""
    equity = peak = max_dd = D(0)
    worst_at = None
    ordered = sorted(rows, key=lambda r: (r["terminal_at_ms"], r["id"]))
    for row in ordered:
        equity = exact_reference_sum((equity, row["net"]))
        peak = max(peak, equity)
        dd = exact_reference_sum((peak, -equity))
        if dd > max_dd:
            max_dd = dd
            worst_at = row["terminal_at_ms"]
    return {
        "classification": "CLOSED_TERMINAL_ONLY_NOT_INTRATRADE_EQUITY_DRAWDOWN",
        "resolved_closed_net_r_sum": _fmt(equity),
        "closed_peak_to_trough_drawdown_r": _fmt(max_dd),
        "closed_peak_to_trough_worst_terminal_at_ms": worst_at,
        "note": "Parallel open risk, mark-to-market equity and unresolved positions are not included",
    }


def _cost_sensitivity(rows: list[dict]) -> list[dict]:
    base_fee = exact_reference_sum(r["fees"] for r in rows)
    base_funding = exact_reference_sum(r["funding"] for r in rows)
    base_net = exact_reference_sum(r["net"] for r in rows)
    grid = []
    for fm in COST_MULTIPLIERS:
        for um in COST_MULTIPLIERS:
            # Perturb already-booked reference net outcomes; 1x/1x is
            # definitionally identical to the portfolio ledger. Do not
            # rederive base P&L from rounded intermediate gross and fees.
            value = exact_reference_sum((
                base_net, (D(1) - fm) * base_fee,
                (D(1) - um) * base_funding,
            ))
            grid.append({
                "fee_multiplier": str(fm),
                "funding_multiplier": str(um),
                "hypothetical_resolved_net_r_sum": _fmt(value),
            })
    return grid


def quality_report(priced: list[dict], cohorts: dict[str, dict],
                   *, end_exclusive_ms: int) -> dict:
    """Compute descriptive metrics using only settled, preselected entries.

    UTC timestamp for the stop boundary must match the replay's fixed window.
    Ineligible and rejected candidate outcomes are never included.
    """
    if type(end_exclusive_ms) is not int or end_exclusive_ms <= 0:
        raise ValueError("Invalid analysis cutoff")
    indexed = {row["id"]: row for row in priced}
    if len(indexed) != len(priced):
        raise ValueError("Duplicate candidate identity in quality report")
    if set(cohorts) != {"V4", "H", "B", "R"}:
        raise ValueError("Four independent cohorts required")
    results = {}
    for name in ("V4", "H", "B", "R"):
        cohort = cohorts[name]
        accepted = cohort["accepted_ids"]
        if len(set(accepted)) != len(accepted):
            raise ValueError("Repeated accepted identity")
        if any(identity not in indexed for identity in accepted):
            raise ValueError("Unknown accepted candidate")
        resolved = []
        unresolved = 0
        for identity in accepted:
            row = indexed[identity]
            out = row["outcome"]
            if out is None:
                raise ValueError("Accepted candidate missing pricing outcome")
            status = out["status"]
            if status == "OPEN_UNRESOLVED":
                if out["net_realized_r"] is not None:
                    raise ValueError("Unresolved position has terminal net R")
                unresolved += 1
                continue
            if status not in CLOSED:
                raise ValueError("Accepted trade has unsupported outcome")
            terminal = out["terminal_at_ms"]
            at = row["at_ms"]
            entry = out["entry_at_ms"]
            if (type(terminal) is not int or type(entry) is not int
                    or not at < entry < terminal <= end_exclusive_ms):
                raise ValueError("Noncausal or out-of-window resolved trade")
            gross = _dec(out["gross_realized_r"], "gross")
            fees = _dec(out["fee_debit_r"], "fee")
            funding = _dec(out["funding_debit_r"], "funding")
            net = _dec(out["net_realized_r"], "net")
            if fees < 0 or funding < 0 or gross - fees - funding != net:
                raise ValueError("Fee/funding/net reconciliation failed")
            ambiguous = out["intraminute_stop_first_ties"]
            if type(ambiguous) is not int or ambiguous < 0:
                raise ValueError("Invalid intraminute tie count")
            resolved.append({
                "id": identity,
                "lane": row["lane"],
                "direction": row["direction"],
                "regime": row["regime"],
                "entry_month_utc": datetime.fromtimestamp(
                    at / 1000, timezone.utc
                ).strftime("%Y-%m"),
                "terminal_at_ms": terminal,
                "net": net,
                "gross": gross,
                "fees": fees,
                "funding": funding,
                "ambiguous": ambiguous,
                "holding_minutes": D(terminal - entry) / 60_000,
            })
        if len(resolved) != cohort["resolved_references"]:
            raise ValueError("Resolved count inconsistent with cohort replay")
        if unresolved != cohort["unresolved_references"]:
            raise ValueError("Unresolved count inconsistent with cohort replay")
        overall = _stats(resolved)
        quality_net = _dec(overall["resolved_net_r_sum"], "quality net R")
        cohort_net = _dec(cohort["resolved_net_r_sum"], "cohort net R")
        if quality_net != cohort_net:
            raise ValueError(
                "Resolved quality net R contradicts portfolio "
                f"(cohort={name}, quality={quality_net}, portfolio={cohort_net}, "
                f"discrepancy={exact_reference_sum((quality_net, -cohort_net))})"
            )
        split = {}
        for grouping, group_keys in (
            ("lane", LANES),
            ("direction", ("long", "short")),
            ("regime", ("established", "emerging")),
        ):
            split[grouping] = {
                key: _stats([r for r in resolved if r[grouping] == key])
                for key in group_keys
            }
        month_rows = defaultdict(list)
        for r in resolved:
            month_rows[r["entry_month_utc"]].append(r)
        results[name] = {
            "status": "FIXED_COHORT_POST_HOC_RESOLVED_TRADES_ONLY",
            "accepted_count": len(accepted),
            "unresolved_count_excluded_from_pnl": unresolved,
            "overall": overall,
            "by_group": split,
            "by_entry_month_utc": {
                month: _stats(rows) for month, rows in sorted(month_rows.items())
            },
            "terminal_only_drawdown": _terminal_drawdown(resolved),
            "fixed_trade_fee_funding_multiplier_grid": _cost_sensitivity(resolved),
        }
    return {
        "status": "POST_HOC_COST_SCENARIO_QUALITY_NOT_LIVE_TRADING_PNL",
        "cohorts": results,
        "limitations": [
            "No observed spread, venue fill, fee tier or actual funding history",
            "Fixed trades and exits; fee/funding multiplier grid does not reprice spread, slippage, protective stops, candidate qualification or fills",
            "Drawdown uses terminal settlement only; intra-position drawdown and open risk unknown",
            "Unresolved and rejected counterfactual outcomes never contribute terminal net R",
            "BTC April-May development only; too few trades to establish superiority",
        ],
    }
