"""Phase 2M validation contract only; test must not access exchange archives."""
from __future__ import annotations

from hashlib import sha256
import json
import unittest

from app.research.t7sonic_validation_plan import frozen_plan


class ValidationPlanTests(unittest.TestCase):
    def test_frozen_market_universe_and_chronology(self):
        p = frozen_plan()
        self.assertEqual(p["action"], "PLAN_ONLY_NO_ARCHIVE_ACCESS")
        self.assertEqual(p["start_day_utc"], "2026-06-12")
        self.assertEqual(p["end_day_utc"], "2026-08-25")
        self.assertEqual(p["utc_calendar_days"], 75)
        self.assertEqual(p["market_days"], 450)
        self.assertEqual(len(p["markets"]), 6)
        self.assertIn("BNBUSDT", p["markets"])
        self.assertEqual(p["monthly_source_pairs_required"], 72)
        self.assertEqual(p["source_months"], ["2026-06", "2026-07", "2026-08"])

    def test_source_and_candidate_rules_are_frozen(self):
        p = frozen_plan()
        self.assertEqual(p["candidate_expert"], "failed_breakout_reversal")
        self.assertEqual(p["immutable_model_source_revision"],
                         "384d08906a8cf9b0ed3e471ee126af680b90fc71")
        self.assertEqual(p["primary_horizon_minutes"], 60)
        self.assertEqual(p["strict_favorable_threshold_bps"], 10)
        self.assertEqual(p["strict_adverse_threshold_bps"], -10)
        self.assertEqual(p["baselines"], ["MATCHED_ALWAYS_LONG", "MATCHED_ALWAYS_SHORT"])
        self.assertEqual(p["secondary_horizons_minutes"], [15, 30, 120])
        self.assertEqual(p["paired_comparison_policy"],
                         "ALL_EXPERT_ONSETS_INCLUDING_NEUTRAL")

    def test_uncertainty_and_failure_gates_are_not_optional(self):
        p = frozen_plan()
        uncertainty = p["uncertainty"]
        self.assertEqual(uncertainty["chronological_moving_block_days"], 7)
        self.assertEqual(uncertainty["bootstrap_resamples"], 10000)
        self.assertEqual(uncertainty["bootstrap_seed"], 20261011)
        gate = p["directional_research_gate"]
        self.assertTrue(gate["require_positive_vs_both_baselines"])
        self.assertTrue(gate["require_both_bootstrap_95pct_lower_bounds_positive"])
        self.assertEqual(gate["monthly_groups_positive_vs_both_required"], 2)
        self.assertEqual(gate["markets_positive_vs_both_required"], 4)

    def test_zero_data_access_and_no_trade_authorization(self):
        p = frozen_plan()
        self.assertEqual(p["archive_files_opened"], 0)
        self.assertEqual(p["validation_market_records_read"], 0)
        self.assertEqual(p["historical_result_labels_computed"], 0)
        self.assertFalse(p["training_performed"])
        self.assertFalse(p["signals_published"])
        self.assertFalse(p["orders_sent"])
        self.assertFalse(p["production_mutation"])
        self.assertEqual(len(p["not_before_data_access"]), 5)

    def test_fingerprint_covers_every_contract_field(self):
        p = frozen_plan()
        digest = p.pop("frozen_plan_sha256")
        payload = json.dumps(p, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(sha256(payload).hexdigest(), digest)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(frozen_plan()["frozen_plan_sha256"], digest)


if __name__ == "__main__":
    unittest.main()
