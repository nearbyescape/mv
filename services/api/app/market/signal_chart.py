"""Read-only bounded signal context; never creates plans or recalculates risk."""
from sqlalchemy import select
from app.models import Candle, IndicatorSnapshot
from .views import market_view


def signal_chart_view(session, signal, window):
    symbol, source = signal['symbol'], signal['source_open_time']
    current = market_view(session, symbol, '1h', limit=2)
    query = select(Candle, IndicatorSnapshot).join(IndicatorSnapshot,
        (Candle.symbol == IndicatorSnapshot.symbol) & (Candle.timeframe == IndicatorSnapshot.timeframe) &
        (Candle.open_time == IndicatorSnapshot.open_time)).where(Candle.symbol == symbol, Candle.timeframe == '1h')
    if window == 'source':
        query = query.where(Candle.open_time >= source - 96 * 3_600_000,
                            Candle.open_time <= source + 72 * 3_600_000)
    pairs = list(reversed(session.execute(query.order_by(Candle.open_time.desc()).limit(169 if window == 'source' else 120)).all()))
    series = {'candles': [], 'ema20': [], 'ema50': [], 'sma200': [], 'atr': []}
    for candle, snapshot in pairs:
        time = candle.open_time // 1000
        series['candles'].append({'time': time, **{key: getattr(candle,key) for key in ('open','high','low','close')}})
        for key in ('ema20','ema50','sma200','atr'):
            if getattr(snapshot,key) is not None:
                series[key].append({'time': time, 'value': getattr(snapshot,key)})
    return {'signal_id': signal['id'], 'plan_hash': signal['plan_hash'], 'symbol': symbol, 'timeframe': '1h',
            'source': 'binance-usdm', 'window': window, 'series': series,
            'live': current['ready'], 'market_status': current['status'],
            'source_candle_in_window': any(c.open_time == source for c,_ in pairs),
            'source_revised': signal['source_revised'], 'integrity_valid': signal['integrity_valid']}
