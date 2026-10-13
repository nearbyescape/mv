"""All V7 subminute source requests mocked; paper-only fail-closed research."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from services.t7sonic import entry_tape_reference as reference
from services.t7sonic import entry_tape_capture_worker as worker

CANDIDATES = [
    {
        "symbol": "SOLUSDT", "direction": "LONG", "expert": "breakout",
        "entry": "107.69", "stop_loss": "106.8",
    },
    {
        "symbol": "DOGEUSDT", "direction": "LONG", "expert": "breakout",
        "entry": "0.08443", "stop_loss": "0.08381",
    },
]


def _rows(start, *, symbol, count=2, price=None):
    if price is None:
        price = "107.71" if symbol == "SOLUSDT" else "0.08442"
    return json.dumps([
        {
            "a": start + i, "p": price, "q": "0.3",
            "f": start + i, "l": start + i, "T": start + i,
            "m": False,
        }
        for i in range(count)
    ]).encode()


class EntryTapeTests(TestCase):
    def setUp(self):
        self.d = TemporaryDirectory(prefix="v7-30s-tape-test-")
        self.addCleanup(self.d.cleanup)
        self.out = Path(self.d.name)
        self.request_urls = []
        self.verified = {
            "status": "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS",
            "candidates": CANDIDATES,
            "decision_paper_journal_inserted_ms_local_unattested":
                reference.BOUNDARY + 2000,
        }

    def getter(self, url, cap):
        self.request_urls.append(url)
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "fapi.binance.com")
        self.assertEqual(parsed.path, "/fapi/v1/aggTrades")
        self.assertEqual(cap, 256_000)
        self.assertEqual(q["limit"], ["1000"])
        self.assertIn(q["symbol"][0], reference.SYMBOLS)
        start, end = int(q["startTime"][0]), int(q["endTime"][0])
        self.assertEqual(end - start, 4999)
        self.assertTrue(reference.BOUNDARY <= start < reference.WINDOW_END)
        return _rows(start+3000, symbol=q["symbol"][0]), (
            reference.WINDOW_END + 60000, 1.0
        )

    def invoke(self, *, getter=None, clock=None):
        return worker.capture_entry_tape(
            "/readonly-source", str(self.out),
            public_network_approved=True,
            paper_only_acknowledged=True,
            getter=getter or self.getter,
            clock_ms=clock or (lambda:reference.WINDOW_END + 60000),
        )

    @patch.object(worker, "audit_one_stored_cycle")
    def test_twelve_complete_original_responses_durable_before_score(self, audit):
        audit.return_value = self.verified
        out = self.invoke()
        self.assertEqual(out["original_http_response_count_saved"], 12)
        self.assertEqual(len(self.request_urls), 12)
        self.assertEqual([x["symbol"] for x in out["observations"]],
                         list(reference.SYMBOLS))
        self.assertFalse(out["actual_quotes_or_client_order_fills_verified"])
        self.assertEqual(out["telegram_messages_sent"], 0)
        self.assertEqual(out["orders_submitted"], 0)
        self.assertEqual(len(list(self.out.glob("v7sonic-entry-tape-original-*.json"))), 12)
        self.assertEqual(len(list(self.out.glob("v7sonic-entry-tape-report-*.json"))), 1)
        self.assertEqual(out["observations"][0][
            "first_post_journal_print_at_or_above_entry_ms"
        ], reference.BOUNDARY + 3000)

    @patch.object(worker, "audit_one_stored_cycle")
    def test_only_one_original_batch_can_be_claimed(self, audit):
        audit.return_value = self.verified
        self.invoke()
        self.request_urls.clear()
        with self.assertRaises(FileExistsError):
            self.invoke()
        self.assertEqual(self.request_urls, [])

    def test_flags_missing_never_contact_source_or_network(self):
        with self.assertRaises(PermissionError):
            worker.capture_entry_tape("/readonly-source", str(self.out))
        self.assertEqual(list(self.out.iterdir()), [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_early_or_outside_retention_guard_before_network(self, audit):
        for ms in (reference.WINDOW_END,
                   reference.BOUNDARY + 40 * 60 * 60 * 1000):
            with self.subTest(clock=ms):
                with self.assertRaisesRegex(ValueError, "retention guard"):
                    self.invoke(clock=lambda ms=ms:ms)
        audit.assert_not_called()
        self.assertEqual(self.request_urls, [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_no_credible_post_decision_clock_fail_closed(self, audit):
        audit.return_value = {
            **self.verified,
            "decision_paper_journal_inserted_ms_local_unattested":
                reference.WINDOW_END,
        }
        with self.assertRaisesRegex(ValueError, "clock"):
            self.invoke()
        self.assertEqual(self.request_urls, [])

    def test_decode_full_limit_is_not_assumed_complete(self):
        raw = _rows(reference.BOUNDARY, symbol="SOLUSDT", count=1000)
        with self.assertRaisesRegex(ValueError, "POSSIBLY_TRUNCATED"):
            reference.decode_slice(
                raw, start_ms=reference.BOUNDARY,
                end_ms=reference.BOUNDARY + 5000,
            )

    @patch.object(worker, "audit_one_stored_cycle")
    def test_truncated_source_saves_original_then_rejects_without_report(self,audit):
        audit.return_value = self.verified
        def too_many(url,maximum):
            p=urlparse(url)
            q=parse_qs(p.query)
            return (_rows(int(q["startTime"][0]),
                symbol=q["symbol"][0], count=1000),
                reference.WINDOW_END + 60_000, 1)
        with self.assertRaisesRegex(ValueError, "POSSIBLY_TRUNCATED"):
            self.invoke(getter=too_many)
        self.assertEqual(len(list(self.out.glob("v7sonic-entry-tape-original-*.json"))),1)
        self.assertEqual(len(list(self.out.glob("v7sonic-entry-tape-incomplete-*.json"))),1)
        self.assertEqual(list(self.out.glob("v7sonic-entry-tape-report-*.json")),[])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_public_get_timeout_retains_gap_and_no_result(self,audit):
        audit.return_value = self.verified
        def timeout(url, maximum):
            raise TimeoutError("HTTP time limit")
        with self.assertRaisesRegex(TimeoutError, "time limit"):
            self.invoke(getter=timeout)
        self.assertEqual(len(list(self.out.glob("v7sonic-entry-tape-incomplete-*.json"))),1)
        self.assertEqual(list(self.out.glob("v7sonic-entry-tape-report-*.json")),[])

    def test_a_trade_price_touch_does_not_imply_a_fill(self):
        sliced = [reference.decode_slice(
            _rows(reference.BOUNDARY+i*5000 + 3000, symbol="SOLUSDT"),
            start_ms=reference.BOUNDARY+i*5000,
            end_ms=reference.BOUNDARY+(i+1)*5000)
            for i in range(6)]
        scored = reference.score_entry_window(
            CANDIDATES[0],
            journal_inserted_ms=reference.BOUNDARY+2000,
            trade_slices=sliced,
        )
        self.assertTrue(scored["any_post_journal_trade_price_at_or_above_entry"])
        self.assertFalse(scored["original_entry_order_or_fill_proven"])
        self.assertFalse(scored["actual_quote_liquidity_verified"])

    def test_pre_paper_journal_prints_do_not_count_as_entry(self):
        sliced = [reference.decode_slice(
            _rows(reference.BOUNDARY+i*5000, symbol="SOLUSDT",
                  price="108.50" if i == 0 else "107.00"),
            start_ms=reference.BOUNDARY+i*5000,
            end_ms=reference.BOUNDARY+(i+1)*5000)
            for i in range(6)]
        scored = reference.score_entry_window(
            CANDIDATES[0],
            journal_inserted_ms=reference.BOUNDARY+2000,
            trade_slices=sliced,
        )
        self.assertFalse(scored["any_post_journal_trade_price_at_or_above_entry"])
        self.assertFalse(scored["original_entry_order_or_fill_proven"])

    def test_ordering_and_out_of_range_prices_fail_closed(self):
        raw = json.loads(_rows(reference.BOUNDARY, symbol="SOLUSDT"))
        raw[0]["T"] = reference.BOUNDARY-1
        with self.assertRaisesRegex(ValueError, "off-window"):
            reference.decode_slice(json.dumps(raw).encode(),
                start_ms=reference.BOUNDARY,
                end_ms=reference.BOUNDARY+5000)
        raw[0]["T"] = reference.BOUNDARY
        raw[0]["p"] = "NaN"
        with self.assertRaisesRegex(ValueError, "Invalid trade decimal"):
            reference.decode_slice(json.dumps(raw).encode(),
                start_ms=reference.BOUNDARY,
                end_ms=reference.BOUNDARY+5000)
