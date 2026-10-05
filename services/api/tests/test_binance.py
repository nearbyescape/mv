import asyncio
from dataclasses import replace

import httpx
import pytest
from app.market.binance import BinancePublic, RateLimited, parse_rest_bar, parse_stream_bar, validate_contract, parse_quote
from test_indicators import bars


def contract():
    return {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT", "marginAsset": "USDT", "underlyingType": "COIN", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.1"}, {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"}, {"filterType": "MIN_NOTIONAL", "notional": "50"}]}


def test_contract_checks_crypto_trading_perpetual_and_filters():
    assert validate_contract(contract())[0] is True
    assert validate_contract(None)[0] is False
    for field, value in {"underlyingType": "TRADIFI", "status": "SETTLING", "marginAsset": "BTC", "contractType": "CURRENT_QUARTER"}.items():
        assert validate_contract({**contract(), field: value})[0] is False
    bad = contract()
    bad["filters"][0]["tickSize"] = "NaN"
    assert validate_contract(bad)[0] is False


def event(final=True):
    b = bars(1)[0]
    return {"stream": "btcusdt@kline_1h", "data": {"e": "kline", "E": b.close_time + 1, "s": "BTCUSDT", "k": {"s": "BTCUSDT", "i": "1h", "t": b.open_time, "T": b.close_time, "o": str(b.open), "h": str(b.high), "l": str(b.low), "c": str(b.close), "v": str(b.volume), "x": final}}}


def test_only_final_selected_symbol_stream_candles_are_accepted():
    assert parse_stream_bar(event(False), ["BTCUSDT"]) is None
    with pytest.raises(ValueError, match="Unexpected"):
        parse_stream_bar(event(False), ["ETHUSDT"])
    assert parse_stream_bar(event(), ["BTCUSDT"])[2] == bars(1)[0]
    with pytest.raises(ValueError, match="Unexpected"):
        parse_stream_bar(event(), ["ETHUSDT"])
    bad = event()
    bad["data"]["E"] = 0
    with pytest.raises(ValueError, match="before"):
        parse_stream_bar(bad, ["BTCUSDT"])
    bad = event()
    del bad["data"]["k"]["x"]
    with pytest.raises(ValueError, match="finalization"):
        parse_stream_bar(bad, ["BTCUSDT"])


def test_rest_parser_retains_exact_decimal_source_values():
    row = [0, "100.000000001", "101", "99", "100.000000002", "10", 3_599_999]
    parsed = parse_rest_bar(row, "1h")
    assert str(parsed.close) == "100.000000002"
    row[4] = 100.000000002
    with pytest.raises(ValueError, match="decimal strings"):
        parse_rest_bar(row, "1h")


def test_rate_limit_is_reported_without_immediate_retry():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(RateLimited) as error:
                await BinancePublic(client).catalog()
            assert error.value.retry_after == 120
    asyncio.run(run())
    assert len(requests) == 1


def test_book_quote_retains_exchange_timestamp_and_exact_prices():
    row = {"symbol": "BTCUSDT", "bidPrice": "100.00000001", "askPrice": "100.00000002", "bidQty": "1.000", "askQty": "2.001", "time": 123456789}
    quote = parse_quote(row, "BTCUSDT", 123456900)
    assert str(quote.ask) == "100.00000002"
    assert quote.time == 123456789 and quote.received_at == 123456900
    for change in ({"symbol": "ETHUSDT"}, {"time": 1.5}, {"askPrice": 100.00000002}, {"bidPrice": "NaN"}, {"bidPrice": "101"}, {"askQty": "0"}):
        with pytest.raises(ValueError):
            parse_quote({**row, **change}, "BTCUSDT", 123456900)
