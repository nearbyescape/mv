"""Offline raw-klines-to-V7Sonic batch integration, no network or clients."""
from __future__ import annotations

from copy import deepcopy
import unittest

from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_forward_protocol import START_MS, STEP_MS
from services.t7sonic.forward_release_bridge import (
    preview_from_raw_market_responses,
    preview_from_raw_candles_and_books,
)
from test_t7sonic_forward_acquisition import fake_response, as_bytes
from test_t7sonic_forward_live_quote import contract_data, book_data


BOUNDARY = START_MS + STEP_MS


def source_bundle():
    responses, quotes = {}, []
    for symbol in MARKETS:
        responses[symbol] = {}
        for frame in ("1m", "15m", "1h", "4h"):
            plan, rows = fake_response(frame, symbol=symbol, boundary=BOUNDARY)
            responses[symbol][frame] = (
                plan, as_bytes(rows), 200, BOUNDARY+1_000
            )
        quotes.append({
            "symbol": symbol, "decision_boundary_ms": BOUNDARY,
            "observed_at_ms": BOUNDARY+1_000,
            "evaluated_at_ms": BOUNDARY+2_000,
            "bid": "100.00", "ask": "100.01", "tick_size": "0.01",
        })
    return responses, quotes


class RawReleaseBridgeTests(unittest.TestCase):
    def test_full_six_market_synthetic_raw_batch_is_reconciled(self):
        sources, quotes = source_bundle()
        r = preview_from_raw_market_responses(BOUNDARY, sources, quotes)
        self.assertEqual(r["markets_evaluated"], 6)
        self.assertEqual(r["raw_source_response_count"], 24)
        self.assertEqual(set(r["source_geometry_checks"]), set(MARKETS))
        self.assertEqual(r["status"],
                         "24_RAW_RESPONSE_OFFLINE_PAPER_PLANS_UNATTESTED")
        self.assertFalse(r["real_https_performed"])
        self.assertFalse(r["telegram_enqueued"])
        self.assertFalse(r["real_money_orders_authorized"])
        self.assertFalse(r["actual_exchange_source_authenticated"])
        self.assertFalse(r["external_clock_receipt_verified"])
        self.assertEqual(
            r, preview_from_raw_market_responses(BOUNDARY, *source_bundle())
        )

    def test_invalid_or_missing_source_makes_whole_batch_fail(self):
        original, quotes = source_bundle()
        missing_market = deepcopy(original)
        missing_market.pop("ETHUSDT")
        with self.assertRaises(ValueError):
            preview_from_raw_market_responses(
                BOUNDARY, missing_market, quotes
            )
        missing_frame = deepcopy(original)
        missing_frame["SOLUSDT"].pop("1h")
        with self.assertRaises(ValueError):
            preview_from_raw_market_responses(
                BOUNDARY, missing_frame, quotes
            )

    def test_tampered_raw_price_or_changed_cutoff_rejected(self):
        sources, quotes = source_bundle()
        p, _, status, received = sources["BTCUSDT"]["1m"]
        sources["BTCUSDT"]["1m"] = (
            p, b"FAKE tampered body", status, received
        )
        with self.assertRaises(ValueError):
            preview_from_raw_market_responses(BOUNDARY, sources, quotes)
        sources, quotes = source_bundle()
        with self.assertRaises(ValueError):
            preview_from_raw_market_responses(
                BOUNDARY + STEP_MS, sources, quotes
            )

    def test_six_market_kline_plus_realistic_book_ticker_contract_integrates(self):
        sources, _ = source_bundle()
        ticks = {
            symbol: book_data(symbol=symbol, event_ms=BOUNDARY+500)
            for symbol in MARKETS
        }
        received = {symbol: BOUNDARY+1000 for symbol in MARKETS}
        evaluated = {symbol: BOUNDARY+2000 for symbol in MARKETS}
        out = preview_from_raw_candles_and_books(
            BOUNDARY, sources, ticks, contract_data(),
            received_ms_by_symbol=received,
            evaluated_ms_by_symbol=evaluated,
        )
        self.assertEqual(out["markets_evaluated"], 6)
        self.assertEqual(out["raw_source_response_count"], 24)
        self.assertEqual(out["top_of_book_responses_validated"], 6)
        self.assertEqual(len(out["quote_proofs"]), 6)
        self.assertEqual(len(out["venue_contracts"]), 6)
        self.assertFalse(out["real_network_used"])
        self.assertFalse(out["telegram_enqueued"])
        self.assertFalse(out["client_publication_authorized"])

    def test_missing_book_or_stale_quote_blocks_whole_market_batch(self):
        sources, _ = source_bundle()
        ticks = {
            symbol: book_data(symbol=symbol, event_ms=BOUNDARY+500)
            for symbol in MARKETS
        }
        received = {symbol: BOUNDARY+1000 for symbol in MARKETS}
        evaluated = {symbol: BOUNDARY+2000 for symbol in MARKETS}
        bad = dict(ticks)
        bad.pop("SOLUSDT")
        with self.assertRaises(ValueError):
            preview_from_raw_candles_and_books(
                BOUNDARY, sources, bad, contract_data(),
                received_ms_by_symbol=received,
                evaluated_ms_by_symbol=evaluated
            )
        bad = dict(ticks)
        bad["XRPUSDT"] = book_data(
            symbol="XRPUSDT", event_ms=BOUNDARY-6000
        )
        with self.assertRaises(ValueError):
            preview_from_raw_candles_and_books(
                BOUNDARY, sources, bad, contract_data(),
                received_ms_by_symbol=received,
                evaluated_ms_by_symbol=evaluated,
            )

    def test_market_quote_mismatch_aborts_without_partial_publication(self):
        sources, quotes = source_bundle()
        quotes[4]["symbol"] = "ETHUSDT"
        with self.assertRaises(ValueError):
            preview_from_raw_market_responses(BOUNDARY, sources, quotes)


if __name__ == "__main__":
    unittest.main()
