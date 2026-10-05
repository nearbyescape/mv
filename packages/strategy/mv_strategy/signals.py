"""Version-one signal rules and risk plans. Pure Decimal logic; no I/O or fills."""
from dataclasses import dataclass
from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN
import hashlib
import json

from .indicators import Bar, INTERVAL_MS, PRECISION, confirmation_open_time

STRATEGY_ID = "EMA-PULLBACK-ATR-v1"
RISK_ID = "RISK-ATR14-2X-2R-v1"
EXPIRY_MS = 300_000
QUOTE_AGE_MS = 5000


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def decision_id(symbol, open_time):
    return canonical_hash([STRATEGY_ID, "binance-usdm", symbol, "1h", open_time])


@dataclass(frozen=True)
class Snapshot:
    timeframe: str
    bar: Bar
    ema20: Decimal
    ema50: Decimal
    sma200: Decimal
    atr: Decimal
    count: int
    history_origin: int
    lineage: str

    def validate(self):
        self.bar.validate(self.timeframe)
        values = (self.ema20, self.ema50, self.sma200, self.atr)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values) or min(values[:3]) <= 0 or self.atr < 0:
            raise ValueError("Invalid indicator snapshot")
        if self.count != (self.bar.open_time - self.history_origin) // INTERVAL_MS[self.timeframe] + 1:
            raise ValueError("Snapshot count does not match documented origin")

    def evidence(self):
        return {"timeframe": self.timeframe, "open_time": self.bar.open_time, "close_boundary": self.bar.close_time + 1,
                "ohlcv": {k: str(getattr(self.bar, k)) for k in ("open", "high", "low", "close", "volume")},
                **{k: str(getattr(self, k)) for k in ("ema20", "ema50", "sma200", "atr")},
                "bars": self.count, "history_origin": self.history_origin, "lineage": self.lineage, "source_hash": self.bar.digest()}


@dataclass(frozen=True)
class Setup:
    outcome: str
    reason: str
    direction: str | None
    checks: list[dict]


def evaluate_setup(current: Snapshot, previous: Snapshot | None, confirmation: Snapshot | None):
    """One close-to-close reclaim/loss. Equality never creates an ordered regime."""
    current.validate()
    if current.timeframe != "1h" or current.count < 500:
        return Setup("BLOCKED_DATA", "WARMUP_1H", None, [])
    if previous is None:
        return Setup("BLOCKED_DATA", "MISSING_PREVIOUS_1H", None, [])
    previous.validate()
    if previous.timeframe != "1h" or previous.bar.open_time + INTERVAL_MS["1h"] != current.bar.open_time or previous.history_origin != current.history_origin:
        return Setup("BLOCKED_DATA", "NONCONTIGUOUS_PREVIOUS_1H", None, [])
    comparisons = {
        "long.order_1h": current.ema20 > current.ema50 > current.sma200,
        "long.previous_close": previous.bar.close <= previous.ema20,
        "long.reclaim": current.bar.close > current.ema20,
        "short.order_1h": current.ema20 < current.ema50 < current.sma200,
        "short.previous_close": previous.bar.close >= previous.ema20,
        "short.loss": current.bar.close < current.ema20,
    }
    checks = [{"id": key, "passed": value} for key, value in comparisons.items()]
    long = all(comparisons[k] for k in ("long.order_1h", "long.previous_close", "long.reclaim"))
    short = all(comparisons[k] for k in ("short.order_1h", "short.previous_close", "short.loss"))
    if not long and not short:
        return Setup("NO_SETUP", "NO_FRESH_RECLAIM_OR_LOSS", None, checks)
    direction = "long" if long else "short"
    if current.atr <= 0:
        return Setup("BLOCKED_DATA", "NONPOSITIVE_ATR", direction, checks)
    required = confirmation_open_time(current.bar.close_time + 1)
    if confirmation is None or confirmation.timeframe != "4h" or confirmation.bar.open_time != required:
        return Setup("BLOCKED_DATA", "WAITING_EXPECTED_4H", direction, checks)
    confirmation.validate()
    if confirmation.count < 500:
        return Setup("BLOCKED_DATA", "WARMUP_4H", direction, checks)
    order = confirmation.ema20 > confirmation.ema50 > confirmation.sma200 if long else confirmation.ema20 < confirmation.ema50 < confirmation.sma200
    close = confirmation.bar.close > confirmation.ema20 if long else confirmation.bar.close < confirmation.ema20
    checks += [{"id": direction + ".order_4h", "passed": order}, {"id": direction + ".close_4h", "passed": close}, {"id": "positive_atr", "passed": True}]
    if not order or not close:
        return Setup("NO_SETUP", "4H_CONFIRMATION_FAILED", direction, checks)
    return Setup("LONG_SETUP" if long else "SHORT_SETUP", "RULES_PASSED", direction, checks)


