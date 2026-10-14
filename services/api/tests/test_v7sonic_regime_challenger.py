"""Standalone V7 challenger tests. Synthetic inputs; never network or Telegram."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
import unittest

from test_t7sonic_perception import fixture
from test_t7sonic_release_candidate import breakout, quote
from app.research.t7sonic_release_candidate import indicative_plan
from app.research.t7sonic_regime_challenger import (
    POLICY, NOT_FOR_CLIENTS, propose_paper_challenger,
    research_hypotheses,
)
from app.research.t7sonic_perception import perceive_symbol


class RegimeChallengerTests(unittest.TestCase):
    def test_reference_breakout_stays_nonpublishable_even_if_qualifying(self):
        snapshot = breakout()
        q = quote()
        frozen = indicative_plan(deepcopy(snapshot), deepcopy(q))
        report = propose_paper_challenger(snapshot, q)
        self.assertEqual(frozen, indicative_plan(snapshot, q))
        self.assertEqual(report["policy"], POLICY)
        self.assertEqual(report["symbol"], "BTCUSDT")
        self.assertEqual(report["status"], NOT_FOR_CLIENTS)
        self.assertFalse(report["publishable_signal"])
        self.assertFalse(report["client_publication_authorized"])
        self.assertFalse(report["executable_order"])
        self.assertFalse(report["accuracy_established"])
        self.assertFalse(report["venue_execution_or_fills_verified"])
        self.assertEqual(report["reference_exit_split"], "50/50")
        entry = D(report["entry"])
        stop = D(report["stop_loss"])
        tp1 = D(report["take_profit_1"])
        tp2 = D(report["take_profit_2"])
        self.assertLess(stop, entry)
        self.assertLess(entry, tp1)
        self.assertLess(tp1, tp2)
        self.assertGreaterEqual(D(report["weighted_exit_net_r_if_filled"]), D("1.25"))
        self.assertEqual(report, propose_paper_challenger(
            deepcopy(snapshot), deepcopy(q)))

    def test_new_trend_reentry_family_uses_completed_candles(self):
        snapshot = fixture()
        snapshot["bars"]["5m"][-1]["close"] = "102.85"
        q = quote(bid="102.84", ask="102.85")
        hyps = research_hypotheses(perceive_symbol(snapshot))
        self.assertIn(
            {"expert": "trend_pullback_reentry", "direction": "LONG"},
            hyps,
        )
        report = propose_paper_challenger(snapshot, q)
        self.assertEqual(report["status"], NOT_FOR_CLIENTS)
        self.assertEqual(report["expert"], "trend_pullback_reentry")
        self.assertEqual(report["direction"], "LONG")

    def test_locked_symbol_cannot_qualify(self):
        result = propose_paper_challenger(
            breakout(), quote(), active_symbols=("BTCUSDT",),
        )
        self.assertEqual(result["reason"], "ACTIVE_SYMBOL_LOCK")
        self.assertFalse(result["publishable_signal"])

    def test_malformed_market_evidence_fails_closed(self):
        cases = [
            (breakout(), quote(observed=True)),
            (breakout(), quote(observed=0)),
            (breakout(), quote(bid="102", ask="104")),
            (breakout(), quote(symbol="ETHUSDT")),
        ]
        bad = breakout()
        bad["bars"]["5m"][-1]["close"] = "NaN"
        cases.append((bad, quote()))
        bad = breakout()
        bad["bars"]["5m"][-1]["open_ms"] += 300_000
        cases.append((bad, quote()))
        for snapshot, q in cases:
            with self.subTest(q=q), self.assertRaises(ValueError):
                propose_paper_challenger(snapshot, q)

    def test_stale_or_missing_15m_cannot_generate_challenger(self):
        snapshot = breakout()
        del snapshot["bars"]["15m"][-1]
        with self.assertRaises(ValueError):
            propose_paper_challenger(snapshot, quote())
        snapshot = breakout()
        snapshot["as_of_ms"] += 300_000
        with self.assertRaises(ValueError):
            propose_paper_challenger(
                snapshot,
                quote(boundary=snapshot["as_of_ms"]),
            )

    def test_no_duplicate_or_invalid_portfolio_lock(self):
        for value in (
            ["BTCUSDT"], ("BTCUSDT", "BTCUSDT"), ("DOGEUSDT", "DOGEUSDT"),
            ("NOTAMARKET",),
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                propose_paper_challenger(
                    breakout(), quote(), active_symbols=value,
                )

    def test_short_plan_geometry_is_valid_or_fail_closed(self):
        snapshot = fixture()
        m5 = snapshot["bars"]["5m"][-1]
        m5.update({
            "high": "104.00", "low": "102.00",
            "open": "103.00", "close": "102.50",
            "volume": "130",
        })
        m1 = snapshot["bars"]["1m"][-1]
        m1.update({
            "open": "102.90", "high": "103.15",
            "low": "102.40", "close": "102.50",
        })
        result = propose_paper_challenger(
            snapshot, quote(bid="102.49", ask="102.50"),
        )
        self.assertFalse(result["publishable_signal"])
        self.assertFalse(result["executable_order"])
        if result["status"] == NOT_FOR_CLIENTS:
            self.assertEqual(result["direction"], "SHORT")
            self.assertLess(D(result["take_profit_2"]), D(result["take_profit_1"]))
            self.assertLess(D(result["take_profit_1"]), D(result["entry"]))
            self.assertLess(D(result["entry"]), D(result["stop_loss"]))
        else:
            self.assertEqual(result["status"], "NO_RESEARCH_CANDIDATE")


if __name__ == "__main__":
    unittest.main()
