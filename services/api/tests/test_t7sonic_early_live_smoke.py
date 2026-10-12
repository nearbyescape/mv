"""No-network tests for V7Sonic early real-data engineering smoke."""
from __future__ import annotations
from copy import deepcopy
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import json

from services.t7sonic import early_live_smoke as smoke
from test_t7sonic_forward_release_bridge import source_bundle, BOUNDARY
from test_t7sonic_forward_live_quote import contract_data, book_data
from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_forward_protocol import START_MS


def data():
    bundle,_=source_bundle()
    candles={s:{f:bundle[s][f][1] for f in smoke.FRAMES} for s in MARKETS}
    books={s:book_data(s,event_ms=BOUNDARY+500) for s in MARKETS}
    receipts={s:BOUNDARY+1000 for s in MARKETS}
    return candles,books,contract_data(),receipts


class EarlySmokeTests(TestCase):
    def test_no_http_in_preflight_and_only_frozen_six_markets(self):
        with patch.object(smoke,"_get") as http:
            result=smoke.preflight(START_MS-86400000)
            self.assertEqual(result["network_calls"],0)
            self.assertTrue(result["separate_from_oct15_forward_study"])
            self.assertEqual(result["markets"],list(MARKETS))
            http.assert_not_called()

    def test_complete_six_market_source_yields_internal_only_paper(self):
        candles,books,exchange,receipts=data()
        result=smoke.analyze(
            BOUNDARY,candles,books,exchange,receipts,BOUNDARY+2000
        )
        self.assertEqual(result["market_count"],6)
        self.assertEqual(len(result["decisions"]),6)
        self.assertEqual(len(result["source_proofs"]),6)
        self.assertFalse(result["client_publication_authorized"])
        self.assertFalse(result["profitability_verified"])
        self.assertFalse(result["data_source_independently_attested"])
        self.assertFalse(result["telegram_enqueued"])
        self.assertEqual(result["orders_submitted"],False)
        self.assertTrue(result["formal_forward_window_unchanged"])

    def test_partial_source_and_corrupt_candle_refuse(self):
        candles,books,exchange,receipts=data()
        candles["BTCUSDT"].pop("1h")
        with self.assertRaises(ValueError):
            smoke.analyze(BOUNDARY,candles,books,exchange,receipts,BOUNDARY+2000)
        candles,books,exchange,receipts=data()
        rows=json.loads(candles["BTCUSDT"]["1m"])
        rows.pop()
        candles["BTCUSDT"]["1m"]=json.dumps(rows).encode()
        with self.assertRaises(ValueError):
            smoke.analyze(BOUNDARY,candles,books,exchange,receipts,BOUNDARY+2000)

    def test_too_late_and_book_timestamp_refuse(self):
        candles,books,exchange,receipts=data()
        with self.assertRaises(ValueError):
            smoke.analyze(BOUNDARY,candles,books,exchange,receipts,
                          BOUNDARY+30_001)
        with self.assertRaises(ValueError):
            smoke.analyze(BOUNDARY,candles,books,exchange,receipts,
                          BOUNDARY+6001)

    def test_unapproved_source_urls_rejected(self):
        with self.assertRaises(ValueError):
            smoke.url_for("FAKEUSDT","1m",BOUNDARY)
        with self.assertRaises(ValueError):
            smoke.url_for("BTCUSDT","5m",BOUNDARY)
        url=smoke.url_for("BTCUSDT","1m",BOUNDARY)
        self.assertIn("fapi.binance.com/fapi/v1/klines?",url)
        self.assertIn("limit=480",url)
        self.assertIn("endTime=",url)

    def test_live_capture_refuses_any_after_frozen_start_without_http(self):
        with TemporaryDirectory(prefix="v7sonic-early-live-test-") as folder:
            with patch.object(smoke.time,"time_ns",
                              return_value=(START_MS+1)*1_000_000):
                with patch.object(smoke,"_get") as http:
                    with patch.object(smoke.time,"sleep") as sleep:
                        with self.assertRaises(ValueError):
                            smoke.capture_one(folder)
                        sleep.assert_not_called()
                        http.assert_not_called()

    def test_private_directory_required(self):
        with TemporaryDirectory(prefix="v7sonic-early-live-test-") as folder:
            test_path=Path(folder)/"public"
            test_path.mkdir()
            test_path.chmod(0o755)
            with patch.object(smoke.time,"time_ns",
                              return_value=(START_MS-100_000)*1_000_000):
                with self.assertRaises(PermissionError):
                    smoke.capture_one(str(test_path))


if __name__=="__main__":
    import unittest
    unittest.main()
