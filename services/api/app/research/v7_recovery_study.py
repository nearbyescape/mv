"""Costed multi-month V7Sonic recovery research assessment; NO live signals.

Requires six complete verified publisher ZIP/.CHECKSUM pairs per month.
Every candle/exit is retrospectively observable only; fills and intrabar
barrier ordering are NOT verified. No strategy selection on this evidence.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import random
from statistics import mean

from .v7_recovery_archives import MARKETS, MONTHS, verified_series
from .v7_recovery_engine import (
    POLICY, POLICY_SHA256, portfolio_simulation,
    MAX_REFERENCE_RISK_PER_IDEA_PCT,
)

IST = timezone(timedelta(minutes=330))
BOOTSTRAPS = 1000
BOOTSTRAP_SEED = 20261014


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts / 1000, IST).strftime("%Y-%m-%d")


def _summary(trades: list[dict], days: list[str]) -> dict:
    ordered = sorted(trades, key=lambda t: (
        t["exit_boundary_ms"], t["symbol"], t["decision_boundary_ms"]
    ))
    valid = [t for t in ordered if t["outcome"] != "CENSORED"]
    if not days:
        raise ValueError("Zero complete calendar days")
    allowed = set(days)
    if any(_day(t["decision_boundary_ms"]) not in allowed for t in valid):
        raise ValueError("Trades escape the specified assessment period")
    daily = {d: [] for d in days}
    for t in valid:
        daily[_day(t["decision_boundary_ms"])].append(t["net_R"])
    values = [t["net_R"] for t in valid]
    mean_r = mean(values) if values else None
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for trade in valid:
        equity *= max(0.000001, 1 + trade["net_R"] *
                      MAX_REFERENCE_RISK_PER_IDEA_PCT / 100)
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak-equity)/peak)
    day_groups = [daily[x] for x in days]
    randomizer = random.Random(BOOTSTRAP_SEED)
    bootstrap = []
    for _ in range(BOOTSTRAPS):
        sampled = [day_groups[randomizer.randrange(len(day_groups))]
                   for __ in range(len(day_groups))]
        total = sum(sum(day) for day in sampled)
        count = sum(len(day) for day in sampled)
        bootstrap.append(total/count if count else 0.0)
    bootstrap.sort()
    return {
        "calendar_days": len(days),
        "days_with_closed_ideas": sum(bool(x) for x in daily.values()),
        "hypothetical_closed_ideas": len(valid),
        "censored_ideas_excluded": len(ordered)-len(valid),
        "wins_net_of_modeled_cost": sum(x > 0 for x in values),
        "losses_or_flat_net_of_modeled_cost": sum(x <= 0 for x in values),
        "mean_costed_R_per_closed_reference": round(mean_r, 6) if mean_r is not None else None,
        "win_rate": round(sum(x > 0 for x in values) / len(values), 5) if values else None,
        "day_cluster_bootstrap_mean_R_95pct": [
            round(bootstrap[24], 6), round(bootstrap[975], 6)
        ],
        "stop_first_ambiguous_bar_count": sum(
            t["outcome"] == "AMBIGUOUS_STOP_FIRST" for t in valid
        ),
        "modeled_target_hit": sum(t["outcome"] == "TARGET" for t in valid),
        "stop_or_ambiguous": sum(t["outcome"] in (
            "STOP", "AMBIGUOUS_STOP_FIRST"
        ) for t in valid),
        "time_or_session_exit": sum(t["outcome"] in (
            "TIME_EXIT", "SESSION_EXIT"
        ) for t in valid),
        "illustrative_equity_change_if_0_5pct_risk_each": round(equity-1, 6),
        "illustrative_closed_trades_only_max_drawdown": round(drawdown, 6),
        "reference_equity_not_realized_pnl": True,
        "bootstrap_independent_trade_assumption": False,
    }


def run_study(root: Path, *, months: tuple[str, ...] = MONTHS) -> dict:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise ValueError("Absolute research archive root required")
    if months != MONTHS:
        raise ValueError("Full, predeclared six-month April–September set mandatory")
    complete = {}
    proofs = {}
    for symbol in MARKETS:
        complete[symbol], proofs[symbol] = verified_series(root, symbol, months)
    model = portfolio_simulation(complete)
    if (model["client_publication_authorized"] is not False or
            model["telegram_messages_sent"] != 0 or
            model["orders_submitted"] != 0):
        raise RuntimeError("Research implementation attempted production actions")

    first_ms = complete[MARKETS[0]][0].open_ms
    end_ms = complete[MARKETS[0]][-1].open_ms + 900_000
    first = datetime.fromtimestamp(first_ms / 1000, IST).date()
    end = datetime.fromtimestamp((end_ms-1) / 1000, IST).date()
    from datetime import timedelta as TD
    all_days = [
        (first + TD(days=x)).isoformat()
        for x in range((end-first).days+1)
    ]
    partitions = {
        "APR_MAY_DEVELOPMENT": ("2026-04", "2026-05"),
        "JUN_JUL_INSPECTED_RESEARCH": ("2026-06", "2026-07"),
        "AUG_SEP_EXPLORATORY_NOT_INDEPENDENT": ("2026-08", "2026-09"),
    }
    results = {}
    for label, months_group in partitions.items():
        accepted = [
            day for day in all_days if day[:7] in months_group
        ]
        choices = [
            t for t in model["modeled_references"]
            if _day(t["decision_boundary_ms"]) in set(accepted)
        ]
        results[label] = _summary(choices, accepted)
    full = _summary(model["modeled_references"], all_days)
    suggest = (
        full["hypothetical_closed_ideas"] >= 100
        and full["days_with_closed_ideas"] >= 30
        and full["mean_costed_R_per_closed_reference"] is not None
        and full["mean_costed_R_per_closed_reference"] > 0
        and full["day_cluster_bootstrap_mean_R_95pct"][0] > 0
    )
    return {
        "schema": 1,
        "status": "V7_SIX_MONTH_COSTED_RESEARCH_ONLY_NO_PRODUCTION_AUTHORIZATION",
        "policy": POLICY,
        "policy_sha256": POLICY_SHA256,
        "six_frozen_markets": list(MARKETS),
        "source_months": list(months),
        "complete_15m_bars_per_market": model["source_15m_bars_per_market"],
        "source_provenance": proofs,
        "proposals_before_portfolio_filters": model["proposals_before_portfolio_constraints"],
        "selected_paper_references": model["selected_paper_references"],
        "portfolio_suppression_reasons": model["portfolio_suppression_reasons"],
        "candidate_diagnostics_by_market": model["reasons_by_market"],
        "full_exploratory_summary": full,
        "chronological_exploratory_summaries": results,
        "retrospective_sample_meets_basic_frequency_and_edge_thresholds": suggest,
        "promotable_without_later_unseen_prospective_validation": False,
        "public_data_downloaded_by_evaluator": False,
        "live_exchange_quotes_and_fills_verified": False,
        "fee_slippage_assumptions_are_scenarios_not_observed": True,
        "same_candle_stop_and_target_resolved_stop_first": True,
        "trading_venue_quantity_or_funding_verified": False,
        "source_checksum_independent_exchange_attestation": False,
        "strategy_selected_after_14_october_observations": True,
        "historical_periods_not_out_of_sample_validation": True,
        "real_time_client_signal_publisher_implemented": False,
        "client_publication_authorized": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }


def main():
    p = argparse.ArgumentParser(description="V7 immutable no-network multi-month paper research")
    p.add_argument("--data-root", required=True)
    p.add_argument("--out", help="Optional new output path; refuses overwrite")
    args = p.parse_args()
    report = run_study(Path(args.data_root))
    encoded = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    if args.out:
        path = Path(args.out)
        if not path.is_absolute() or path.is_symlink():
            p.error("Output must be an absolute non-symlink path")
        with path.open("xb") as stream:
            stream.write(encoded)
    else:
        print(encoded.decode(), end="")


if __name__ == "__main__":
    main()
