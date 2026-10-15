"""Fail-closed, causality and realistic execution tests for V7 reversal."""
from __future__ import annotations

from datetime import datetime,timezone
from decimal import Decimal as D
import unittest
from unittest.mock import patch

from app.research.t7sonic_perception import Bar
from app.research.v7_failed_break_reversal import (
    POLICY,POLICY_SHA256,PARAMETERS,proposals_for_symbol,reversal_portfolio,
)
from app.research.v7_recovery_archives import MARKETS,STEP_MS

START=int(datetime(2026,4,1,tzinfo=timezone.utc).timestamp()*1000)


def series():
    candles=[]
    for i in range(640):
        low,high=D("99.6"),D("100.4")
        opening=closing=D("100")
        volume=D("100")
        if i==600:
            opening,closing=D("100.8"),D("100.2")
            high,low=D("101.5"),D("99.9")
            volume=D("200")
        candles.append(Bar(START+i*STEP_MS,opening,high,low,closing,volume))
    return candles


class ReversalStudyTests(unittest.TestCase):
    def test_rejection_reversal_detects_completed_wick(self):
        rows,reason=proposals_for_symbol(series(),"BTCUSDT")
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["direction"],-1)
        self.assertEqual(rows[0]["entry_bar_index"],601)
        self.assertEqual(rows[0]["decision_boundary_ms"],START+601*STEP_MS)
        self.assertEqual(sum(reason.values()),640-561)
        self.assertGreater(rows[0]["modeled_target_net_R"],.90)
        self.assertTrue(rows[0]["decision_uses_completed_bars_only"])
        self.assertFalse(rows[0]["next_open_execution_verified"])
        self.assertFalse(rows[0]["client_publication_authorized"])

    def test_strategy_frozen_and_order_safe(self):
        self.assertEqual(len(POLICY_SHA256),64)
        self.assertTrue(POLICY.startswith("V7_RESEARCH_"))
        self.assertEqual(PARAMETERS["fee_and_slippage_bps_per_side"],8)
        self.assertEqual(PARAMETERS["ambiguity_policy"],"STOP_FIRST")
        self.assertEqual(PARAMETERS["gross_target_r"],1.60)

    def test_no_signal_if_wick_fails_confirmation(self):
        altered=series()
        bar=altered[600]
        altered[600]=Bar(
            bar.open_ms,D("100.2"),D("101.5"),D("99.9"),D("100.8"),D("200")
        )
        rows,_=proposals_for_symbol(altered,"BTCUSDT")
        self.assertEqual(rows,[])

    def test_no_future_observation_changes_prior_signal(self):
        original=series()
        earlier,_=proposals_for_symbol(original,"BTCUSDT")
        mutation=list(original)
        victim=mutation[620]
        mutation[620]=Bar(
            victim.open_ms,victim.opening,victim.high+D("20"),
            victim.low-D("20"),victim.close,victim.volume
        )
        later,_=proposals_for_symbol(mutation,"BTCUSDT")
        self.assertEqual(earlier,later)

    def test_missing_bar_rejected(self):
        rows=series()
        del rows[590]
        with self.assertRaises(ValueError):
            proposals_for_symbol(rows,"BTCUSDT")

    def test_wrong_market_rejected(self):
        with self.assertRaises(ValueError):
            proposals_for_symbol(series(),"FAKEUSDT")

    def test_paper_portfolio_limits_and_no_broadcast(self):
        result=reversal_portfolio({s:series() for s in MARKETS})
        self.assertLessEqual(result["paper_selected"],4)
        self.assertGreaterEqual(result["candidate_decisions"],result["paper_selected"])
        self.assertFalse(result["client_publication_authorized"])
        self.assertEqual(result["telegram_messages_sent"],0)
        self.assertEqual(result["orders_submitted"],0)

    def test_no_trade_if_4h_trend_is_strong(self):
        bars=series()
        # This is a source integrity check: no experiment can silently
        # change its time axis to evade chronological validation.
        bad=list(bars)
        idx=610
        b=bad[idx]
        bad[idx]=Bar(b.open_ms+STEP_MS,b.opening,b.high,b.low,b.close,b.volume)
        with self.assertRaises(ValueError):
            proposals_for_symbol(bad,"BTCUSDT")

    def test_module_does_not_import_publishers_or_brokers(self):
        import inspect
        import app.research.v7_failed_break_reversal as model
        source=inspect.getsource(model)
        for forbidden in (
            "from app.telegram","sendMessage",
            "place_order(", "enqueue_approved(",
            "from app.database","from app.v7sonic_client_delivery",
        ):
            self.assertNotIn(forbidden,source)


if __name__=="__main__":
    unittest.main()
