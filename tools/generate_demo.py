"""Reproducible synthetic chart fixtures. These are never trading signals or exchange data."""
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path


def fixture(symbol, frame):
    rng = random.Random(f"mv-demo-{symbol}-{frame}")
    scale = 1 if symbol == "BTCUSDT" else 0.043
    step = 3600 if frame == "1h" else 14400
    end = int(datetime(2026, 9, 29, 12, tzinfo=timezone.utc).timestamp())
    candles, closes, ranges, ema20, ema50, sma200, atr = [], [], [], [], [], [], []
    previous = 0
    for i in range(500):
        close = (61200 + i * 13 + math.sin(i / 7) * 310 + math.sin(i / 19) * 380 + rng.uniform(-70, 70)) * scale
        opening = previous if i else close - 50 * scale
        high = max(close, opening) + rng.uniform(35, 120) * scale
        low = min(close, opening) - rng.uniform(35, 120) * scale
        time = end - (499 - i) * step
        candles.append({"time": time, "open": round(opening, 2), "high": round(high, 2), "low": round(low, 2), "close": round(close, 2)})
        closes.append(close)
        if i:
            ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        for period, series in [(20, ema20), (50, ema50)]:
            if i == period - 1:
                value = sum(closes[:period]) / period
            elif i >= period:
                value = 2 / (period + 1) * close + (1 - 2 / (period + 1)) * series[-1]["value"]
            else:
                continue
            series.append({"time": time, "value": value})
        if i >= 199:
            sma200.append({"time": time, "value": sum(closes[-200:]) / 200})
        if i == 14:
            value = sum(ranges[:14]) / 14
        elif i > 14:
            value = (13 * atr[-1]["value"] + ranges[-1]) / 14
        else:
            value = None
        if value is not None:
            atr.append({"time": time, "value": value})
        previous = close
    return {"candles": candles[-120:], "ema20": ema20[-120:], "ema50": ema50[-120:], "sma200": sma200[-120:], "atr": atr[-120:]}


output = Path(__file__).resolve().parents[1] / "apps/web/src/lib/demo-charts.json"
output.write_text(json.dumps({s: {f: fixture(s, f) for f in ["1h", "4h"]} for s in ["BTCUSDT", "ETHUSDT"]}, separators=(",", ":")), encoding="utf-8")
print(f"Wrote synthetic fixtures: {output}")
