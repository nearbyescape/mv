"""Synthetic-only Binance USDM quote/contract adapter tests: no network."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import unittest

from app.research.t7sonic_forward_protocol import START_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_live_quote import (
    extract_contract_rule, parse_book_ticker,
)


BOUNDARY = START_MS
SYMBOL = "BTCUSDT"


def info_market(symbol=SYMBOL):
    return {
        "symbol": symbol, "status": "TRADING",
        "contractType": "PERPETUAL", "quoteAsset": "USDT",
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "minPrice": "0.01", "maxPrice": "1000000.00",
                "tickSize": "0.01",
            },
            {
                "filterType": "LOT_SIZE",
                "minQty": "0.001", "maxQty": "100000",
                "stepSize": "0.001",
            },
        ],
        "pricePrecision": 8,
    }


def contract_data(markets=None):
    return json.dumps({"symbols": markets if markets is not None else [
        info_market(symbol) for symbol in MARKETS
    ]}, separators=(",", ":")).encode()


def book_data(symbol=SYMBOL, event_ms=BOUNDARY+500):
    return json.dumps({
        "symbol": symbol,
        "bidPrice": "100.00", "bidQty": "10",
        "askPrice": "100.01", "askQty": "20",
        "time": event_ms,
    }, separators=(",", ":")).encode()


class ContractAndQuoteTests(unittest.TestCase):
    def test_all_six_usdm_perpetual_price_filters_not_precision_proxy(self):
        source = contract_data()
        for symbol in MARKETS:
            with self.subTest(symbol=symbol):
                result = extract_contract_rule(source, symbol)
                self.assertEqual(result["tick_size"], "0.01")
                self.assertEqual(result["lot_size_step"], "0.001")
                self.assertEqual(result["contract_source_sha256"],
                                 sha256(source).hexdigest())
                self.assertFalse(result["quote_and_contract_authenticated"])

    def test_usable_completed_boundary_quote_from_book_event_time(self):
        venue = extract_contract_rule(contract_data(), SYMBOL)
        raw = book_data()
        quote, proof = parse_book_ticker(
            SYMBOL, BOUNDARY, raw, venue,
            received_ms=BOUNDARY+1000,
            evaluated_ms=BOUNDARY+1500,
        )
        self.assertEqual(quote["observed_at_ms"], BOUNDARY+500)
        self.assertEqual(quote["bid"], "100.00")
        self.assertEqual(quote["ask"], "100.01")
        self.assertEqual(quote["tick_size"], "0.01")
        self.assertFalse(proof["independent_receipt_witness_verified"])
        self.assertFalse(proof["trading_authorized"])
        self.assertEqual(proof["book_ticker_sha256"],
                         sha256(raw).hexdigest())

    def test_nontrading_quarterly_wrong_quote_market_and_missing_filters_refused(self):
        for field, value in (
            ("status", "BREAK"),
            ("contractType", "CURRENT_QUARTER"),
            ("quoteAsset", "BUSD"),
        ):
            original = info_market()
            original[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                extract_contract_rule(contract_data([original]), SYMBOL)
        missing = info_market()
        missing["filters"].pop()
        with self.assertRaises(ValueError):
            extract_contract_rule(contract_data([missing]), SYMBOL)
        dup = [info_market(), info_market()]
        with self.assertRaises(ValueError):
            extract_contract_rule(contract_data(dup), SYMBOL)
        with self.assertRaises(ValueError):
            extract_contract_rule(contract_data([info_market("SOLUSDT")]), SYMBOL)

    def test_wrong_precision_or_filter_geometry_refused(self):
        cases = [
            ("PRICE_FILTER", "tickSize", "0"),
            ("PRICE_FILTER", "maxPrice", "0.001"),
            ("LOT_SIZE", "stepSize", "0"),
            ("LOT_SIZE", "maxQty", "0.0001"),
            ("LOT_SIZE", "minQty", "-1"),
        ]
        for type_, key, val in cases:
            row = info_market()
            next(x for x in row["filters"] if x["filterType"] == type_)[key] = val
            with self.subTest(type_=type_, key=key), self.assertRaises(ValueError):
                extract_contract_rule(contract_data([row]), SYMBOL)

    def test_stale_future_or_boundary_mismatch_refused(self):
        v = extract_contract_rule(contract_data(), SYMBOL)
        for event, receive, evaluate in (
            (BOUNDARY-1, BOUNDARY+1000, BOUNDARY+2000),
            (BOUNDARY+1002, BOUNDARY+1000, BOUNDARY+2000),
            (BOUNDARY+1000, BOUNDARY+1001, BOUNDARY+7000),
            (BOUNDARY+500, BOUNDARY+1000, BOUNDARY+7000),
            (BOUNDARY+500, BOUNDARY+31_000, BOUNDARY+31_100),
        ):
            with self.subTest(event=event, receive=receive, evaluated=evaluate):
                with self.assertRaises(ValueError):
                    parse_book_ticker(
                        SYMBOL, BOUNDARY, book_data(event_ms=event), v,
                        received_ms=receive, evaluated_ms=evaluate
                    )

    def test_bad_bid_ask_and_price_tick_alignment_refused(self):
        v = extract_contract_rule(contract_data(), SYMBOL)
        for field, bad in (
            ("bidPrice", "100.02"),
            ("askPrice", "100.00"),
            ("bidPrice", "100.001"),
            ("askPrice", "100.005"),
            ("bidQty", "0"),
            ("askQty", "NaN"),
            ("symbol", "ETHUSDT"),
            ("time", True),
        ):
            item = json.loads(book_data())
            item[field] = bad
            with self.subTest(field=field, val=bad), self.assertRaises(ValueError):
                parse_book_ticker(
                    SYMBOL, BOUNDARY, json.dumps(item).encode(), v,
                    received_ms=BOUNDARY+1000,
                    evaluated_ms=BOUNDARY+2000,
                )

    def test_no_network_or_trusted_client_witness_is_claimed(self):
        v = extract_contract_rule(contract_data(), SYMBOL)
        quote, proof = parse_book_ticker(
            SYMBOL, BOUNDARY, book_data(), v,
            received_ms=BOUNDARY+1000,
            evaluated_ms=BOUNDARY+2000,
        )
        self.assertNotIn("signature_verified", quote)
        self.assertFalse(proof["actual_available_fill_liquidity_verified"])
        with self.assertRaises(ValueError):
            parse_book_ticker(
                "FAKEUSDT", BOUNDARY, book_data(), v,
                received_ms=BOUNDARY+1000, evaluated_ms=BOUNDARY+2000,
            )


if __name__ == "__main__":
    unittest.main()
