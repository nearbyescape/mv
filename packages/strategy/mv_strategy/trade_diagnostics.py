"""Entry-time features and descriptive cohorts; never selects or originates a signal."""
from collections import defaultdict
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN

from .indicators import PRECISION

DIMENSIONS = ("symbol", "direction", "exit_reason", "atr_fraction", "ema_gap_atr", "aligned_ema50_slope_atr")


def number(value):
    if not isinstance(value, str):
        raise ValueError("Diagnostic financial values must be exact strings")
    result = D(value)
    if not result.is_finite():
        raise ValueError("Nonfinite diagnostic value")
    return result


def edges(spec, key):
    values = [number(value) for value in spec[key + "_edges"]]
    if not values or any(value < 0 for value in values) or any(b <= a for a, b in zip(values, values[1:])):
        raise ValueError("Invalid registered diagnostic thresholds")
    return values


def bucket(value, thresholds):
    # Half-open cohorts: equality belongs to the higher bucket.
    for index, edge in enumerate(thresholds):
        if value < edge:
            return str(index)
    return str(len(thresholds))


def features(trade, spec):
    source, previous = (trade["evidence"][key] for key in ("source", "previous"))
    if source["open_time"] + 3_600_000 != trade["source_close"] or previous["open_time"] + 3_600_000 != source["open_time"]:
        raise ValueError("Diagnostic source is not the completed entry evidence")
    atr, close = number(source["atr"]), number(source["ohlcv"]["close"])
    if atr <= 0 or close <= 0 or trade["direction"] not in ("long", "short"):
        raise ValueError("Invalid diagnostic entry data")
    sign = 1 if trade["direction"] == "long" else -1
    return {"atr_fraction": atr / close,
            "ema_gap_atr": abs(number(source["ema20"]) - number(source["ema50"])) / atr,
            "aligned_ema50_slope_atr": sign * (number(source["ema50"]) - number(previous["ema50"])) / atr}


def summarize(trades):
    sums = {key: sum((number(trade[key]) for trade in trades), D(0)) for key in ("net_pnl", "gross_pnl", "fees", "funding_pnl", "net_r")}
    count = len(trades)
    wins = sum(number(trade["net_pnl"]) > 0 for trade in trades)
    positive = sum((max(number(t["net_pnl"]), D(0)) for t in trades), D(0))
    negative = sum((min(number(t["net_pnl"]), D(0)) for t in trades), D(0))
    excursions = []
    for trade in trades:
        quantity, risk = number(trade["quantity"]), number(trade["initial_risk_usdt"])
        if quantity <= 0 or risk <= 0:
            raise ValueError("Invalid diagnostic quantity/risk")
        mae, mfe = number(trade["mae_observed"]), number(trade["mfe_observed"])
        if min(mae, mfe) < 0:
            raise ValueError("Invalid diagnostic excursions")
        excursions.append((mae * quantity / risk, mfe * quantity / risk))
    return {"trades": count, **{key: str(value) for key, value in sums.items() if key != "net_r"},
            "win_rate": str(D(wins) / count) if count else None,
            "expectancy_r": str(sums["net_r"] / count) if count else None,
            "expectancy_usdt": str(sums["net_pnl"] / count) if count else None,
            "profit_factor": str(positive / -negative) if negative else None,
            "average_mae_r_observed": str(sum((e[0] for e in excursions), D(0)) / count) if count else None,
            "average_mfe_r_observed": str(sum((e[1] for e in excursions), D(0)) / count) if count else None,
            "observed_at_least_1r": sum(e[1] >= 1 for e in excursions),
            "losers_observed_at_least_1r": sum(e[1] >= 1 and number(t["net_pnl"]) < 0 for e, t in zip(excursions, trades))}


def diagnose(trades, spec):
    with localcontext() as context:
        context.prec, context.rounding = PRECISION, ROUND_HALF_EVEN
        thresholds = {key: edges(spec, key) for key in DIMENSIONS[3:]}
        members = {key: defaultdict(list) for key in DIMENSIONS}
        for trade in trades:
            values = features(trade, spec)
            for key in DIMENSIONS:
                cohort = bucket(values[key], thresholds[key]) if key in values else trade[key]
                members[key][cohort].append(trade)
        return {"summary": summarize(trades), "dimensions": {
            key: [{"cohort": cohort, **summarize(rows)} for cohort, rows in sorted(groups.items())]
            for key, groups in members.items()}}
