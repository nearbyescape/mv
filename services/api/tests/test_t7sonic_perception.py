"""T7Sonic Phase 1: causal market perception and watch-only specialist safety."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import unittest

from app.research.t7sonic_cli import run_offline_snapshot
from app.research.t7sonic_experts import (
    EXPERT_NAMES, RESEARCH_ONLY_STATUS, classify_market,
    discover_hypotheses, research_market,
)
from app.research.t7sonic_perception import (
    INTERVAL_MS, breadth_context, perceive_symbol,
)


AS_OF = int(datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)


def fixture(symbol="BTCUSDT", as_of=AS_OF, length=55):
    streams={}
    for name, interval in INTERVAL_MS.items():
        end=(as_of // interval)*interval
        data=[]
        for i in range(length):
            opening=Decimal("100")+Decimal(i)*Decimal("0.05")
            closing=opening+Decimal("0.03")
            data.append({
                "open_ms":end-(length-i)*interval,
                "open":str(opening),
                "high":str(closing+Decimal(".25")),
                "low":str(opening-Decimal(".25")),
                "close":str(closing),
                "volume":"100",
            })
        streams[name]=data
    return {"symbol":symbol,"as_of_ms":as_of,"bars":streams}


class TestT7SonicResearchFoundation(unittest.TestCase):

    def test_deterministic_five_timeframe_perception(self):
        sample=fixture()
        p=perceive_symbol(sample)
        self.assertEqual(p["symbol"],"BTCUSDT")
        self.assertEqual(set(p["frames"]),set(INTERVAL_MS))
        self.assertEqual(p["as_of_ms"],AS_OF)
        self.assertEqual(len(p["feature_source_sha256"]),64)
        self.assertEqual(p,perceive_symbol(deepcopy(sample)))
        self.assertFalse(p["prediction_probabilities_available"])
        for f in p["frames"].values():
            self.assertLessEqual(f["last_completed_boundary_ms"],AS_OF)

    def test_all_five_frames_are_required(self):
        sample=fixture()
        del sample["bars"]["4h"]
        with self.assertRaisesRegex(ValueError,"five"):
            perceive_symbol(sample)

    def test_incomplete_candle_causes_fail_closed(self):
        sample=fixture()
        sample["as_of_ms"]=AS_OF-1
        with self.assertRaisesRegex(ValueError,"Lookahead"):
            perceive_symbol(sample)

    def test_stale_snapshot_causes_fail_closed(self):
        sample=fixture()
        sample["as_of_ms"]=AS_OF+60_000
        with self.assertRaisesRegex(ValueError,"Stale"):
            perceive_symbol(sample)

    def test_missing_bar_and_duplicate_rejected(self):
        sample=fixture()
        del sample["bars"]["15m"][21]
        with self.assertRaisesRegex(ValueError,"Gap"):
            perceive_symbol(sample)
        sample=fixture()
        sample["bars"]["5m"][19]["open_ms"]=sample["bars"]["5m"][18]["open_ms"]
        with self.assertRaisesRegex(ValueError,"duplicate"):
            perceive_symbol(sample)

    def test_invalid_ohlcv_and_malformed_source_rejected(self):
        sample=fixture()
        sample["bars"]["1m"][-1]["low"]="999999"
        with self.assertRaisesRegex(ValueError,"geometry"):
            perceive_symbol(sample)
        sample=fixture()
        sample["bars"]["1m"][-1]["volume"]="-1"
        with self.assertRaisesRegex(ValueError,"negative"):
            perceive_symbol(sample)
        sample=fixture()
        sample["bars"]["1m"][-1]["close"]="NaN"
        with self.assertRaisesRegex(ValueError,"Nonfinite"):
            perceive_symbol(sample)
        sample=fixture()
        sample["outcome_from_future"]="GREAT_PROFIT"
        with self.assertRaisesRegex(ValueError,"contract mismatch"):
            perceive_symbol(sample)

    def test_regime_and_trend_expert_find_positive_context(self):
        perception=perceive_symbol(fixture())
        state=classify_market(perception)
        self.assertEqual(state["primary"],"TREND_UP")
        proposals=discover_hypotheses(perception)
        self.assertTrue(any(
            h["expert"]=="trend_continuation" and h["direction"]=="LONG"
            for h in proposals
        ))
        for p in proposals:
            self.assertIn(p["expert"],EXPERT_NAMES)
            self.assertEqual(p["status"],RESEARCH_ONLY_STATUS)
            self.assertIsNone(p["win_probability"])
            self.assertIsNone(p["entry_price"])
            self.assertIsNone(p["stop_loss"])
            self.assertIsNone(p["expected_net_r"])
            self.assertFalse(p["publishable_signal"])
            self.assertFalse(p["executable_order"])

    def test_breakout_expert_does_not_need_v4_hourly_trigger(self):
        sample=fixture()
        bars=sample["bars"]["5m"]
        last=bars[-1]
        last["close"]="103.10"
        last["high"]="103.50"
        last["low"]="102.20"
        last["volume"]="300"
        perception=perceive_symbol(sample)
        proposals=discover_hypotheses(perception)
        self.assertTrue(any(
            h["expert"]=="breakout" and h["direction"]=="LONG"
            for h in proposals
        ))

    def test_breadth_requires_matching_asof_and_no_duplicate_markets(self):
        btc=perceive_symbol(fixture())
        eth=perceive_symbol(fixture("ETHUSDT"))
        context=breadth_context([btc,eth])
        self.assertEqual(context["markets_observed"],2)
        self.assertFalse(context["full_universe_complete"])
        self.assertEqual(context["symbols"],["BTCUSDT","ETHUSDT"])
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            breadth_context([btc,deepcopy(btc)])
        wrong=deepcopy(eth)
        wrong["as_of_ms"]=AS_OF+60_000
        with self.assertRaisesRegex(ValueError,"as_of mismatch"):
            breadth_context([btc,wrong])

    def test_readonly_runner_reports_watch_hypotheses_not_signals(self):
        payload={"schema":1,"snapshots":[fixture(),fixture("ETHUSDT")]}
        before=deepcopy(payload)
        report=run_offline_snapshot(payload)
        self.assertEqual(payload,before)
        self.assertEqual(report["engine"],"T7Sonic")
        self.assertEqual(report["market_count"],2)
        self.assertGreater(report["watch_hypothesis_count"],0)
        self.assertEqual(report["actionable_signal_count"],0)
        self.assertFalse(report["evidence"]["deployment_permission"])
        self.assertFalse(report["evidence"]["live_market_data_access"])
        self.assertEqual(report["probability_model_status"],"NOT_TRAINED")
        self.assertEqual(report,json.loads(json.dumps(report)))

    def test_contradictory_or_unavailable_market_data_never_generates_action(self):
        sample=fixture()
        sample["bars"]["4h"][-1]["open_ms"]+=INTERVAL_MS["4h"]
        with self.assertRaises(ValueError):
            run_offline_snapshot({"schema":1,"snapshots":[sample]})
        self.assertEqual(research_market([perceive_symbol(fixture())])[
            "actionable_signal_count"],0)

    def test_explicit_bounded_universe_and_schema(self):
        with self.assertRaisesRegex(ValueError,"1–30"):
            run_offline_snapshot({"schema":1,"snapshots":[]})
        with self.assertRaisesRegex(ValueError,"1–30"):
            run_offline_snapshot({"schema":1,"snapshots":[fixture()]*31})
        with self.assertRaisesRegex(ValueError,"schema"):
            run_offline_snapshot({"schema":2,"snapshots":[fixture()]})
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            run_offline_snapshot({"schema":1,"snapshots":[fixture(),fixture()]})
        with self.assertRaisesRegex(ValueError,"unexpected|Unexpected"):
            perceive_symbol(fixture("BOGUS"))


if __name__=="__main__":
    unittest.main()
