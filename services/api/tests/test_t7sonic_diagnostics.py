"""Deterministic post-label T7Sonic per-expert diagnostics (not a trading model)."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from app.research.t7sonic_diagnostics import (
    summarize_attribution,
)
from app.research.t7sonic_diagnostics_cli import verified_diagnostics
from app.research.t7sonic_outcomes import research_outcomes
from test_t7sonic_history import (
    _month_zip, _write_source, SYMBOL, HISTORICAL_FRAMES,
)


class T7SonicDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="t7sonic-diag-month-")
        cls.root=Path(cls.temp.name)
        for frame in HISTORICAL_FRAMES:
            _write_source(cls.root,frame,_month_zip(frame))
        cls.base=research_outcomes(
            cls.root,(SYMBOL,),"2026-04-20",maximum=12,
            include_episode_records=True
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_counts_reconcile_across_all_exclusive_partitions(self):
        r=summarize_attribution(self.base)
        self.assertEqual(r["directional_episodes"],
                         self.base["directional_grouping"]["directional_episodes"])
        self.assertEqual(r["decision_stream_sha256"],self.base["decision_stream_sha256"])
        self.assertEqual(r["label_stream_sha256"],self.base["label_stream_sha256"])
        self.assertTrue(r["nominal_episode_count_is_not_independent_sample_size"])
        for horizon in ("15","30","60","120"):
            for k in ("by_direction","by_onset_consensus","by_utc_half_day"):
                partition=r[k][horizon]
                self.assertEqual(sum(x["episode_count"] for x in partition.values()),
                                 r["directional_episodes"])
                self.assertEqual(sum(x["favorable"] for x in partition.values()),
                                 self.base["horizon_labels"][horizon]["favorable_above_10bps"])
                self.assertEqual(sum(x["adverse"] for x in partition.values()),
                                 self.base["horizon_labels"][horizon]["adverse_below_minus_10bps"])

    def test_same_episode_may_be_attributed_to_multiple_onset_experts(self):
        r=summarize_attribution(self.base)
        horizon=r["by_onset_expert"]["60"]
        participating=r["by_ever_participating_expert"]["60"]
        self.assertTrue(all(
            x["episode_count"]<=r["directional_episodes"] for x in horizon.values()
        ))
        for expert in horizon:
            self.assertGreaterEqual(participating[expert]["episode_count"],
                                    horizon[expert]["episode_count"])
        # No sum is used to infer distinct independent expert proposals.

    def test_digest_mismatch_never_silently_summarized(self):
        r=deepcopy(self.base)
        if r["directional_episode_labels"]:
            record=r["directional_episode_labels"][0]
            record["direction"]="SHORT" if record["direction"]=="LONG" else "LONG"
            with self.assertRaisesRegex(ValueError,"digest mismatch"):
                summarize_attribution(r)

    def test_missing_records_and_fabricated_trading_permission_refused(self):
        missing=deepcopy(self.base)
        del missing["directional_episode_labels"]
        with self.assertRaisesRegex(ValueError,"include-episode-records"):
            summarize_attribution(missing)
        r=deepcopy(self.base)
        r["actionable_signals"]=1
        with self.assertRaisesRegex(ValueError,"nontrading"):
            summarize_attribution(r)
        r=deepcopy(self.base)
        r["scope"]="INDEPENDENT_UNTOUCHED_HOLDOUT"
        with self.assertRaisesRegex(ValueError,"holdout"):
            summarize_attribution(r)

    def test_verification_requires_both_pinned_shas_and_matches_episode_counts(self):
        x=verified_diagnostics(
            self.root,(SYMBOL,),"2026-04-20",
            self.base["decision_stream_sha256"],
            self.base["label_stream_sha256"],maximum=12
        )
        self.assertTrue(x["verified_existing_decision_and_label_shas"])
        self.assertEqual(x["original_expert_activations"],
                         self.base["expert_activation_episodes"])
        self.assertEqual(x["directional_episodes"],
                         self.base["directional_grouping"]["directional_episodes"])
        with self.assertRaisesRegex(ValueError,"decision stream differs"):
            verified_diagnostics(
                self.root,(SYMBOL,),"2026-04-20",
                "0"*64,self.base["label_stream_sha256"],maximum=12
            )
        with self.assertRaisesRegex(ValueError,"label stream differs"):
            verified_diagnostics(
                self.root,(SYMBOL,),"2026-04-20",
                self.base["decision_stream_sha256"],"0"*64,maximum=12
            )

    def test_mean_and_zero_count_strata(self):
        report=summarize_attribution(self.base)
        for horizon in ("15","30","60","120"):
            for r in report["by_onset_expert"][horizon].values():
                if r["episode_count"]==0:
                    self.assertIsNone(r["mean_signed_mark_bps"])
                else:
                    self.assertIsInstance(D(r["mean_signed_mark_bps"]),D)


if __name__=="__main__":
    unittest.main()
