"""Final V7 breakout safety/causality tests — never market or Telegram network."""
from __future__ import annotations

from decimal import Decimal as D
from datetime import datetime, timezone
from pathlib import Path
import json
import math
import tempfile
import unittest
from unittest.mock import patch

from app.research.t7sonic_perception import Bar
from app.research.v7_recovery_archives import STEP_MS, MONTHS, MARKETS
from app.research.v7_final_breakout import (
    POLICY, POLICY_SHA256, RULES, STARTUP_BARS_15M, _reference_decisions,
    _score_reference, _four_hour, breakout_portfolio,
)
from app.research.v7_recovery_engine import PriceBar, _validate_bars


FIRST=int(datetime(2026,4,1,tzinfo=timezone.utc).timestamp()*1000)


def breakout_fixture(n=960, breakout_index=600):
    """Trend/wicks/volume, a single distinct completed price breakout."""
    output=[]
    previous=D("100")
    for i in range(n):
        move=D("0.10")
        if i == breakout_index:
            move=D("1.25")
        opening=previous
        close=opening+move
        volume=D("500") if i == breakout_index else D("100")
        output.append(Bar(
            FIRST+i*STEP_MS,
            opening,
            max(opening,close)+D("0.30"),
            min(opening,close)-D("0.30"),
            close,volume,
        ))
        previous=close
    return output


class BreakoutContractTests(unittest.TestCase):
    def test_deterministic_valid_reference_and_safe_policy(self):
        bars=breakout_fixture()
        records, reason=_reference_decisions(bars,"BTCUSDT")
        self.assertEqual(sum(reason.values()),len(bars)-STARTUP_BARS_15M-1)
        self.assertGreater(len(records),0,"Synthetic range breakout must be detected")
        self.assertEqual(len(POLICY_SHA256),64)
        self.assertEqual(RULES["fee_and_slippage_bps_per_side"],8)
        for item in records:
            self.assertEqual(item["policy"],POLICY)
            self.assertFalse(item["client_publication_authorized"])
            self.assertFalse(item["exchange_fills_verified"])
            self.assertFalse(item["data_at_decision_contains_future_bar"])
            self.assertGreaterEqual(item["modeled_target_net_R"],1.25)
            self.assertLess(item["stop"],item["entry"])
            self.assertGreater(item["target"],item["entry"])
        self.assertEqual(records,_reference_decisions(breakout_fixture(),"BTCUSDT")[0])

    def test_mutating_later_bar_does_not_change_earlier_decisions(self):
        src=breakout_fixture()
        before,_=_reference_decisions(src[:800],"BTCUSDT")
        other=list(src)
        victim=other[850]
        other[850]=Bar(
            victim.open_ms,victim.opening,victim.high+D("4"),
            victim.low,victim.close,victim.volume,
        )
        after,_=_reference_decisions(other,"BTCUSDT")
        self.assertEqual(
            before,
            [r for r in after if r["entry_bar_index"]<800]
        )

    def test_missing_bar_and_wrong_market_fail_closed(self):
        src=breakout_fixture()
        del src[700]
        with self.assertRaises(ValueError):
            _reference_decisions(src,"BTCUSDT")
        with self.assertRaises(ValueError):
            _reference_decisions(breakout_fixture(),"NOTUSDT")

    def test_hourly_regime_never_exposes_unfinished_4h_bar(self):
        src=_validate_bars(breakout_fixture())
        frames=_four_hour(src)
        for i in range(STARTUP_BARS_15M,len(src)-1):
            ix=(i+1)//16-1
            self.assertLessEqual(
                frames[ix].open_ms+16*STEP_MS,
                src[i].open_ms+STEP_MS
            )

    def test_adverse_stop_first_same_bar(self):
        src=[
            PriceBar(FIRST+i*STEP_MS,100,110,89,100,100)
            for i in range(40)
        ]
        idea={
            "symbol":"BTCUSDT",
            "entry_bar_index":1,
            "entry":100.0,
            "stop":95.0,
            "target":107.0,
            "direction":1,
            "risk_price":5.0,
            "decision_boundary_ms":FIRST+STEP_MS,
            "client_publication_authorized":False,
        }
        outcome=_score_reference(idea,src)
        self.assertEqual(outcome["outcome"],"AMBIGUOUS_STOP_FIRST")
        self.assertLess(outcome["net_R"],-1)
        self.assertFalse(outcome["actual_fill_verified"])
        self.assertEqual(outcome["orders_submitted"],0)

    def test_short_gap_through_stop_worse_than_planned(self):
        src=[PriceBar(FIRST+i*STEP_MS,110,112,96,101,100) for i in range(40)]
        idea={
            "symbol":"BTCUSDT","entry_bar_index":1,"entry":100.0,
            "stop":105.0,"target":90.0,
            "direction":-1,"risk_price":5.0,
            "decision_boundary_ms":FIRST+STEP_MS,
        }
        res=_score_reference(idea,src)
        self.assertEqual(res["exit"],110)
        self.assertLess(res["net_R"],-2)

    def test_last_incomplete_hold_is_censored(self):
        src=[PriceBar(FIRST+i*STEP_MS,100,101,99,100,100) for i in range(40)]
        idea={
            "symbol":"BTCUSDT","entry_bar_index":30,"entry":100.,
            "stop":95.,"target":110.,
            "direction":1,"risk_price":5.,
            "decision_boundary_ms":FIRST+30*STEP_MS,
        }
        result=_score_reference(idea,src)
        self.assertEqual(result["outcome"],"CENSORED")

    def test_portfolio_nosend_and_independent_strategies(self):
        source={s:breakout_fixture() for s in MARKETS}
        result=breakout_portfolio(source)
        self.assertEqual(result["reference_max_concurrent_slots"],4)
        self.assertFalse(result["client_publication_authorized"])
        self.assertFalse(result["exchange_fills_verified"])
        self.assertEqual(result["telegram_messages_sent"],0)
        self.assertEqual(result["orders_submitted"],0)
        self.assertLessEqual(result["selected_paper_references"],
                             result["proposals_before_portfolio_constraints"])

    def test_no_production_plugins_or_signers_imported(self):
        import inspect
        import app.research.v7_final_breakout as module
        code=inspect.getsource(module)
        for forbidden in (
            "from app.telegram", "import requests", "httpx.",
            "from app.database", "from app.v7sonic_client_delivery",
            "place_order(", "send_message(", "enqueue_approved(",
        ):
            self.assertNotIn(forbidden,code)

if __name__=="__main__":
    unittest.main()
