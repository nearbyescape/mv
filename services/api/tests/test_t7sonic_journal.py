"""Phase 2S: synthetic offline journal persistence; never uses real exchange data."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest

from app.research.t7sonic_forward_protocol import (
    START_MS, STEP_MS, make_synthetic_precommit,
)
from app.research.t7sonic_forward_coverage import make_synthetic_gap
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_journal import OfflineSyntheticJournal, JOURNAL_STATUS


def synthetic_watch(t, previous=None, prev_t=None):
    reports = [{"symbol": s, "watch_hypotheses": []} for s in MARKETS]
    features = {s: sha256(s.encode()).hexdigest() for s in MARKETS}
    return make_synthetic_precommit(
        boundary_ms=t, receipt_ms=t + 1000,
        market_reports=reports, feature_source_hashes=features,
        previous_sha256=previous or ("0" * 64),
        previous_boundary_ms=prev_t,
    )


def synthetic_gap(t, previous, prev_t):
    return make_synthetic_gap(
        boundary_ms=t, recorded_ms=t + 65000,
        missing_reasons={"ETHUSDT": "SOURCE_STALE"},
        previous_sha256=previous, previous_boundary_ms=prev_t,
    )


class OfflineJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="t7sonic-journal-synthetic-")
        self.path = Path(self.temp.name) / "records.jsonl"

    def tearDown(self):
        self.temp.cleanup()

    def test_append_recover_append_preserves_all_six_markets_and_gaps(self):
        one = synthetic_watch(START_MS)
        two = synthetic_gap(START_MS+STEP_MS, one["batch_sha256"], START_MS)
        three = synthetic_watch(START_MS+STEP_MS*2, two["batch_sha256"],
                                START_MS+STEP_MS)
        with OfflineSyntheticJournal(self.path) as journal:
            first = journal.append(one)
            self.assertEqual(first["records"], 1)
            second = journal.append(two)
            self.assertEqual(second["watch_cycles"], 1)
            self.assertEqual(second["gap_cycles"], 1)
            self.assertFalse(second["external_time_witness"])
            self.assertEqual(second["status"], JOURNAL_STATUS)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with OfflineSyntheticJournal(self.path) as journal:
            self.assertEqual(journal.summary()["records"], 2)
            third = journal.append(three)
            self.assertEqual(third["records"], 3)
            self.assertEqual(third["gap_cycles"], 1)
            self.assertEqual(third["watch_cycles"], 2)
            self.assertEqual(third["last_sha256"], three["batch_sha256"])
        records = [json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len(records), 3)
        self.assertEqual(records[1]["status"],
                         "SYNTHETIC_GAP_NEVER_TREAT_AS_NO_WATCH")
        self.assertEqual(len(records[0]["observations"]), 6)

    def test_duplicate_out_of_order_and_skipped_interval_fail_closed(self):
        one = synthetic_watch(START_MS)
        two = synthetic_watch(START_MS + STEP_MS, one["batch_sha256"], START_MS)
        three = synthetic_watch(START_MS + 2*STEP_MS, two["batch_sha256"],
                                START_MS+STEP_MS)
        with OfflineSyntheticJournal(self.path) as journal:
            journal.append(one)
            with self.assertRaises(ValueError):
                journal.append(one)
            with self.assertRaises(ValueError):
                journal.append(three)
            journal.append(two)
        with OfflineSyntheticJournal(self.path) as journal:
            self.assertEqual(journal.summary()["records"], 2)
            self.assertEqual(journal.summary()["last_sha256"], two["batch_sha256"])

    def test_torn_final_json_line_blocks_recovery_without_mutation(self):
        one = synthetic_watch(START_MS)
        with OfflineSyntheticJournal(self.path) as journal:
            journal.append(one)
        with self.path.open("ab") as f:
            f.write(b'{"unfinished":')
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "torn"):
            with OfflineSyntheticJournal(self.path):
                pass
        self.assertEqual(self.path.read_bytes(), before)

    def test_altered_content_rejected_even_when_valid_json(self):
        one = synthetic_watch(START_MS)
        with OfflineSyntheticJournal(self.path) as journal:
            journal.append(one)
        data = json.loads(self.path.read_text())
        data["observations"][0]["candidate_active"] = True
        self.path.write_text(json.dumps(
            data, sort_keys=True, separators=(",", ":")
        ) + "\n")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Tampered"):
            with OfflineSyntheticJournal(self.path):
                pass
        self.assertEqual(self.path.read_bytes(), before)

    def test_reject_symlink_hardlink_insecure_permissions_and_no_lock(self):
        other = Path(self.temp.name) / "other.jsonl"
        other.write_bytes(b"")
        link = Path(self.temp.name) / "link.jsonl"
        link.symlink_to(other)
        with self.assertRaises(ValueError):
            with OfflineSyntheticJournal(link):
                pass
        hard = Path(self.temp.name) / "hard.jsonl"
        os.link(other, hard)
        with self.assertRaises(ValueError):
            with OfflineSyntheticJournal(hard):
                pass
        other.chmod(0o644)
        with self.assertRaises(ValueError):
            with OfflineSyntheticJournal(other):
                pass
        with OfflineSyntheticJournal(self.path) as j:
            with self.assertRaises(BlockingIOError):
                with OfflineSyntheticJournal(self.path):
                    pass

    def test_cannot_append_after_close_and_private_directory_required(self):
        one = synthetic_watch(START_MS)
        j = OfflineSyntheticJournal(self.path)
        with self.assertRaises(RuntimeError):
            j.append(one)
        with j:
            j.append(one)
        with self.assertRaises(RuntimeError):
            j.append(one)
        wide = Path(self.temp.name) / "shared"
        wide.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            with OfflineSyntheticJournal(wide / "bad.jsonl"):
                pass


if __name__ == "__main__":
    unittest.main()
