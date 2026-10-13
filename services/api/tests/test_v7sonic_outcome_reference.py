"""V7 historical post-decision evidence; no false fills or profits."""
import json
from decimal import Decimal
from unittest import TestCase

from services.t7sonic.outcome_reference import (
    full_post_decision_minute_bars, score_reference_path,
)
from test_t7sonic_forward_release_bridge import BOUNDARY

SOL = {
    "symbol": "SOLUSDT", "direction": "LONG", "expert": "breakout",
    "entry": "107.69", "stop_loss": "106.8",
    "take_profit_1": "108.58", "take_profit_2": "109.92",
}
DOGE = {
    "symbol": "DOGEUSDT", "direction": "LONG", "expert": "breakout",
    "entry": "0.08443", "stop_loss": "0.08381",
    "take_profit_1": "0.08505", "take_profit_2": "0.08598",
}


def minute_fixture(*, symbol="SOLUSDT", first_high="108", first_low="107.4"):
    entry = Decimal(SOL["entry"] if symbol == "SOLUSDT" else DOGE["entry"])
    first_high = Decimal(str(first_high))
    first_low = Decimal(str(first_low))
    rows = []
    for i in range(120):
        opening = BOUNDARY + (i + 1) * 60_000
        h = first_high if i == 0 else entry + Decimal("0.05")
        l = first_low if i == 0 else entry - Decimal("0.05")
        rows.append([
            opening, str(entry), str(h), str(l), str(entry), "200.0",
            opening + 59_999, "0", 7, "0", "0", "0",
        ])
    return json.dumps(rows, separators=(",", ":")).encode()


class OutcomeReferenceTests(TestCase):
    def test_complete_120_candles_are_after_decision_partial_minute(self):
        payload = minute_fixture()
        bars = full_post_decision_minute_bars("SOLUSDT", BOUNDARY, payload)
        self.assertEqual(len(bars), 120)
        self.assertEqual(bars[0]["open_ms"], BOUNDARY + 60_000)
        self.assertEqual(bars[-1]["open_ms"], BOUNDARY + 120 * 60_000)
        result = score_reference_path(SOL, bars)
        self.assertFalse(result["entry_fill_proven"])
        self.assertFalse(result["initial_30_second_entry_window_observable"])
        self.assertFalse(result["realized_return_or_profit_claim"])
        self.assertEqual(set(result["horizon_closes_in_full_post_decision_minutes"]),
                         {"15", "30", "60", "120"})
        self.assertEqual(result["first_reference_barrier_event"],
                         "NONE_WITHIN_120_FULL_POST_DECISION_MINUTES")

    def test_target_first_without_stop_reference(self):
        raw = minute_fixture(first_high="108.59")
        out = score_reference_path(SOL, full_post_decision_minute_bars(
            "SOLUSDT", BOUNDARY, raw))
        self.assertEqual(out["first_reference_barrier_event"],
                         "INITIAL_TP1_REFERENCE_TOUCHED_FIRST")
        self.assertEqual(out["first_event_post_decision_full_minute_index"], 1)
        self.assertTrue(out["any_tp1_reference_touch"])
        self.assertFalse(out["any_tp2_reference_touch"])
        self.assertFalse(out["any_stop_reference_touch"])
        self.assertFalse(out["entry_fill_proven"])

    def test_stop_first_without_target_reference(self):
        raw = minute_fixture(first_low="106.7")
        out = score_reference_path(SOL, full_post_decision_minute_bars(
            "SOLUSDT", BOUNDARY, raw))
        self.assertEqual(out["first_reference_barrier_event"],
                         "INITIAL_STOP_REFERENCE_TOUCHED_FIRST")
        self.assertTrue(out["any_stop_reference_touch"])
        self.assertFalse(out["entry_fill_proven"])

    def test_intraminute_both_stop_and_target_is_ambiguous(self):
        raw = minute_fixture(first_high="109.93", first_low="106.70")
        out = score_reference_path(SOL, full_post_decision_minute_bars(
            "SOLUSDT", BOUNDARY, raw))
        self.assertEqual(out["first_reference_barrier_event"],
                         "AMBIGUOUS_SL_AND_TP1_SAME_ONE_MINUTE_CANDLE")
        self.assertTrue(out["any_tp2_reference_touch"])
        self.assertTrue(out["any_stop_reference_touch"])
        self.assertFalse(out["realized_return_or_profit_claim"])

    def test_doge_reference_units(self):
        raw = minute_fixture(symbol="DOGEUSDT",
                             first_high="0.08507", first_low="0.08410")
        out = score_reference_path(DOGE, full_post_decision_minute_bars(
            "DOGEUSDT", BOUNDARY, raw))
        self.assertEqual(out["risk_unit_quote_per_coin"], "0.00062")
        self.assertEqual(out["first_reference_barrier_event"],
                         "INITIAL_TP1_REFERENCE_TOUCHED_FIRST")

    def test_omitted_missing_or_extra_candles_rejected(self):
        data = json.loads(minute_fixture())
        for modified in (data[:-1], data + [data[-1]]):
            with self.subTest(size=len(modified)):
                with self.assertRaisesRegex(ValueError, "120-minute"):
                    full_post_decision_minute_bars("SOLUSDT", BOUNDARY,
                                                  json.dumps(modified).encode())
        data[15][0] += 60_000
        with self.assertRaisesRegex(ValueError, "Out-of-order"):
            full_post_decision_minute_bars("SOLUSDT", BOUNDARY,
                                          json.dumps(data).encode())

    def test_never_accept_decision_partial_minute_as_full_bar(self):
        rows = json.loads(minute_fixture())
        rows[0][0] = BOUNDARY
        rows[0][6] = BOUNDARY + 59_999
        with self.assertRaisesRegex(ValueError, "partial"):
            full_post_decision_minute_bars("SOLUSDT", BOUNDARY,
                                          json.dumps(rows).encode())

    def test_missing_stop_invalid_geometry_rejected(self):
        bars = full_post_decision_minute_bars(
            "SOLUSDT", BOUNDARY, minute_fixture())
        bad = dict(SOL, stop_loss="108")
        with self.assertRaisesRegex(ValueError, "geometry"):
            score_reference_path(bad, bars)
