"""T7Sonic multi-day evidence-integrity and matched-baseline regressions."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from app.research.t7sonic_multiday import analyze, FAV, ADV, NEU


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _episode(day: str, direction: str, move: int, expert: str) -> dict:
    label = FAV if move > 10 else ADV if move < -10 else NEU
    return {
        "id": f"BTCUSDT:{direction}:{day}",
        "symbol": "BTCUSDT", "direction": direction,
        "experts_at_onset": [expert], "horizons_minutes": {
            h: {"signed_mark_move_bps": str(move), "classification": label}
            for h in ("15", "30", "60", "120")
        },
    }


def _report(day: str, direction: str, move: int) -> dict:
    episode = _episode(day, direction, move, "failed_breakout_reversal")
    raw = json.dumps(episode, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    state = FAV if move > 10 else ADV if move < -10 else NEU
    rollups = {
        h: {
            "episode_labels": 1, "favorable_above_10bps": int(state == FAV),
            "adverse_below_minus_10bps": int(state == ADV),
            "neutral_within_10bps": int(state == NEU),
        } for h in ("15", "30", "60", "120")
    }
    return {
        "schema": 1, "engine": "T7Sonic", "day": day,
        "symbols": ["BTCUSDT"],
        "scope": "INSPECTED_APRIL_MAY_DEVELOPMENT_ONLY",
        "status": "RETROSPECTIVE_DEVELOPMENT_DIRECTIONAL_MARK_PROXY_NOT_TRADES",
        "completed_five_minute_decision_boundaries": 288,
        "actionable_signals": 0, "trading_wins_claimed": False,
        "quotes_slippage_fees_funding_modeled": False,
        "all_episode_labels_derived_after_decisions_frozen": True,
        "decision_stream_sha256": "c" * 64,
        "label_stream_sha256": _hash(raw),
        "directional_grouping": {"directional_episodes": 1},
        "directional_episode_labels": [episode],
        "horizon_labels": rollups,
    }


class MultiDayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="t7sonic-multiday-")
        self.root = Path(self.temp.name)
        self.reports = {
            "2026-04-19": _report("2026-04-19", "LONG", 15),
            "2026-04-20": _report("2026-04-20", "SHORT", -20),
        }
        self._write()

    def tearDown(self):
        self.temp.cleanup()

    def _write(self):
        rows = []
        for day, report in sorted(self.reports.items()):
            filename = day + ".json"
            data = json.dumps(report, sort_keys=True, indent=2).encode()
            (self.root / filename).write_bytes(data)
            rows.append(f"{_hash(data)}  {self.root / filename}\n")
        data = b"synthetic descriptive summary\n"
        (self.root / "summary.txt").write_bytes(data)
        rows.append(f"{_hash(data)}  {self.root / 'summary.txt'}\n")
        ledger = "".join(rows).encode()
        (self.root / "SHA256SUMS").write_bytes(ledger)
        self.ledger_sha = _hash(ledger)
        self.anchor_sha = self.reports["2026-04-20"]["label_stream_sha256"]

    def _run(self):
        return analyze(
            self.root, "2026-04-19", 2, self.ledger_sha, "c" * 64,
            self.anchor_sha,
        )

    def test_matched_baselines_are_same_episode_times(self):
        r = self._run()
        self.assertEqual(r["actual_watch_direction"]["favorable"], 1)
        self.assertEqual(r["actual_watch_direction"]["adverse"], 1)
        self.assertEqual(r["matched_always_long_on_same_watch_onsets"]["favorable"], 2)
        self.assertEqual(r["matched_always_short_on_same_watch_onsets"]["adverse"], 2)
        self.assertEqual(r["by_expert_at_onset"]["failed_breakout_reversal"]["active_days"], 2)
        self.assertTrue(r["april_20_anchor_verified"])

    def test_paired_expert_baselines_account_for_each_onset(self):
        report = self._run()
        paired = report["paired_onsets"]
        self.assertEqual(paired["actual"]["favorable"], 1)
        self.assertEqual(paired["matched_long"]["favorable"], 2)
        self.assertEqual(paired["matched_short"]["favorable"], 0)
        self.assertEqual(
            paired["vs_matched_long"]["net_favorable_episodes_actual_minus_baseline"], -1
        )
        self.assertEqual(paired["vs_matched_long"]["baseline_only_favorable"], 1)
        self.assertEqual(paired["vs_matched_long"]["actual_only_favorable"], 0)
        self.assertEqual(
            paired["vs_matched_short"]["net_favorable_episodes_actual_minus_baseline"], 1
        )
        expert = report["by_expert_paired_matched_baselines"]["failed_breakout_reversal"]
        self.assertEqual(expert["active_days"], 2)
        self.assertEqual(expert["active_days_worse_than_matched_long"], 1)
        self.assertEqual(expert["active_days_tied_with_matched_long"], 1)
        self.assertEqual(expert["active_days_better_than_matched_short"], 1)
        self.assertEqual(expert["active_days_tied_with_matched_short"], 1)
        self.assertEqual(sum(day["episodes"] for day in expert["daily"].values()), 2)

    def test_coactivated_experts_share_cohort_but_not_total_episodes(self):
        first = self.reports["2026-04-19"]
        first["directional_episode_labels"][0]["experts_at_onset"] = [
            "failed_breakout_reversal", "volatility_transition"
        ]
        entry = first["directional_episode_labels"][0]
        raw = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        first["label_stream_sha256"] = _hash(raw)
        self._write()
        report = self._run()
        self.assertEqual(report["actual_watch_direction"]["episodes"], 2)
        self.assertEqual(
            report["by_expert_paired_matched_baselines"]["volatility_transition"]["actual"]["episodes"], 1
        )
        self.assertEqual(
            report["by_expert_paired_matched_baselines"]["failed_breakout_reversal"]["actual"]["episodes"], 2
        )

    def test_report_byte_tampering_rejected(self):
        path = self.root / "2026-04-19.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Evidence member differs"):
            self._run()

    def test_ledger_tampering_rejected(self):
        with (self.root / "SHA256SUMS").open("ab") as stream:
            stream.write(b"anything\n")
        with self.assertRaisesRegex(ValueError, "ledger digest mismatch"):
            self._run()

    def test_matching_ledger_does_not_bypass_label_hash(self):
        self.reports["2026-04-19"]["directional_episode_labels"][0][
            "horizons_minutes"]["60"]["signed_mark_move_bps"] = "-15"
        self._write()
        with self.assertRaisesRegex(ValueError, "label-stream SHA mismatch"):
            self._run()

    def test_original_anchor_rejected_if_changed(self):
        self.anchor_sha = "a" * 64
        with self.assertRaisesRegex(ValueError, "April 20 original frozen"):
            self._run()

    def test_horizon_rollups_required_even_with_valid_hashes(self):
        self.reports["2026-04-19"]["horizon_labels"]["60"][
            "favorable_above_10bps"] = 0
        self._write()
        with self.assertRaisesRegex(ValueError, "Horizon rollup mismatch"):
            self._run()

    def test_nontrading_scope_immutable(self):
        self.reports["2026-04-19"]["actionable_signals"] = 1
        self._write()
        with self.assertRaisesRegex(ValueError, "nontrading report"):
            self._run()

    def test_reject_missing_and_extra_days(self):
        (self.root / "2026-04-20.json").unlink()
        with self.assertRaisesRegex(ValueError, "Unexpected or missing"):
            self._run()


if __name__ == "__main__":
    unittest.main()
