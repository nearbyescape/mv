"""BTC April-May V6HBR *proxy* trading-performance pilot, offline only.

This computes H/B/R portfolio counterfactuals from the source-audited BTC
candidate stream with existing V4 and V5 plan builders, plus explicit research
cost scenarios. A synthetic zero-spread reference quote and operator-assumed
price tick CANNOT validate live/as-of orderbook quality, historical fees,
funding, liquidity, Lighter fills, or real-margin exposure. No holdout access.
"""
from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace
import json

from mv_strategy.signals import PriceFilter, Quote, PlanRejected
from mv_strategy.strategy_v4 import evaluate_setup_v4, build_plan_v4
from mv_strategy.strategy_v5 import evaluate_context_v5, evaluate_trigger_v5
from mv_strategy.indicators import confirmation_open_time

from .dataset import timestamp
from .v5_archive_batch import batch_plan
from .v5_archive_audit import audited_bars, audit_minute_pair
from .v5_archives import load_spec, valid_research_root
from .v5_decision_replay import HOUR, MIN15, _structures, snapshots_from_pinned
from .v5_compare import _v5_reference_plan, balanced_15m_filter_reason
from .v4_retrospective import btc_timing_reason
from .v6hbr_candidate_export import export_events
from .v6hbr_execution_model import ExecutionScenario, simulate_reference_trade, MINUTE
from .v6hbr_portfolio_replay import simulate_cohort
from .v6hbr_attribution import diagnose

SYMBOL = "BTCUSDT"
DEVELOPMENT_START = "2026-04-01"
DEVELOPMENT_END = "2026-06-01"


def _check_value(checks: list[dict], suffix: str) -> D:
    for row in checks:
        if str(row.get("id", "")).endswith("." + suffix) and "value" in row:
            return D(row["value"])
    raise ValueError("Missing inherited strategy ranking key: " + suffix)


def _source_context(maps: dict, row: dict):
    opened = row["context_open_ms"]
    current = maps["1h"].get(opened)
    previous = maps["1h"].get(opened - HOUR)
    four = maps["4h"].get(confirmation_open_time(row["at_ms"] if row["lane"] == "v4_base"
                                                  else opened + HOUR))
    structure = _structures(maps["1h"], opened, HOUR)
    if current is None or current.bar.close_time + 1 != opened + HOUR:
        raise ValueError("Missing/uncausally timed 1h source snapshot")
    return current, previous, four, structure


