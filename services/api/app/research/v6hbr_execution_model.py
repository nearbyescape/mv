"""Conservative, *scenario-based* 1m futures reference execution for V6HBR.

Not historical Lighter fills, spread observations or historical funding rates.
Use only after independently audited minute data, causal strategies, and
as-of price/risk controls. OPEN_UNRESOLVED never contributes booked net R.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal as D
from typing import Iterable

from mv_strategy.strategy_v3 import TP1_ALLOCATION, TP2_ALLOCATION, TP3_ALLOCATION

MINUTE = 60_000
FUNDING_INTERVAL = 8 * 60 * MINUTE


@dataclass(frozen=True)
class ExecutionScenario:
    spread_bps: D
    slippage_bps: D
    taker_fee_bps: D
    funding_debit_bps_per_8h: D
    latency_minutes: int = 1

    def validate(self):
        values = (
            self.spread_bps, self.slippage_bps,
            self.taker_fee_bps, self.funding_debit_bps_per_8h,
        )
        if any(not isinstance(v, D) or not v.is_finite() or v < 0 or v > 1000 for v in values):
            raise ValueError("Explicit nonnegative finite cost scenario required")
        if type(self.latency_minutes) is not int or not 1 <= self.latency_minutes <= 15:
            raise ValueError("Latency must be 1..15 full minutes")


def simulate_reference_trade(plan: dict, bars: Iterable, published_at: int,
                             scenario: ExecutionScenario) -> dict:
    """Simulate a single already-approved trade independently of portfolio.

    A bar's old protective stop wins any same-minute target/stop tie.  A stop
    advance from partial TP becomes effective only on the *next* minute.
    Prices are candle-open reference prices plus explicit adverse cost scenario.
    Portfolio caps, fill feasibility, and historical exchange filters are NOT
    certified by this standalone calculation.
    """
    scenario.validate()
    if type(published_at) is not int or published_at % MINUTE:
        raise ValueError("Publication must be an exact closed-candle minute")
    direction = plan.get("direction")
    if direction not in ("long", "short"):
        raise ValueError("Unknown direction")
    sign = D(1) if direction == "long" else D(-1)
    stop = D(plan["stop"])
    levels = (D(plan["tp1"]), D(plan["tp2"]), D(plan["tp3"]))
    if any(not p.is_finite() or p <= 0 for p in (stop, *levels)):
        raise ValueError("Invalid stop/target")
    if not all(sign * (b - a) > 0 for a, b in zip((stop, *levels), levels)):
        # The stop and targets must progress monotonically in the direction of profit;
        # entry geometry is checked after the actual scenario fill.
        raise ValueError("Invalid stop/target order")
    weights = (TP1_ALLOCATION, TP2_ALLOCATION, TP3_ALLOCATION)
    if sum(weights, D(0)) != D(1):
        raise ValueError("Partial allocations do not sum to one")

    first_minute = published_at + scenario.latency_minutes * MINUTE
    ordered = iter(bars)
    last_open = None
    entry = risk = None
    entry_at = None
    remaining = D(1)
    filled = 0
    gross = fees = funding = D(0)
    exits = []
    ambiguous_count = 0
    last_close = None
    charged_funding_through = None
    favorable_050_at_ms = None
    adverse_050_at_ms = None
    impact = (scenario.spread_bps / D(2) + scenario.slippage_bps) / D(10_000)
    fee_fraction = scenario.taker_fee_bps / D(10_000)
    debit_fraction = scenario.funding_debit_bps_per_8h / D(10_000)

    def complete(status, terminal_at=None):
        return {
            "status": status,
            "entry_at_ms": entry_at,
            "terminal_at_ms": terminal_at,
            "entry_price_scenario": str(entry) if entry is not None else None,
            "risk_distance_at_fill": str(risk) if risk is not None else None,
            "remaining_fraction": str(remaining),
            "tp_count": filled,
            "gross_realized_r": str(gross),
            "fee_debit_r": str(fees),
            "funding_debit_r": str(funding),
            "net_realized_r": str(gross - fees - funding) if status in (
                "STOP", "PROTECTED_STOP", "TP3"
            ) else None,
            "open_mark_r_not_booked": (
                str(sign * (last_close - entry) / risk * remaining)
                if status == "OPEN_UNRESOLVED" and last_close is not None else None
            ),
            "intraminute_stop_first_ties": ambiguous_count,
            "favorable_050_at_ms": favorable_050_at_ms,
            "adverse_050_at_ms": adverse_050_at_ms,
            "exits": exits,
            "scenario_not_observed_fills": True,
        }

    for bar in ordered:
        t = bar.open_time
        if t < first_minute:
            continue
        if last_open is not None and t != last_open + MINUTE:
            raise ValueError("Execution minute gap or unsorted/duplicate data")
        if last_open is None and t != first_minute:
            raise ValueError("First executable full minute unavailable")
        last_open = t
        low, high, opened, last_close = (D(bar.low), D(bar.high), D(bar.open), D(bar.close))
        if low <= 0 or not low <= min(opened, last_close) <= max(opened, last_close) <= high:
            raise ValueError("Invalid reference OHLC")
        if entry is None:
            entry_at = t
            entry = opened * (D(1) + sign * impact)
            if sign * (entry - stop) <= 0 or not sign * (levels[0] - entry) > 0:
                raise ValueError("Scenario fill breaks frozen entry risk geometry")
            risk = abs(entry - stop)
            fees += fee_fraction * entry / risk
            charged_funding_through = t // FUNDING_INTERVAL
        else:
            latest_funding_mark = t // FUNDING_INTERVAL
            # Debit scenario on each UTC 8h funding boundary while position remains open.
            if latest_funding_mark > charged_funding_through:
                funding += (
                    (latest_funding_mark - charged_funding_through)
                    * debit_fraction * entry / risk * remaining
                )
                charged_funding_through = latest_funding_mark

        if sign > 0:
            favorable_r = max(high - entry, D(0)) / risk
            adverse_r = max(entry - low, D(0)) / risk
        else:
            favorable_r = max(entry - low, D(0)) / risk
            adverse_r = max(high - entry, D(0)) / risk
        # Milestones are observable only after this complete reference minute;
        # same-minute adverse/favorable ties are treated adverse-first by safety.
        if favorable_050_at_ms is None and favorable_r >= D("0.5"):
            favorable_050_at_ms = t + MINUTE
        if adverse_050_at_ms is None and adverse_r >= D("0.5"):
            adverse_050_at_ms = t + MINUTE

        effective_stop = stop if filled == 0 else entry if filled == 1 else levels[0]
        stop_hit = low <= effective_stop if sign > 0 else high >= effective_stop
        next_target = levels[filled] if filled < 3 else None
        target_hit = (
            (high >= next_target if sign > 0 else low <= next_target)
            if next_target is not None else False
        )
        if stop_hit:
            if target_hit:
                ambiguous_count += 1
            # Gap through stop may be worse than its level.
            preimpact = min(opened, effective_stop) if sign > 0 else max(opened, effective_stop)
            exit_price = preimpact * (D(1) - sign * impact)
            gross += remaining * sign * (exit_price - entry) / risk
            fees += remaining * fee_fraction * exit_price / risk
            exits.append({"at_ms": t, "type": "protective_stop", "fraction": str(remaining),
                          "price_scenario": str(exit_price)})
            remaining = D(0)
            return complete("STOP" if filled == 0 else "PROTECTED_STOP", t + MINUTE)

        while filled < 3:
            target = levels[filled]
            reached = high >= target if sign > 0 else low <= target
            if not reached:
                break
            fraction = weights[filled]
            exit_price = target * (D(1) - sign * impact)
            gross += fraction * sign * (exit_price - entry) / risk
            fees += fraction * fee_fraction * exit_price / risk
            exits.append({"at_ms": t, "type": f"tp{filled + 1}",
                          "fraction": str(fraction), "price_scenario": str(exit_price)})
            remaining -= fraction
            filled += 1
        if filled == 3:
            if remaining != 0:
                raise ValueError("Incomplete partial allocation")
            return complete("TP3", t + MINUTE)

    if entry is None:
        return complete("NO_FILL_REFERENCE")
    return complete("OPEN_UNRESOLVED")
