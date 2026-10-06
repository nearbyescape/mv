"""Pure financial arithmetic. No I/O, floats, display rounding or demo imports."""
from dataclasses import dataclass, field
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json

INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
PRECISION = 34
STATE_VERSION = 1


@dataclass(frozen=True)
class Bar:
    open_time: int
    close_time: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def validate(self, timeframe: str):
        step = INTERVAL_MS[timeframe]
        if self.open_time < 0 or self.open_time % step or self.close_time != self.open_time + step - 1:
            raise ValueError("Invalid candle boundaries")
        values = (self.open, self.high, self.low, self.close, self.volume)
        if any(not isinstance(v, Decimal) or not v.is_finite() for v in values):
            raise ValueError("Candle values must be finite Decimals")
        if min(values[:4]) <= 0 or self.volume < 0 or not self.low <= min(self.open, self.close) <= max(self.open, self.close) <= self.high:
            raise ValueError("Invalid OHLC or volume")

    def digest(self):
        # Exact source strings are retained; a change to the supplied final bar is auditable.
        return hashlib.sha256(json.dumps([self.open_time, self.close_time, *map(str, (self.open, self.high, self.low, self.close, self.volume))], separators=(",", ":")).encode()).hexdigest()


@dataclass
class IndicatorState:
    timeframe: str
    history_origin: int | None = None
    last_open_time: int | None = None
    count: int = 0
    previous_close: Decimal | None = None
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    atr: Decimal | None = None
    seed_closes: list[Decimal] = field(default_factory=list)
    close_window: list[Decimal] = field(default_factory=list)
    tr_seed: list[Decimal] = field(default_factory=list)
    lineage: str = ""

    def advance(self, bar: Bar) -> dict[str, Decimal | None]:
        bar.validate(self.timeframe)
        if self.last_open_time is not None and bar.open_time != self.last_open_time + INTERVAL_MS[self.timeframe]:
            raise ValueError("Non-contiguous or duplicate candle; repair/replay required")
        with localcontext() as ctx:
            ctx.prec = PRECISION
            ctx.rounding = ROUND_HALF_EVEN
            if self.count < 50:
                self.seed_closes.append(bar.close)
            for period, attribute in ((20, "ema20"), (50, "ema50")):
                previous = getattr(self, attribute)
                if self.count == period - 1:
                    setattr(self, attribute, sum(self.seed_closes[:period], Decimal(0)) / Decimal(period))
                elif self.count >= period:
                    alpha = Decimal(2) / Decimal(period + 1)
                    setattr(self, attribute, alpha * bar.close + (Decimal(1) - alpha) * previous)
            if self.previous_close is not None:
                tr = max(bar.high - bar.low, abs(bar.high - self.previous_close), abs(bar.low - self.previous_close))
                if self.count <= 14:
                    self.tr_seed.append(tr)
                if self.count == 14:
                    self.atr = sum(self.tr_seed, Decimal(0)) / Decimal(14)
                elif self.count > 14:
                    self.atr = (Decimal(13) * self.atr + tr) / Decimal(14)
            self.close_window.append(bar.close)
            self.close_window = self.close_window[-200:]
            sma = sum(self.close_window, Decimal(0)) / Decimal(200) if len(self.close_window) == 200 else None
            if self.history_origin is None:
                self.history_origin = bar.open_time
            self.count += 1
            self.last_open_time = bar.open_time
            self.previous_close = bar.close
            self.lineage = hashlib.sha256((self.lineage + bar.digest()).encode()).hexdigest()
            if self.count >= 50:
                self.seed_closes = []
            if self.count >= 15:
                self.tr_seed = []
            return {"ema20": self.ema20, "ema50": self.ema50, "sma200": sma, "atr": self.atr}

    def dump(self):
        result = {"version": STATE_VERSION, "precision": PRECISION, "timeframe": self.timeframe, "history_origin": self.history_origin, "last_open_time": self.last_open_time, "count": self.count, "lineage": self.lineage}
        for key in ("previous_close", "ema20", "ema50", "atr"):
            value = getattr(self, key)
            result[key] = str(value) if value is not None else None
        for key in ("seed_closes", "close_window", "tr_seed"):
            result[key] = list(map(str, getattr(self, key)))
        return result

    @classmethod
    def restore(cls, data):
        if data.get("version") != STATE_VERSION or data.get("precision") != PRECISION or data.get("timeframe") not in INTERVAL_MS:
            raise ValueError("Incompatible indicator checkpoint")
        state = cls(data["timeframe"])
        for key in ("history_origin", "last_open_time", "count", "lineage"):
            setattr(state, key, data[key])
        for key in ("previous_close", "ema20", "ema50", "atr"):
            setattr(state, key, Decimal(data[key]) if data[key] is not None else None)
        for key in ("seed_closes", "close_window", "tr_seed"):
            setattr(state, key, list(map(Decimal, data[key])))
        if state.count < 0 or len(state.close_window) != min(state.count, 200):
            raise ValueError("Malformed indicator checkpoint")
        return state


def confirmation_open_time(entry_close_boundary_ms: int) -> int:
    """Required completed 4H bar at the 1H boundary. Never choose by event arrival order."""
    if entry_close_boundary_ms % INTERVAL_MS["1h"]:
        raise ValueError("Entry boundary must be aligned to 1H")
    step = INTERVAL_MS["4h"]
    return entry_close_boundary_ms // step * step - step
