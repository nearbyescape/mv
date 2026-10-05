"""Explicit JSON codec; no pickle or arbitrary class loading."""
from collections import Counter
from dataclasses import fields, is_dataclass
from decimal import Decimal
from mv_strategy.indicators import Bar
from mv_strategy.signals import Snapshot, Setup, PriceFilter
from mv_strategy.backtest import Costs, Funding, Replay

RECORDS = {cls.__name__: cls for cls in (Bar, Snapshot, Setup, PriceFilter, Costs, Funding)}


def encode(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Nonfinite paper state")
        return {"$decimal": str(value)}
    if is_dataclass(value):
        return {"$record": type(value).__name__, "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)}}
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [encode(v) for v in value]
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("Unsupported paper state value")


def decode(value):
    if isinstance(value, dict):
        if "$decimal" in value:
            result = Decimal(value["$decimal"])
            if set(value) != {"$decimal"} or not result.is_finite():
                raise ValueError("Invalid paper decimal")
            return result
        if "$record" in value:
            cls = RECORDS.get(value["$record"])
            if cls is None or set(value) != {"$record", "fields"} or set(value["fields"]) != {f.name for f in fields(cls)}:
                raise ValueError("Invalid paper record")
            return cls(**{k: decode(v) for k, v in value["fields"].items()})
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def dump(engine):
    return encode({k: v for k, v in vars(engine).items() if k != "snapshots"})


def restore(payload):
    values = decode(payload)
    engine = Replay(values["symbol"], {"1h": {}, "4h": {}}, [], values["filter"], values["costs"],
                    values["start"] // 3_600_000 * 3_600_000, values["end"], values["initial"], values["exit_policy"], values["entry_policy"])
    vars(engine).update(values)
    engine.blocked = Counter(engine.blocked)
    return engine
