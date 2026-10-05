"""Frozen research entry filters. Never used to change the live v1 engine."""
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN

ENTRY_POLICIES = {
    "baseline": ("EMA-PULLBACK-ATR-v1", None, None),
    "slope": ("EMA-PULLBACK-ATR-SLOPE-v1", "aligned_ema50_slope_atr", "0.05"),
    "separation": ("EMA-PULLBACK-ATR-GAP-v1", "ema_gap_atr", "0.5"),
}


def entry_filter(policy, source, previous, direction):
    if policy not in ENTRY_POLICIES:
        raise ValueError("Unknown versioned entry policy")
    if policy == "baseline":
        return {"policy": policy, "passed": True}
    source.validate()
    if previous is None:
        raise ValueError("Filter needs previous completed source")
    previous.validate()
    if direction not in ("long", "short") or source.timeframe != "1h" or previous.timeframe != "1h" or previous.bar.open_time + 3_600_000 != source.bar.open_time or previous.history_origin != source.history_origin or source.atr <= 0:
        raise ValueError("Invalid filter source alignment/direction/ATR")
    strategy, feature, minimum = ENTRY_POLICIES[policy]
    with localcontext() as context:
        context.prec, context.rounding = 34, ROUND_HALF_EVEN
        value = ((source.ema50 - previous.ema50) * (1 if direction == "long" else -1) if policy == "slope" else abs(source.ema20 - source.ema50)) / source.atr
        return {"policy": policy, "strategy": strategy, "feature": feature, "value": str(value), "minimum": minimum, "passed": value >= D(minimum)}
