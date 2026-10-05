"""Read-only live verification. Run from the root after API/collector startup."""
import asyncio
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
os.chdir(ROOT / "services" / "api")  # Match the API's documented local database/.env directory.

import httpx
from sqlalchemy import select
from mv_strategy import IndicatorState
from app.config import get_settings
from app.database import Session
from app.market.binance import BinancePublic
from app.market.store import as_bar, history
from app.models import IndicatorCheckpoint, IndicatorSnapshot, WatchlistItem


def independent_values(source):
    closes = [Fraction(bar.close) for bar in source]
    result = {"sma200": sum(closes[-200:]) / 200}
    for period, key in ((20, "ema20"), (50, "ema50")):
        alpha = Fraction(2, period + 1)
        decay = 1 - alpha
        seed = sum(closes[:period]) / period
        result[key] = seed * decay ** (len(source) - period) + alpha * sum(
            closes[i] * decay ** (len(source) - 1 - i) for i in range(period, len(source))
        )
    ranges = [max(Fraction(bar.high) - Fraction(bar.low), abs(Fraction(bar.high) - closes[i - 1]), abs(Fraction(bar.low) - closes[i - 1])) for i, bar in enumerate(source) if i]
    decay = Fraction(13, 14)
    result["atr"] = sum(ranges[:14]) / 14 * decay ** (len(ranges) - 14) + Fraction(1, 14) * sum(
        ranges[i] * decay ** (len(ranges) - 1 - i) for i in range(14, len(ranges))
    )
    return result


async def main():
    report = []
    with Session() as session:
        symbols = list(session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order)))
    async with httpx.AsyncClient(timeout=20) as client:
        health = (await client.get("http://127.0.0.1:8000/health")).raise_for_status().json()
        assert health["collector"]["live"], health["collector"]
        public = BinancePublic(client)
        for symbol in symbols:
            for timeframe in ("1h", "4h"):
                with Session() as session:
                    source = [as_bar(row) for row in history(session, symbol, timeframe)]
                    saved = session.get(IndicatorCheckpoint, (symbol, timeframe)).state_json
                    snapshot = session.get(IndicatorSnapshot, (symbol, timeframe, source[-1].open_time))
                    actual = {key: Decimal(getattr(snapshot, key)) for key in ("ema20", "ema50", "sma200", "atr")}
                assert len(source) >= 500
                restored = IndicatorState(timeframe)
                for bar in source:
                    restored.advance(bar)
                assert restored.dump() == saved, "Checkpoint must exactly match uninterrupted retained-history replay"
                for key, value in independent_values(source).items():
                    with localcontext() as context:
                        context.prec = 60
                        exact = Decimal(value.numerator) / Decimal(value.denominator)
                        assert abs(actual[key] - exact) <= Decimal("1e-28") * max(Decimal(1), abs(exact)), key
                direct = await public.klines(symbol, timeframe, end_time=source[-1].close_time, limit=3)
                assert len(direct) == 3 and direct == source[-3:], "Stored final OHLCV differs from direct Binance REST response"
                response = await client.get(f"http://127.0.0.1:8000/v1/markets/{symbol}", params={"timeframe": timeframe}, headers={"Authorization": f"Bearer {get_settings().dev_api_token}"})
                view = response.raise_for_status().json()
                assert view["ready"] and isinstance(view["signal_generation"], bool), view["status"]
                report.append({"symbol": symbol, "timeframe": timeframe, "bars": len(source), "history_origin": saved["history_origin"], "source_comparison": "3 direct Binance bars match", "checkpoint": "bit-identical replay", "indicators": "independent rational oracle matches", "status": view["status"]})
    result = {"collector": health["collector"], "markets": report}
    target = ROOT / "artifacts" / "live-market-verification.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
