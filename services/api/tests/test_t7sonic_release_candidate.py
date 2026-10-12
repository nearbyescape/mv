"""V7Sonic release-candidate numerical plan tests, all offline and synthetic."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
import unittest

from test_t7sonic_perception import fixture, AS_OF
from app.research.t7sonic_release_candidate import (
    indicative_plan, POLICY,
)


def breakout():
    snapshot = fixture()
    candle = snapshot["bars"]["5m"][-1]
    candle.update({
        "close": "103.10",
        "high": "103.50",
        "low": "102.20",
        "volume": "300",
    })
    return snapshot


def quote(*, symbol="BTCUSDT", boundary=AS_OF, observed=None,
          evaluated=None, bid="103.09", ask="103.10", tick="0.01"):
    return {
        "symbol": symbol, "decision_boundary_ms": boundary,
        "observed_at_ms": boundary+1000 if observed is None else observed,
        "evaluated_at_ms": boundary+2000 if evaluated is None else evaluated,
        "bid": bid, "ask": ask, "tick_size": tick,
    }


class ReleaseCandidateTests(unittest.TestCase):
    def test_complete_long_plan_with_levels_and_no_publishable_state(self):
        plan = indicative_plan(breakout(), quote())
        self.assertEqual(plan["policy"], POLICY)
        self.assertEqual(plan["direction"], "LONG")
        self.assertEqual(plan["symbol"], "BTCUSDT")
        entry, sl, tp1, tp2 = (
            D(plan[k]) for k in (
                "entry", "stop_loss", "take_profit_1", "take_profit_2"
            )
        )
        self.assertLess(sl, entry)
        self.assertLess(entry, tp1)
        self.assertLess(tp1, tp2)
        self.assertGreaterEqual(D(plan["estimated_net_rr_tp2_if_filled"]), D("1.5"))
        self.assertGreaterEqual(D(plan["estimated_net_rr_50_50_if_both_tps_filled"]), D("1.25"))
        self.assertEqual(plan["max_equity_risk_percent"], "0.5")
        self.assertIsNone(plan["win_probability"])
        self.assertFalse(plan["publishable_signal"])
        self.assertFalse(plan["executable_order"])
        self.assertFalse(plan["actual_fill_verified"])
        self.assertFalse(plan["source_origin_independently_verified"])
        self.assertEqual(plan, indicative_plan(deepcopy(breakout()), deepcopy(quote())))
        self.assertEqual(len(plan["candidate_sha256"]), 64)

    def test_no_trade_on_locked_market(self):
        plan = indicative_plan(breakout(), quote(), active_symbols=("BTCUSDT",))
        self.assertEqual(plan["status"], "NO_CANDIDATE")
        self.assertEqual(plan["reason"], "ACTIVE_POSITION_LOCK")
        self.assertFalse(plan["publishable_signal"])

    def test_reject_quote_staleness_future_deadline_and_market_mismatch(self):
        invalid = [
            quote(symbol="ETHUSDT"),
            quote(boundary=AS_OF+300_000),
            quote(observed=AS_OF-1, evaluated=AS_OF+2000),
            quote(observed=AS_OF+1000, evaluated=AS_OF+7000),
            quote(observed=AS_OF+31_000, evaluated=AS_OF+31_001),
            quote(observed="not-integer"),
            quote(observed=True),
            quote(bid="103.11", ask="103.10"),
            quote(bid="102", ask="104"),
            quote(bid="103.091"),
            quote(tick="0"),
            quote(ask="NaN"),
        ]
        for i, q in enumerate(invalid):
            with self.subTest(i=i), self.assertRaises(ValueError):
                indicative_plan(breakout(), q)

    def test_reject_quote_drift_after_completed_candle(self):
        p = indicative_plan(breakout(), quote(bid="103.99", ask="104.00"))
        self.assertEqual(p["reason"], "ENTRY_DRIFT_TOO_LARGE")

    def test_bad_source_or_lookahead_candle_rejected(self):
        sample = breakout()
        sample["bars"]["5m"][-1]["close"] = "NaN"
        with self.assertRaises(ValueError):
            indicative_plan(sample, quote())
        sample = breakout()
        sample["bars"]["5m"][-1]["open_ms"] += 300_000
        with self.assertRaises(ValueError):
            indicative_plan(sample, quote())

    def test_wrong_lock_snapshot_and_symbol_refused(self):
        for active in (["BTCUSDT"], ("BTCUSDT", "BTCUSDT"), ("FAKE",)):
            with self.assertRaises(ValueError):
                indicative_plan(breakout(), quote(), active_symbols=active)
        snap = breakout()
        snap["symbol"] = "FAKEUSDT"
        with self.assertRaises(ValueError):
            indicative_plan(snap, quote(symbol="FAKEUSDT"))

    def test_valid_short_geometry_from_reversal_event(self):
        snap = fixture()
        m5 = snap["bars"]["5m"][-1]
        # Sweeps a 20-bar high and closes back in range.
        m5.update({
            "high": "104.00", "low": "102.00",
            "open": "103.00", "close": "102.50", "volume": "130",
        })
        one = snap["bars"]["1m"][-1]
        one.update({
            "open": "102.90", "high": "103.15",
            "low": "102.40", "close": "102.50",
        })
        plan = indicative_plan(
            snap, quote(bid="102.49", ask="102.50")
        )
        self.assertEqual(plan["direction"], "SHORT")
        self.assertEqual(plan["expert"], "failed_breakout_reversal")
        self.assertLess(D(plan["take_profit_2"]), D(plan["take_profit_1"]))
        self.assertLess(D(plan["take_profit_1"]), D(plan["entry"]))
        self.assertGreater(D(plan["stop_loss"]), D(plan["entry"]))


if __name__ == "__main__":
    unittest.main()