def price_candidates(events, maps, minute_bars, scenario: ExecutionScenario,
                     assumed_tick: D):
    """Price every reference independently; never preselect hindsight winners."""
    price_filter = PriceFilter(assumed_tick, D(0), D(0))
    price_filter.validate()
    minutes = {b.open_time: i for i, b in enumerate(minute_bars)}
    btc_states = {
        t: {"bar": s.bar, "count": s.count, "ema20": s.ema20, "ema50": s.ema50}
        for t, s in maps["15m"].items()
    }
    ranked = []
    for i, ev in enumerate(events):
        at = ev["at_ms"]
        current, previous, four, structure = _source_context(maps, ev)
        preliminary = btc_timing_reason(btc_states, at, ev["direction"])
        plan = None
        setup = None
        rank_run = rank_extension = None
        if ev["lane"] == "v4_base":
            setup = evaluate_setup_v4(current, previous, four, structure)
            if (
                setup.outcome not in ("LONG_SETUP", "SHORT_SETUP")
                or setup.direction != ev["direction"]
                or setup.setup_type != ev["setup_type"]
                or setup.regime != ev["regime"]
            ):
                raise ValueError("V4 event no longer matches inherited strategy")
            rank_run = _check_value(setup.checks, "recent_run_atr")
            rank_extension = _check_value(setup.checks, "source_extension_atr")
            trigger = None
            context = None
            trigger_snapshot = None
        else:
            v4 = evaluate_setup_v4(current, previous, four, structure)
            if v4.reason != "NO_PULLBACK_OR_BREAKOUT_TRIGGER":
                raise ValueError("Rescue no longer follows V4 no-trigger decision")
            context = evaluate_context_v5(current, previous, four, structure)
            if context.outcome != "ARMED" or context.direction != ev["direction"]:
                raise ValueError("Rescue context no longer armed")
            trigger_open = ev["trigger_open_ms"]
            trigger_snapshot = maps["15m"].get(trigger_open)
            trigger = evaluate_trigger_v5(
                context.direction, trigger_snapshot,
                maps["15m"].get(trigger_open - MIN15),
                _structures(maps["15m"], trigger_open, MIN15),
            )
            if (
                trigger.outcome != "TRIGGER"
                or trigger.trigger_type != ev["setup_type"]
                or trigger_snapshot.bar.close_time + 1 != at
            ):
                raise ValueError("Rescue trigger no longer matches inherited strategy")
            rank_run, rank_extension = trigger.recent_run_atr, trigger.source_extension_atr

        entry_t = at + scenario.latency_minutes * MINUTE
        entry_index = minutes.get(entry_t)
        if entry_index is None:
            preliminary = preliminary or "REFERENCE_ENTRY_UNAVAILABLE"
        if preliminary is None:
            opening = D(minute_bars[entry_index].open)
            if not price_filter.allows(opening):
                preliminary = "ASSUMED_TICK_FILTER_REJECTED"
            else:
                try:
                    if ev["lane"] == "v4_base":
                        quote = Quote(SYMBOL, opening, opening, D(1), D(1),
                                      entry_t, entry_t)
                        plan = build_plan_v4(
                            SYMBOL, setup, current, quote, price_filter, entry_t
                        )
                    else:
                        plan = _v5_reference_plan(
                            SYMBOL, context, trigger, current, trigger_snapshot,
                            opening, price_filter, at,
                        )
                except PlanRejected as exc:
                    preliminary = exc.code

        balanced_reason = balanced_15m_filter_reason(
            SimpleNamespace(
                symbol=SYMBOL, regime=ev["regime"], direction=ev["direction"],
                published_at=at, preliminary_reason=preliminary,
            ),
            {SYMBOL: maps["15m"]},
        )
        outcome = (
            simulate_reference_trade(
                plan, minute_bars[entry_index:], at, scenario
            )
            if plan is not None and entry_index is not None else None
        )
        ranked.append({
            "id": f"{SYMBOL}:{ev['context_open_ms']}:{ev['lane']}:{ev.get('trigger_open_ms', '-')}",
            "symbol": SYMBOL,
            "direction": ev["direction"],
            "lane": ev["lane"],
            "regime": ev["regime"],
            "at_ms": at,
            "context_open_ms": ev["context_open_ms"],
            "recent_run_atr": str(rank_run),
            "source_extension_atr": str(rank_extension),
            "preliminary_reason": preliminary,
            "balanced_reason": balanced_reason,
            "balanced_confirmed": (
                ev["regime"] == "established" or balanced_reason is None
            ),
            "outcome": outcome,
            "entry_reference": plan["entry"] if plan else None,
            "plan_strategy": plan["strategy"] if plan else None,
        })
    return ranked


