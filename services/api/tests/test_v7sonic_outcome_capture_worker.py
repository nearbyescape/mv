"""Post-signal 120m public-data probe tests: all Binance GETs mocked."""
from __future__ import annotations

import base64
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

from services.t7sonic import outcome_capture_worker as worker

SOL = {
    "symbol":"SOLUSDT","direction":"LONG","expert":"breakout",
    "entry":"107.69","stop_loss":"106.8",
    "take_profit_1":"108.58","take_profit_2":"109.92",
}
DOGE = {
    "symbol":"DOGEUSDT","direction":"LONG","expert":"breakout",
    "entry":"0.08443","stop_loss":"0.08381",
    "take_profit_1":"0.08505","take_profit_2":"0.08598",
}


def _rows(symbol):
    from decimal import Decimal
    cand = SOL if symbol == "SOLUSDT" else DOGE
    entry = Decimal(cand["entry"])
    risk = entry - Decimal(cand["stop_loss"])
    rows = []
    for idx in range(120):
        t = worker.BOUNDARY + (idx + 1) * 60_000
        rows.append([
            t, str(entry), str(entry + risk / 10),
            str(entry - risk / 10), str(entry), "234.5",
            t + 59999, "0", 6, "0", "0", "0",
        ])
    return json.dumps(rows, separators=(",", ":")).encode()


class HistoricalCaptureTests(TestCase):
    def setUp(self):
        self.folder = TemporaryDirectory(prefix="v7-outcome-test-")
        self.addCleanup(self.folder.cleanup)
        self.outcomes = Path(self.folder.name)
        self.called_urls = []
        self.done_ms = worker.BOUNDARY + 122 * 60_000

    @staticmethod
    def verified_original(*a, **kw):
        return {
            "status": "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS",
            "candidates": [dict(SOL), dict(DOGE)],
        }

    def getter(self, url, maximum):
        self.called_urls.append(url)
        self.assertEqual(maximum, 256_000)
        parsed = urlparse(url)
        args = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "fapi.binance.com")
        self.assertEqual(parsed.path, "/fapi/v1/klines")
        self.assertEqual(args["interval"], ["1m"])
        self.assertEqual(args["limit"], ["120"])
        self.assertEqual(int(args["startTime"][0]), worker.BOUNDARY + 60_000)
        self.assertEqual(int(args["endTime"][0]),
                         worker.BOUNDARY + 121 * 60_000 - 1)
        return _rows(args["symbol"][0]), self.done_ms, 21.0

    def capture(self, **options):
        return worker.historic_one_shot_outcome(
            "/readonly-source", str(self.outcomes),
            public_network_approved=True,
            paper_only_acknowledged=True,
            clock_ms=lambda:self.done_ms,
            getter=self.getter,
            **options,
        )

    @patch.object(worker, "audit_one_stored_cycle")
    def test_complete_hist_source_is_saved_before_120m_reference_score(self, audit):
        audit.side_effect = self.verified_original
        report = self.capture()
        self.assertEqual(len(self.called_urls), 2)
        self.assertEqual(report["market_count"], 2)
        self.assertEqual([x["symbol"] for x in report["reference_results"]],
                         ["SOLUSDT", "DOGEUSDT"])
        self.assertEqual(report["entry_fills_proven"], 0)
        self.assertFalse(report["realized_net_pnl_verified"])
        self.assertEqual(report["telegram_messages_sent"], 0)
        self.assertEqual(report["orders_submitted"], 0)
        raw = next(self.outcomes.glob("v7sonic-outcome-original-http-*.json"))
        source = json.loads(raw.read_bytes())
        self.assertEqual(source["response_count"], 2)
        self.assertEqual(sha256(raw.read_bytes()).hexdigest(),
                         report["original_outcome_http_sha256"])
        for s in ("SOLUSDT", "DOGEUSDT"):
            result = source["outcome_bodies"][s]
            assert sha256(base64.b64decode(result["original_body_base64"])).hexdigest() == result["original_body_sha256"]
        self.assertEqual(len(list(self.outcomes.glob("v7sonic-outcome-reference-*.json"))),1)
        self.assertFalse(any(x["entry_fill_proven"] for x in report["reference_results"]))

    def test_no_operator_flags_prevents_original_account_and_market_access(self):
        with self.assertRaises(PermissionError):
            worker.historic_one_shot_outcome(
                "/readonly-source", str(self.outcomes))
        self.assertEqual(list(self.outcomes.iterdir()), [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_cannot_capture_before_last_120m_bar_closes(self, audit):
        with self.assertRaisesRegex(ValueError, "120 fully closed"):
            worker.historic_one_shot_outcome(
                "/readonly-source", str(self.outcomes),
                public_network_approved=True, paper_only_acknowledged=True,
                clock_ms=lambda:worker.BOUNDARY + 121 * 60_000 - 1,
                getter=self.getter,
            )
        audit.assert_not_called()
        self.assertEqual(self.called_urls, [])
        self.assertEqual(list(self.outcomes.iterdir()), [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_invalid_original_candidate_list_prevents_any_http(self, audit):
        audit.return_value = {"status":"wrong", "candidates":[]}
        with self.assertRaisesRegex(ValueError, "original candidate"):
            self.capture()
        self.assertEqual(self.called_urls, [])
        self.assertEqual(list(self.outcomes.iterdir()), [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_exactly_once_claim_blocks_second_request(self, audit):
        audit.side_effect = self.verified_original
        self.capture()
        self.called_urls.clear()
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual(self.called_urls, [])

    @patch.object(worker, "audit_one_stored_cycle")
    def test_missing_second_http_response_preserves_gap(self, audit):
        audit.side_effect = self.verified_original
        original_getter = self.getter
        def broken(url, maximum):
            if "DOGEUSDT" in url:
                raise TimeoutError("simulated source timeout")
            return original_getter(url, maximum)
        with self.assertRaisesRegex(TimeoutError, "timeout"):
            worker.historic_one_shot_outcome(
                "/readonly-source", str(self.outcomes),
                public_network_approved=True, paper_only_acknowledged=True,
                clock_ms=lambda:self.done_ms,
                getter=broken,
            )
        self.assertEqual(
            len(list(self.outcomes.glob("v7sonic-outcome-acquisition-gap-*.json"))),1
        )
        self.assertEqual(
            list(self.outcomes.glob("v7sonic-outcome-reference-*.json")), []
        )

    @patch.object(worker, "audit_one_stored_cycle")
    def test_invalid_120m_source_saved_then_rejected_never_claim_profit(self,audit):
        audit.side_effect = self.verified_original
        def bad(url, maximum):
            data, now, duration = self.getter(url,maximum)
            if "DOGEUSDT" in url:
                data = b"[]"
            return data, now, duration
        with self.assertRaisesRegex(ValueError, "120-minute"):
            worker.historic_one_shot_outcome(
                "/readonly-source", str(self.outcomes),
                public_network_approved=True, paper_only_acknowledged=True,
                clock_ms=lambda:self.done_ms,
                getter=bad,
            )
        self.assertEqual(
            len(list(self.outcomes.glob("v7sonic-outcome-original-http-*.json"))),1
        )
        self.assertEqual(
            len(list(self.outcomes.glob("v7sonic-outcome-analysis-rejected-*.json"))),1
        )
        self.assertEqual(
            list(self.outcomes.glob("v7sonic-outcome-reference-*.json")), []
        )
