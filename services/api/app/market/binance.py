"""Public exchange reads only. No account endpoints or credentials."""
import asyncio
from decimal import Decimal
import time

import httpx
from mv_strategy import Bar
from mv_strategy.signals import Quote


def now_ms():
    return time.time_ns() // 1_000_000


class RateLimited(RuntimeError):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super().__init__(f"Exchange rate limit; retry in {retry_after}s")


class BinancePublic:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def get(self, path, **params):
        for attempt in range(3):
            response = await self.client.get("https://fapi.binance.com" + path, params=params)
            if response.status_code in (418, 429):
                try:
                    delay = max(1, float(response.headers.get("Retry-After", "60")))
                except ValueError:
                    delay = 60
                raise RateLimited(delay)
            if response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError("Exchange unavailable")

    async def clock(self):
        start = now_ms()
        result = await self.get("/fapi/v1/time")
        end = now_ms()
        if end - start > 5000:
            raise ValueError("Exchange time request too slow to establish freshness")
        return int(result["serverTime"]), int(result["serverTime"]) - (start + end) // 2

    async def catalog(self):
        result = await self.get("/fapi/v1/exchangeInfo")
        return {row["symbol"]: row for row in result["symbols"]}

    async def quote(self, symbol, offset):
        result = await self.get("/fapi/v1/ticker/bookTicker", symbol=symbol)
        return parse_quote(result, symbol, now_ms() + offset)

    async def klines(self, symbol, timeframe, *, end_time, start_time=None, limit=1000):
        params = {"symbol": symbol, "interval": timeframe, "endTime": end_time, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        rows = await self.get("/fapi/v1/klines", **params)
        return [parse_rest_bar(row, timeframe) for row in rows]


def parse_rest_bar(row, timeframe):
    if not isinstance(row, list) or len(row) < 7:
        raise ValueError("Malformed REST candle")
    if any(not isinstance(value, str) for value in row[1:6]):
        raise ValueError("Exchange prices and volumes must be decimal strings")
    bar = Bar(int(row[0]), int(row[6]), *map(Decimal, row[1:6]))
    bar.validate(timeframe)
    return bar


def parse_stream_bar(payload, symbols):
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("Malformed stream event")
    if data.get("e") != "kline":
        return None
    k = data.get("k", {})
    if not isinstance(k, dict):
        raise ValueError("Malformed stream candle")
    if k.get("s") not in symbols or k.get("i") not in ("1h", "4h") or data.get("s") != k.get("s"):
        raise ValueError("Unexpected stream symbol or timeframe")
    if any(not isinstance(k.get(key), str) for key in ("o", "h", "l", "c", "v")):
        raise ValueError("Stream prices and volumes must be decimal strings")
    bar = Bar(int(k["t"]), int(k["T"]), *map(Decimal, (k["o"], k["h"], k["l"], k["c"], k["v"])))
    bar.validate(k["i"])
    if k.get("x") is False:
        return None
    if k.get("x") is not True:
        raise ValueError("Missing candle finalization flag")
    if int(data["E"]) <= bar.close_time:
        raise ValueError("Final candle arrived before its close boundary")
    return k["s"], k["i"], bar


def validate_contract(metadata):
    if metadata is None:
        return False, "Symbol is not listed on Binance USD-M futures"
    expected = {"status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "underlyingType": "COIN"}
    for field, value in expected.items():
        if metadata.get(field) != value:
            return False, f"Requires {field}={value}"
    filters = {row["filterType"]: row for row in metadata.get("filters", [])}
    try:
        values = (filters["PRICE_FILTER"]["tickSize"], filters["LOT_SIZE"]["stepSize"], filters["LOT_SIZE"]["minQty"], filters["MIN_NOTIONAL"]["notional"])
        if any(not Decimal(v).is_finite() or Decimal(v) <= 0 for v in values):
            raise ValueError("Invalid filters")
    except (KeyError, ValueError, ArithmeticError):
        return False, "Missing or invalid contract filters"
    return True, "Trading USDT crypto perpetual; filters verified"


def parse_quote(result, symbol, received_at):
    if not isinstance(result, dict) or result.get("symbol") != symbol or type(result.get("time")) is not int:
        raise ValueError("Malformed or mismatched book ticker")
    keys = ("bidPrice", "askPrice", "bidQty", "askQty")
    if any(not isinstance(result.get(key), str) for key in keys):
        raise ValueError("Book ticker values must be decimal strings")
    values = tuple(Decimal(result[key]) for key in keys)
    if any(not value.is_finite() or value <= 0 for value in values) or values[0] > values[1]:
        raise ValueError("Invalid book ticker prices, spread or liquidity")
    return Quote(symbol, *values, result["time"], received_at)