def run_development_proxy(root: Path, *, scenario: ExecutionScenario,
                          assumed_tick: D, risk_unit: D,
                          max_aggregate_risk: D):
    scenario.validate()
    assumed_tick = D(str(assumed_tick))
    if scenario.spread_bps > D(10):
        raise ValueError("Assumed spread exceeds frozen V4 10bps acceptance guard")
    if assumed_tick <= 0:
        raise ValueError("Explicit positive assumed price tick required")
    spec, spec_sha = load_spec()
    maps, source_hashes = {}, {}
    for frame in ("15m", "1h", "4h"):
        plans = batch_plan(spec, SYMBOL, frame, "2026-01", "2026-05")
        maps[frame], source = snapshots_from_pinned(root, plans, spec_sha)
        source_hashes[frame] = source["canonical_series_sha256"]
    events = export_events(
        maps, SYMBOL, timestamp(DEVELOPMENT_START), timestamp(DEVELOPMENT_END)
    )
    minute_plans = batch_plan(spec, SYMBOL, "1m", "2026-04", "2026-05")
    quarter_plans = batch_plan(spec, SYMBOL, "15m", "2026-04", "2026-05")
    parity = audit_minute_pair(root, minute_plans, quarter_plans, spec_sha)
    if parity["disposition"] != "PASS":
        raise ValueError("BTC 1m/15m independent integrity check failed")
    minute_bars = list(audited_bars(root, minute_plans, spec_sha))
    if len(minute_bars) != 87_840:
        raise ValueError("Unexpected audited April-May minute count")
    priced = price_candidates(events["events"], maps, minute_bars,
                              scenario, assumed_tick)
    cohorts = {}
    for name in ("V4", "H", "B", "R"):
        full = simulate_cohort(
            priced, name, risk_unit=risk_unit,
            max_aggregate_risk=max_aggregate_risk,
        )
        cohorts[name] = {
            key: value for key, value in full.items() if key != "audit"
        }
        cohorts[name]["audit"] = full["audit"]
    baseline = set(cohorts["V4"]["accepted_ids"])
    for name in ("H", "B", "R"):
        kept = set(cohorts[name]["accepted_ids"])
        # Backward-compatible legacy key: 'missing' does NOT itself prove rescue crowd-out.
        cohorts[name]["v4_base_ids_displaced"] = sorted(baseline - kept)
    attribution = diagnose(priced, cohorts)
    return {
        "schema": 1,
        "status": "BTC_ONLY_EXPLICIT_COST_SCENARIO_NOT_CERTIFIED",
        "production_mutation": False,
        "performance_window": "2026-04-01..2026-05-31, development only",
        "data_spec_sha256": spec_sha,
        "source_series_sha256": {
            **source_hashes, "1m": parity["minute"]["canonical_series_sha256"],
        },
        "event_stream_sha256": events["export_stream_sha256"],
        "candidate_count": len(priced),
        "post_hoc_attribution": attribution,
        "pricing_preliminary_reasons": dict(sorted(Counter(
            x["preliminary_reason"] or "ELIGIBLE" for x in priced
        ).items())),
        "assumptions": {
            "assumed_tick": str(assumed_tick),
            "spread_bps": str(scenario.spread_bps),
            "slippage_bps": str(scenario.slippage_bps),
            "taker_fee_bps": str(scenario.taker_fee_bps),
            "funding_debit_bps_per_8h": str(scenario.funding_debit_bps_per_8h),
            "latency_minutes": scenario.latency_minutes,
            "risk_unit": str(risk_unit),
            "max_aggregate_risk": str(max_aggregate_risk),
        },
        "cohorts": cohorts,
        "limitations": [
            "Not as-of historical Binance/Lighter book, exchangeInfo or actual funding",
            "Synthetic zero-spread reference quote with scenario spread cost, not valid quote evidence",
            "Fill risk geometry anchored to synthetic reference entry; actual drift may differ",
            "No 30-market correlation/margin certification or live-signal parity",
            "May cutoff censors unresolved positions; no June/holdout outcomes consumed",
            "No future selection by net R; outputs cannot justify V6HBR promotion",
            "Legacy v4_base_ids_displaced means baseline accepted but missing in cohort; post_hoc_attribution distinguishes filter veto from proven rescue blocker",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="BTC Apr-May V6HBR cost-scenario proxy, never orders")
    parser.add_argument("--root", required=True)
    parser.add_argument("--assumed-tick", required=True)
    parser.add_argument("--spread-bps", required=True)
    parser.add_argument("--slippage-bps", required=True)
    parser.add_argument("--taker-fee-bps", required=True)
    parser.add_argument("--funding-debit-bps-per-8h", required=True)
    parser.add_argument("--latency-minutes", type=int, default=1)
    parser.add_argument("--risk-unit", required=True)
    parser.add_argument("--max-aggregate-risk", required=True)
    parser.add_argument("--acknowledge-proxy-not-fills", action="store_true")
    args = parser.parse_args()
    if not args.acknowledge_proxy_not_fills:
        parser.error("Explicit --acknowledge-proxy-not-fills is required")
    scenario = ExecutionScenario(
        D(args.spread_bps), D(args.slippage_bps), D(args.taker_fee_bps),
        D(args.funding_debit_bps_per_8h), args.latency_minutes,
    )
    report = run_development_proxy(
        valid_research_root(args.root),
        scenario=scenario,
        assumed_tick=D(args.assumed_tick),
        risk_unit=D(args.risk_unit),
        max_aggregate_risk=D(args.max_aggregate_risk),
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
