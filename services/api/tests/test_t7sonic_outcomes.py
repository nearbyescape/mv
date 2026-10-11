"""Synthetic-only outcome labeling tests; these are NOT performance evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from app.research.t7sonic_perception import Bar
from app.research.t7sonic_outcomes import (
    HORIZONS, cluster_directional_episodes, label_directional_episode,
    _pinned_future_minutes, research_outcomes,
)
from app.research.t7sonic_replay import replay_day
from test_t7sonic_history import (
    _month_zip, _write_source, SYMBOL, HISTORICAL_FRAMES,
)

STEP=300_000
UTC=lambda day: int(datetime.fromisoformat(day).replace(
    tzinfo=timezone.utc).timestamp()*1000)


class T7SonicOutcomesTests(unittest.TestCase):

    def test_dedup_same_direction_two_experts_and_consecutive_boundaries(self):
        t=UTC("2026-04-20T00:05:00")
        events=[
            {"boundary_ms":t,"active_watch_keys":[
                [SYMBOL,"breakout","LONG"],[SYMBOL,"participation","LONG"]]},
            {"boundary_ms":t+STEP,"active_watch_keys":[
                [SYMBOL,"participation","LONG"]]},
            {"boundary_ms":t+2*STEP,"active_watch_keys":[]},
            {"boundary_ms":t+3*STEP,"active_watch_keys":[
                [SYMBOL,"trend_continuation","SHORT"],
                [SYMBOL,"failed_breakout_reversal","LONG"]]},
        ]
        episodes,summary=cluster_directional_episodes(events)
        self.assertEqual(len(episodes),3)
        self.assertEqual(summary["directional_episodes"],3)
        self.assertEqual(summary["multi_expert_symbol_side_boundaries"],1)
        self.assertEqual(summary["opposing_side_symbol_boundaries"],1)
        self.assertEqual(summary["by_direction"],{"LONG":2,"SHORT":1})
        self.assertEqual(episodes[0]["active_consecutive_5m_boundaries"],2)
        self.assertEqual(episodes[0]["participating_experts"],[
            "breakout","participation"
        ])
        self.assertEqual(episodes[0]["experts_at_onset"],[
            "breakout","participation"
        ])
        self.assertEqual(episodes[0]["first_decision_boundary_ms"],t)
        with self.assertRaisesRegex(ValueError,"contiguous"):
            cluster_directional_episodes(events[:1]+events[2:])

    def test_forward_price_only_for_labels(self):
        t=UTC("2026-04-20T00:05:00")
        episode={
            "id":f"{SYMBOL}:LONG:{t}","symbol":SYMBOL,"direction":"LONG",
            "first_decision_boundary_ms":t,"last_active_boundary_ms":t,
            "active_consecutive_5m_boundaries":1,
            "experts_at_onset":["breakout"],
            "participating_experts":["breakout","participation"]
        }
        future={}
        for n in range(120):
            v=D("100") if n<14 else D("101")
            future[t+n*60_000]=Bar(t+n*60_000,D("100"),max(D("100"),v),
                                   D("99.8"),v,D("50"))
        label=label_directional_episode(episode,future)
        self.assertEqual(label["proxy_entry_price"],"100")
        self.assertEqual(label["horizons_minutes"]["15"]["classification"],
                         "FAVORABLE_ABOVE_10BPS")
        self.assertEqual(label["horizons_minutes"]["120"]["classification"],
                         "FAVORABLE_ABOVE_10BPS")
        self.assertEqual(D(label["horizons_minutes"]["15"]["signed_mark_move_bps"]),D("100"))
        self.assertTrue("NOT_EXECUTABLE_FILL" in label["proxy_entry_type"])
        short=dict(episode,direction="SHORT")
        self.assertEqual(label_directional_episode(short,future)[
            "horizons_minutes"]["15"]["classification"],"ADVERSE_BELOW_MINUS_10BPS")
        with self.assertRaisesRegex(ValueError,"Missing future minute"):
            label_directional_episode(episode,{k:v for k,v in future.items() if k!=t+5*60_000})

    def test_exact_10bps_is_neutral_not_selected_as_win(self):
        t=UTC("2026-04-20T00:05:00")
        ep={"id":"x","symbol":SYMBOL,"direction":"LONG",
            "first_decision_boundary_ms":t,"last_active_boundary_ms":t,
            "active_consecutive_5m_boundaries":1,
            "experts_at_onset":[],"participating_experts":[]}
        forward={}
        for n in range(120):
            forward[t+n*60_000]=Bar(
                t+n*60_000,D("100"),D("100.1"),D("100"),D("100.1"),D("1"))
        self.assertEqual(
            label_directional_episode(ep,forward)["horizons_minutes"]["15"]["classification"],
            "NEUTRAL_WITHIN_10BPS"
        )

    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="t7sonic-outcome-calendar-")
        cls.root=Path(cls.temp.name)
        for frame in HISTORICAL_FRAMES:
            _write_source(cls.root,frame,_month_zip(frame))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_replay_digest_identical_before_and_after_labeling(self):
        preview=replay_day(self.root,(SYMBOL,),"2026-04-20",maximum=12)
        detailed=replay_day(self.root,(SYMBOL,),"2026-04-20",maximum=12,
                            include_decision_events=True)
        events=detailed.pop("decision_events")
        self.assertEqual(detailed,preview)
        self.assertEqual(len(events),12)
        outcome=research_outcomes(self.root,(SYMBOL,),"2026-04-20",
                                  maximum=12,include_episode_records=True)
        self.assertEqual(outcome["decision_stream_sha256"],
                         preview["candidate_stream_sha256"])
        self.assertEqual(outcome["expert_activation_episodes"],
                         preview["new_watch_activation_episodes"])
        self.assertEqual(outcome["watch_observations_repeated_same_setups"],
                         preview["watch_observations_repeated_same_setups"])
        self.assertEqual(outcome["actionable_signals"],0)
        self.assertFalse(outcome["trading_wins_claimed"])
        self.assertFalse(outcome["quotes_slippage_fees_funding_modeled"])
        self.assertTrue(outcome["all_episode_labels_derived_after_decisions_frozen"])
        grouped=outcome["directional_grouping"]["directional_episodes"]
        self.assertEqual(len(outcome["directional_episode_labels"]),grouped)
        self.assertEqual(len(outcome["label_stream_sha256"]),64)
        for h in HORIZONS:
            self.assertEqual(outcome["horizon_labels"][str(h)]["episode_labels"],grouped)
        outcome2=research_outcomes(self.root,(SYMBOL,),"2026-04-20",
                                   maximum=12,include_episode_records=False)
        self.assertEqual(outcome2["decision_stream_sha256"],
                         outcome["decision_stream_sha256"])
        self.assertEqual(outcome2["label_stream_sha256"],
                         outcome["label_stream_sha256"])
        self.assertNotIn("directional_episode_labels",outcome2)

    def test_missing_future_month_fails_instead_of_censoring_loss(self):
        first=UTC("2026-04-30T23:55:00")
        nextmonth=UTC("2026-05-01T02:00:00")
        with self.assertRaises(FileNotFoundError):
            _pinned_future_minutes(self.root,SYMBOL,first,nextmonth)

    def test_missing_source_file_fails_closed(self):
        path=self.root/"archives"/SYMBOL/"1m"/f"{SYMBOL}-1m-2026-04.zip"
        backup=path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                research_outcomes(self.root,(SYMBOL,),"2026-04-20",maximum=12)
        finally:
            path.write_bytes(backup)


if __name__=="__main__":
    unittest.main()
