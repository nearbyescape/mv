from decimal import Decimal
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from mv_strategy import Bar, IndicatorState, INTERVAL_MS, confirmation_open_time
from app.models import Candle, IndicatorCheckpoint, IndicatorSnapshot


def as_bar(row):
    return Bar(row.open_time, row.close_time, *map(Decimal, (row.open, row.high, row.low, row.close, row.volume)))


def history(session, symbol, timeframe):
    return list(session.scalars(select(Candle).where(Candle.symbol == symbol, Candle.timeframe == timeframe).order_by(Candle.open_time)))


def apply_bars(session: Session, symbol: str, timeframe: str, bars: list[Bar], server_now: int):
    from app.operations.market_lock import lock_market
    lock_market(session,symbol)
    """Caller owns transaction. Candles, snapshots and checkpoint commit atomically."""
    checkpoint = session.get(IndicatorCheckpoint, (symbol, timeframe))
    state = IndicatorState.restore(checkpoint.state_json) if checkpoint else IndicatorState(timeframe)
    rebuild = checkpoint is None
    changed = []
    seen = set()
    for bar in sorted(bars, key=lambda b: b.open_time):
        bar.validate(timeframe)
        if state.history_origin is not None and bar.open_time < state.history_origin:
            raise ValueError("Cannot prepend candles before the documented history origin")
        if bar.close_time >= server_now:
            raise ValueError("Only completed candles may be persisted")
        if bar.open_time in seen:
            raise ValueError("Duplicate candle in exchange batch")
        seen.add(bar.open_time)
        existing = session.get(Candle, (symbol, timeframe, bar.open_time))
        if existing and existing.source_hash == bar.digest():
            continue
        if state.last_open_time is not None and bar.open_time <= state.last_open_time:
            rebuild = True
        row = existing or Candle(symbol=symbol, timeframe=timeframe, open_time=bar.open_time)
        row.close_time = bar.close_time
        for key in ("open", "high", "low", "close", "volume"):
            setattr(row, key, str(getattr(bar, key)))
        row.source_hash = bar.digest()
        session.add(row)
        changed.append(bar)
    session.flush()
    if not changed and checkpoint:
        return state
    if rebuild:
        # Replay all retained source history from the original seed, never a recent-window reseed.
        state = IndicatorState(timeframe)
        changed = [as_bar(row) for row in history(session, symbol, timeframe)]
        session.execute(delete(IndicatorSnapshot).where(IndicatorSnapshot.symbol == symbol, IndicatorSnapshot.timeframe == timeframe))
    for bar in changed:
        values = state.advance(bar)
        session.add(IndicatorSnapshot(symbol=symbol, timeframe=timeframe, open_time=bar.open_time, lineage=state.lineage, **{k: str(v) if v is not None else None for k, v in values.items()}))
    session.flush()
    checkpoint = checkpoint or IndicatorCheckpoint(symbol=symbol, timeframe=timeframe)
    checkpoint.state_json = state.dump()
    session.add(checkpoint)
    return state


def repair_start(session, symbol, timeframe):
    times = list(session.scalars(select(Candle.open_time).where(Candle.symbol == symbol, Candle.timeframe == timeframe).order_by(Candle.open_time)))
    if not times:
        return None
    step = INTERVAL_MS[timeframe]
    for previous, current in zip(times, times[1:]):
        if current != previous + step:
            return previous
    return max(times[0], times[-1] - 2 * step)


def confirmation_at(session, symbol, entry_close_boundary):
    required = confirmation_open_time(entry_close_boundary)
    snapshot = session.get(IndicatorSnapshot, (symbol, "4h", required))
    return snapshot if snapshot and all(getattr(snapshot, key) is not None for key in ("ema20", "ema50", "sma200", "atr")) else None
