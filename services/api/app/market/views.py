from decimal import Decimal
from sqlalchemy import select
from mv_strategy import INTERVAL_MS
from app.models import Candle, CollectorStatus, IndicatorCheckpoint, IndicatorSnapshot, MarketContract, WatchlistItem
from .binance import now_ms


def collector_health(session):
    row = session.get(CollectorStatus, "collector")
    now = now_ms()
    if row is None:
        return {"state": "not-running", "live": False, "last_event_at": None, "error": None, "clock_offset_ms": 0}
    heartbeat_age = now - row.updated_at
    event_age = now - row.last_event_at if row.last_event_at is not None else None
    live = row.state == "streaming" and 0 <= heartbeat_age <= 30_000 and event_age is not None and 0 <= event_age <= 30_000 and abs(row.clock_offset_ms) <= 5000
    state = row.state if 0 <= heartbeat_age <= 30_000 else "stale"
    if abs(row.clock_offset_ms) > 5000:
        state = "clock-skew"
    return {"state": state, "live": live, "last_event_at": row.last_event_at, "error": row.error, "clock_offset_ms": row.clock_offset_ms, "reconnects": row.reconnects}


def market_view(session, symbol, timeframe, limit=120):
    from app.signals.service import engine_health
    contract = session.get(MarketContract, symbol)
    checkpoint = session.get(IndicatorCheckpoint, (symbol, timeframe))
    status = collector_health(session)
    state = checkpoint.state_json if checkpoint else None
    paired_timeframe = "4h" if timeframe == "1h" else "1h"
    paired_checkpoint = session.get(IndicatorCheckpoint, (symbol, paired_timeframe))
    paired_state = paired_checkpoint.state_json if paired_checkpoint else None
    query = select(Candle, IndicatorSnapshot).join(IndicatorSnapshot, (Candle.symbol == IndicatorSnapshot.symbol) & (Candle.timeframe == IndicatorSnapshot.timeframe) & (Candle.open_time == IndicatorSnapshot.open_time)).where(Candle.symbol == symbol, Candle.timeframe == timeframe).order_by(Candle.open_time.desc()).limit(limit)
    pairs = list(reversed(session.execute(query).all()))
    now = now_ms() + status["clock_offset_ms"]
    expected = now // INTERVAL_MS[timeframe] * INTERVAL_MS[timeframe] - INTERVAL_MS[timeframe]
    latest = pairs[-1][0] if pairs else None
    validated = contract is not None and contract.valid and 0 <= now_ms() - contract.checked_at <= 600_000
    warm = bool(state and state["count"] >= 500 and paired_state and paired_state["count"] >= 500)
    consistent = bool(state and pairs and pairs[-1][1].lineage == state["lineage"] and latest.open_time == state["last_open_time"])
    paired_expected = now // INTERVAL_MS[paired_timeframe] * INTERVAL_MS[paired_timeframe] - INTERVAL_MS[paired_timeframe]
    fresh = bool(latest and latest.open_time == expected and paired_state and paired_state["last_open_time"] == paired_expected)
    readiness = "ready" if validated and warm and fresh and consistent and status["live"] else "blocked-contract" if contract and not contract.valid else "pending-validation" if not validated else "warming-up" if not warm else "stale"
    series = {"candles": [], "ema20": [], "ema50": [], "sma200": [], "atr": []}
    for candle, snapshot in pairs:
        time = candle.open_time // 1000
        series["candles"].append({"time": time, **{key: getattr(candle, key) for key in ("open", "high", "low", "close")}})
        for key in ("ema20", "ema50", "sma200", "atr"):
            value = getattr(snapshot, key)
            if value is not None:
                series[key].append({"time": time, "value": value})
    values = {key: getattr(pairs[-1][1], key) if pairs else None for key in ("ema20", "ema50", "sma200", "atr")}
    aligned = None
    if all(values[k] is not None for k in ("ema20", "ema50", "sma200")):
        fast, slow, trend = (Decimal(values[k]) for k in ("ema20", "ema50", "sma200"))
        aligned = "long-trend" if fast > slow > trend else "short-trend" if fast < slow < trend else "mixed"
    metadata = contract.metadata_json if contract else {}
    filters = {f["filterType"]: f for f in metadata.get("filters", [])}
    return {"symbol": symbol, "timeframe": timeframe, "source": "binance-usdm", "status": readiness, "ready": readiness == "ready", "signal_generation": readiness == "ready" and engine_health(session)["ready"], "collector": status, "contract": {"valid": validated, "reason": contract.reason if contract else "Awaiting collector validation", "tick_size": filters.get("PRICE_FILTER", {}).get("tickSize"), "step_size": filters.get("LOT_SIZE", {}).get("stepSize")}, "bars": state["count"] if state else 0, "history_origin": state["history_origin"] if state else None, "last_close_time": latest.close_time if latest else None, "lineage": state["lineage"] if state else None, "values": values, "trend": aligned, "series": series}


def chosen_market_views(session):
    symbols = session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order))
    return [market_view(session, symbol, "1h", limit=2) for symbol in symbols]