class PlanRejected(ValueError):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal
    ask: Decimal
    bid_qty: Decimal
    ask_qty: Decimal
    time: int
    received_at: int  # Local receipt converted to the synchronized exchange clock.

    def evidence(self):
        return {"symbol": self.symbol, **{k: str(getattr(self, k)) for k in ("bid", "ask", "bid_qty", "ask_qty")}, "time": self.time, "received_at": self.received_at, "source": "binance-usdm-bookTicker"}


@dataclass(frozen=True)
class PriceFilter:
    tick: Decimal
    minimum: Decimal
    maximum: Decimal

    def validate(self):
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in (self.tick, self.minimum, self.maximum)) or self.tick <= 0 or min(self.minimum, self.maximum) < 0 or self.maximum and self.minimum > self.maximum:
            raise PlanRejected("INVALID_PRICE_FILTER")

    def allows(self, value):
        return value > 0 and (not self.minimum or value >= self.minimum) and (not self.maximum or value <= self.maximum) and (value - self.minimum) % self.tick == 0

    def round(self, value, upwards):
        units = ((value - self.minimum) / self.tick).to_integral_value(rounding=ROUND_CEILING if upwards else ROUND_FLOOR)
        return self.minimum + units * self.tick


def build_plan(symbol, direction, source: Snapshot, quote: Quote, price_filter: PriceFilter, now: int):
    source.validate()
    if direction not in ("long", "short") or source.timeframe != "1h":
        raise PlanRejected("INVALID_DIRECTION_OR_SOURCE")
    boundary = source.bar.close_time + 1
    if now < boundary:
        raise PlanRejected("SOURCE_NOT_CLOSED")
    if now >= boundary + EXPIRY_MS:
        raise PlanRejected("EXPIRED_ENTRY_WINDOW")
    if quote.symbol != symbol:
        raise PlanRejected("QUOTE_SYMBOL_MISMATCH")
    values = (quote.bid, quote.ask, quote.bid_qty, quote.ask_qty)
    if any(not isinstance(v, Decimal) or not v.is_finite() or v <= 0 for v in values) or quote.bid > quote.ask:
        raise PlanRejected("INVALID_QUOTE", True)
    if any(type(v) is not int for v in (quote.time, quote.received_at, now)) or not boundary <= quote.time <= quote.received_at <= now or now - quote.time > QUOTE_AGE_MS or now - quote.received_at > QUOTE_AGE_MS:
        raise PlanRejected("STALE_OR_FUTURE_QUOTE", True)
    with localcontext() as ctx:
        ctx.prec, ctx.rounding = PRECISION, ROUND_HALF_EVEN
        price_filter.validate()
        if not price_filter.allows(quote.bid) or not price_filter.allows(quote.ask):
            raise PlanRejected("QUOTE_OFF_TICK_OR_BOUNDS")
        entry = quote.ask if direction == "long" else quote.bid
        atr = source.atr
        if atr <= 0:
            raise PlanRejected("NONPOSITIVE_ATR")
        drift = abs(entry - source.bar.close)
        if drift > Decimal("0.5") * atr:
            raise PlanRejected("MISSED_ENTRY_PRICE_DRIFT")
        if (direction == "long" and entry <= source.ema20) or (direction == "short" and entry >= source.ema20):
            raise PlanRejected("ENTRY_LOST_EMA20_SIDE")
        upwards = direction == "short"
        stop = price_filter.round(entry + (Decimal(2) * atr if upwards else -Decimal(2) * atr), upwards)
        risk = abs(entry - stop)
        target = price_filter.round(entry + (-Decimal(2) * risk if upwards else Decimal(2) * risk), upwards)
        geometry = stop < entry < target if direction == "long" else target < entry < stop
        if risk <= 0 or not geometry or not all(price_filter.allows(p) for p in (entry, stop, target)):
            raise PlanRejected("INVALID_RISK_GEOMETRY_OR_BOUNDS")
        reward = abs(target - entry)
        return {"strategy": STRATEGY_ID, "risk_policy": RISK_ID, "symbol": symbol, "direction": direction,
                **{k: str(v) for k, v in {"entry": entry, "stop": stop, "target": target, "frozen_atr": atr, "risk_distance": risk, "reward_distance": reward, "reward_risk": reward / risk, "entry_drift": drift, "spread": quote.ask - quote.bid, "tick_size": price_filter.tick}.items()},
                "source_open_time": source.bar.open_time, "source_close_boundary": boundary, "published_at": now, "expires_at": boundary + EXPIRY_MS,
                "quote_time": quote.time, "quote_received_at": quote.received_at, "entry_side": "ask" if direction == "long" else "bid", "execution": "signal-reference-only"}
