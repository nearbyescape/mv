"""Phase 2T offline USD-M kline acquisition envelope; synthetic payloads only."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
import json
import unittest

from app.research.t7sonic_forward_protocol import START_MS, STEP_MS
from app.research.t7sonic_perception import INTERVAL_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_acquisition import (
    ROWS_BY_FRAME, request_plan, parse_response_bytes,
    assemble_offline_snapshot,
)

SYMBOL = "BTCUSDT"
BOUNDARY = START_MS + STEP_MS
ONE_MIN_MS = 60_000
FIRST_MS = START_MS
TREND_STEP = D("0.0005")


def faux_kline(time_ms, interval):
    """Internally consistent synthetic OHLCV from one continuous minute series."""
    w = INTERVAL_MS[interval] // ONE_MIN_MS
    idx = (time_ms - FIRST_MS) // ONE_MIN_MS
    start = D("100") + D(idx) * TREND_STEP
    finish = D("100") + D(idx + w - 1) * TREND_STEP
    closing = finish + D(".005")
    return [
        time_ms, str(start), str(closing + D(".1")),
        str(start - D(".1")), str(closing), str(D(w)),
        time_ms + INTERVAL_MS[interval] - 1,
        "0", 1, "0", "0", "0",
    ]


def fake_response(frame, *, symbol=SYMBOL, boundary=BOUNDARY):
    p = request_plan(symbol, frame, boundary)
    step = INTERVAL_MS[frame]
    first = p["query"]["startTime"]
    rows = [
        faux_kline(first + i*step, frame)
        for i in range(p["query"]["limit"])
    ]
    return p, rows


def as_bytes(rows):
    return json.dumps(rows, separators=(",", ":")).encode("utf-8")


def valid_record(frame):
    p, rows = fake_response(frame)
    return (p, as_bytes(rows), 200, BOUNDARY+1000)


class AcquisitionEnvelopeTests(unittest.TestCase):
    def test_requests_have_only_completed_exact_window(self):
        for symbol in MARKETS:
            for frame, count in ROWS_BY_FRAME.items():
                with self.subTest(symbol=symbol, frame=frame):
                    p = request_plan(symbol, frame, BOUNDARY)
                    end = BOUNDARY // INTERVAL_MS[frame] * INTERVAL_MS[frame]
                    self.assertEqual(p["query"]["limit"], count)
                    self.assertEqual(p["query"]["startTime"],
                                     end-count*INTERVAL_MS[frame])
                    self.assertEqual(p["query"]["endTime"], end-1)
                    self.assertEqual(p["host"], "fapi.binance.com")
                    self.assertEqual(p["path"], "/fapi/v1/klines")
                    self.assertEqual(p["scheme"], "https")
                    self.assertFalse(p["http_implemented"])
                    self.assertFalse(p["trading_authorized"])

    def test_invalid_symbol_frame_boundary_rejected(self):
        for symbol, frame, boundary in [
            ("FAKEUSDT", "1m", BOUNDARY),
            ("BTCUSDT", "5m", BOUNDARY),
            ("BTCUSDT", "1m", START_MS-STEP_MS),
            ("BTCUSDT", "1m", START_MS+1),
            ("BTCUSDT", "1m", "2026-10-15"),
            ("BTCUSDT", "1m", True),
        ]:
            with self.subTest(symbol=symbol, frame=frame, boundary=boundary):
                with self.assertRaises(ValueError):
                    request_plan(symbol, frame, boundary)

    def test_complete_frames_assemble_and_reconcile_without_market_feed(self):
        values = {f: valid_record(f) for f in ROWS_BY_FRAME}
        perception, audit = assemble_offline_snapshot(
            SYMBOL, BOUNDARY, values
        )
        self.assertEqual(perception["symbol"], SYMBOL)
        self.assertEqual(perception["as_of_ms"], BOUNDARY)
        self.assertEqual(audit["status"], "OFFLINE_AS_OF_PERCEPTION_NOT_LIVE_SIGNAL")
        self.assertEqual(set(audit["frame_source_proofs"]), set(ROWS_BY_FRAME))
        self.assertFalse(audit["live_binance_collection_performed"])
        self.assertFalse(audit["independent_receipt_time_verified"])
        self.assertFalse(audit["outcome_labels_computed"])
        self.assertFalse(audit["trades_or_telegram_authorized"])
        proof = audit["native_cross_resolution_reconciliation"]
        self.assertEqual(proof["status"],
                         "STRICT_EXACT_CROSS_RESOLUTION_RECONCILIATION")
        for frame in ("15m", "1h", "4h"):
            self.assertGreaterEqual(
                proof["native_bars_reconciled_to_1m"][frame], 1
            )
        for frame, record in values.items():
            self.assertEqual(audit["frame_source_proofs"][frame]["response_body_sha256"],
                             sha256(record[1]).hexdigest())

    def test_duplicate_missing_future_or_closed_time_mismatch_rejected(self):
        p, rows = fake_response("1m")
        cases = {
            "truncated": rows[:-1],
            "overlong": rows+[rows[-1]],
            "out_of_order": list(reversed(rows)),
            "duplicated": rows[:-1]+[rows[-2]],
        }
        for name, mutated in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_response_bytes(
                    p, as_bytes(mutated), http_status=200,
                    receipt_ms_claim=BOUNDARY+1000
                )
        bad = deepcopy(rows)
        bad[-1][6] += 60_000
        with self.assertRaisesRegex(ValueError, "partial"):
            parse_response_bytes(
                p, as_bytes(bad), http_status=200,
                receipt_ms_claim=BOUNDARY+1000,
            )

    def test_fail_closed_undocumented_http_and_untrusted_timestamp_claims(self):
        p, rows = fake_response("1m")
        for status in (301, 429, 500, True):
            with self.subTest(http_status=status), self.assertRaises(ValueError):
                parse_response_bytes(
                    p, as_bytes(rows), http_status=status,
                    receipt_ms_claim=BOUNDARY+1000
                )
        for received in (BOUNDARY-1, BOUNDARY+60001, "now", True):
            with self.subTest(receipt=received), self.assertRaises(ValueError):
                parse_response_bytes(
                    p, as_bytes(rows), http_status=200,
                    receipt_ms_claim=received
                )
        invalid = deepcopy(p)
        invalid["query"]["endTime"] += 60_000
        with self.assertRaisesRegex(ValueError, "metadata mismatch"):
            parse_response_bytes(
                invalid, as_bytes(rows), http_status=200,
                receipt_ms_claim=BOUNDARY+1000
            )
        with self.assertRaisesRegex(ValueError, "raw kline"):
            parse_response_bytes(
                p, b"x"*256001, http_status=200,
                receipt_ms_claim=BOUNDARY+1000,
            )

    def test_tampered_ohlcv_and_cross_timeframe_disagreement_rejected(self):
        recs = {f: valid_record(f) for f in ROWS_BY_FRAME}
        p, rows = fake_response("1m")
        bad = deepcopy(rows)
        bad[15][3] = "-10"
        with self.assertRaises(ValueError):
            parse_response_bytes(
                p, as_bytes(bad), http_status=200,
                receipt_ms_claim=BOUNDARY+1000
            )
        p, rows = fake_response("1h")
        rows[-1][4] = str(D(rows[-1][4]) + D("0.01"))
        recs["1h"] = (p, as_bytes(rows), 200, BOUNDARY+1000)
        with self.assertRaisesRegex(ValueError, "contradicts"):
            assemble_offline_snapshot(SYMBOL, BOUNDARY, recs)

    def test_missing_frame_or_wrong_market_blocked(self):
        recs = {f: valid_record(f) for f in ROWS_BY_FRAME}
        missing = dict(recs)
        missing.pop("4h")
        with self.assertRaises(ValueError):
            assemble_offline_snapshot(SYMBOL, BOUNDARY, missing)
        with self.assertRaises(ValueError):
            assemble_offline_snapshot("SOLUSDT", BOUNDARY, recs)


if __name__ == "__main__":
    unittest.main()
