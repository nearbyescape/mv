"""Decimal portfolio accounting and deterministic calendar-block uncertainty estimates."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import random

from .indicators import PRECISION

D = Decimal


def month(time):
    return datetime.fromtimestamp(time / 1000, timezone.utc).strftime("%Y-%m")


def bootstrap(values, seed=20261004, replications=2000, block=3):
    if len(values) < 6:
        return {"lower": None, "upper": None, "months": len(values), "method": "insufficient calendar months"}
    generator = random.Random(seed)
    means = []
    for _ in range(replications):
        draw = []
        while len(draw) < len(values):
            start = generator.randrange(len(values) - block + 1)
            draw.extend(values[start:start + block])
        means.append(sum(draw[:len(values)], D(0)) / len(values))
    means.sort()
    return {"lower": str(means[int(replications * .025)]), "upper": str(means[int(replications * .975) - 1]),
            "months": len(values), "replications": replications, "block_months": block,
            "method": "moving-block bootstrap of monthly portfolio returns; small samples, no guaranteed coverage"}


def aggregate(results, start, end):
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = PRECISION, ROUND_HALF_EVEN
        trades = sorted([trade for result in results for trade in result["trades"]], key=lambda t: (t["exit_time"], t["symbol"], t["signal_id"]))
        initial = sum((D(row["initial_capital"]) for row in results), D(0))
        ending = sum((D(row["ending_equity"]) for row in results), D(0))
        curves = [{point["time"]: point for point in result["curve"]} for result in results]
        if any(set(curve) != set(curves[0]) for curve in curves[1:]):
            raise ValueError("Portfolio curves are not synchronized")
        curve = [{"time": time, "equity": str(sum((D(c[time]["equity"]) for c in curves), D(0))),
                  "exposure": str(sum((D(c[time]["exposure"]) for c in curves), D(0)))} for time in sorted(curves[0])]
        peak, max_drawdown, peak_time, underwater = initial, D(0), start, 0
        max_exposure = D(0)
        for point in curve:
            value = D(point["equity"])
            if value >= peak:
                peak, peak_time = value, point["time"]
            else:
                max_drawdown = max(max_drawdown, (peak - value) / peak)
                underwater = max(underwater, point["time"] - peak_time)
            if value > 0:
                max_exposure = max(max_exposure, D(point["exposure"]) / value)
        pnl = [D(t["net_pnl"]) for t in trades]
        wins, losses = [v for v in pnl if v > 0], [v for v in pnl if v < 0]
        sums = {key: sum((D(t[key]) for t in trades), D(0)) for key in ("net_pnl", "gross_pnl", "fees", "funding_pnl", "entry_notional", "exit_notional")}
        if ending - initial != sums["net_pnl"]:
            # Each financial step is rounded at precision 34; only accumulated
            # rounding noise is permitted, never an accounting discrepancy.
            if abs(ending - initial - sums["net_pnl"]) > D("1e-25") * max(initial, D(1)):
                raise ValueError("Trade ledger does not reconcile to cash equity")
        monthly = []
        month_start_equity = initial
        for index, point in enumerate(curve[1:], 1):
            if point["time"] == end or month(point["time"]) != month(point["time"] - 1):
                value = D(point["equity"])
                monthly.append({"month": month(point["time"] - 1), "return": str((value - month_start_equity) / month_start_equity) if month_start_equity > 0 else None,
                                "ending_equity": str(value)})
                month_start_equity = value
        split = {}
        for direction in ("long", "short"):
            selected = [t for t in trades if t["direction"] == direction]
            split[direction] = {"trades": len(selected), "net_pnl": str(sum((D(t["net_pnl"]) for t in selected), D(0)))}
        blocked = Counter()
        for result in results:
            blocked.update(result["blocked"])
        metrics = {"initial_capital": str(initial), "ending_equity": str(ending), "net_pnl": str(ending - initial),
                   "return": str((ending - initial) / initial), "gross_pnl": str(sums["gross_pnl"]), "fees": str(sums["fees"]),
                   "funding_pnl": str(sums["funding_pnl"]), "trades": len(trades), "win_rate": str(D(len(wins)) / len(trades)) if trades else None,
                   "expectancy_usdt": str(sum(pnl, D(0)) / len(pnl)) if pnl else None,
                   "expectancy_r": str(sum((D(t["net_r"]) for t in trades), D(0)) / len(trades)) if trades else None,
                   "average_win": str(sum(wins, D(0)) / len(wins)) if wins else None, "average_loss": str(sum(losses, D(0)) / len(losses)) if losses else None,
                   "profit_factor": str(sum(wins, D(0)) / -sum(losses, D(0))) if losses else None,
                   "max_drawdown": str(max_drawdown), "max_time_underwater_hours": str(D(underwater) / 3_600_000),
                   "turnover": str((sums["entry_notional"] + sums["exit_notional"]) / initial), "max_exposure_to_equity": str(max_exposure),
                   "time_exposure": str(D(sum(r["held_minutes"] for r in results)) / ((end - start) // 60_000 * len(results))),
                   "average_holding_hours": str(sum((D(t["exit_time"] - t["entry_time"]) / 3_600_000 for t in trades), D(0)) / len(trades)) if trades else None,
                   "ambiguous_stop_first": sum(t["ambiguous_stop_first"] for t in trades), "gap_stop_exits": sum(t["exit_reason"] == "stop_gap" for t in trades),
                   "forced_partition_exits": sum(t["exit_reason"] == "partition_end" for t in trades),
                   "exit_reasons": dict(Counter(t["exit_reason"] for t in trades)), "directions": split, "blocked": dict(blocked)}
        passive = sum((D(r["passive_ending_equity"]) for r in results), D(0))
        return {"metrics": metrics, "curve": curve, "monthly": monthly,
                "uncertainty": bootstrap([D(m["return"]) for m in monthly if m["return"] is not None]),
                "benchmarks": {"cash_return": "0", "passive_long_return": str((passive - initial) / initial),
                               "passive_fees": str(sum((D(r["passive_fees"]) for r in results), D(0))),
                               "passive_funding_pnl": str(sum((D(r["passive_funding_pnl"]) for r in results), D(0)))},
                "trades": trades}
