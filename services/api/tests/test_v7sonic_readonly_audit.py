"""Source-of-truth V7 offline ledger audit (zero real network or client send)."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import v7sonic_release as release
from app.v7sonic_readonly_audit import audit_one_stored_cycle
from test_v7sonic_release_capture_worker import ReleaseRunnerTests
from test_t7sonic_forward_release_bridge import BOUNDARY


class ReadonlyForensicTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v7-audit-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        fake = ReleaseRunnerTests()
        fake.setUp()
        with patch.object(release, "_ist_open", return_value=True):
            self.original = fake.run_case(self.folder)

    def kwargs(self):
        return {
            "boundary_ms": BOUNDARY,
            "summary_sha256": self.original["receipt_sha256"],
            "original_sha256": self.original["original_http_sha256"],
            "batch_sha256": self.original["paper_batch_sha256"],
        }

    def test_source_31_sha_and_all_six_paper_decisions_report_original_candidates(self):
        result = audit_one_stored_cycle(self.folder, **self.kwargs())
        self.assertEqual(
            result["status"],
            "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS",
        )
        self.assertEqual(result["original_http_responses_verified"], 31)
        self.assertEqual(result["markets_verified"], 6)
        self.assertEqual(len(result["candidates"]), self.original["candidate_count"])
        self.assertEqual(len(result["noncandidates"]), 6 - self.original["candidate_count"])
        self.assertTrue(result["historical_only_do_not_trade"])
        self.assertFalse(result["local_source_independently_authenticated"])
        self.assertEqual(result["clients_notified"], 0)
        self.assertEqual(result["orders_submitted"], 0)
        with sqlite3.connect(self.folder / "v7sonic-paper-release.sqlite3") as db:
            stored = db.execute(
                "SELECT body_json FROM paper_cycles WHERE decision_boundary_ms=?",
                (BOUNDARY,),
            ).fetchone()
        plans = json.loads(stored[0])["indicative_candidates"]
        self.assertEqual(
            [(p["symbol"], p["entry"], p["stop_loss"],
              p["take_profit_1"], p["take_profit_2"])
             for p in result["candidates"]],
            [(p["symbol"], p["entry"], p["stop_loss"],
              p["take_profit_1"], p["take_profit_2"])
             for p in plans],
        )

    def test_changed_summary_sha_is_rejected_before_decisions_displayed(self):
        receipt = self.folder / f"v7sonic-private-paper-cycle-{BOUNDARY}.json"
        receipt.write_bytes(receipt.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "summary SHA256"):
            audit_one_stored_cycle(self.folder, **self.kwargs())

    def test_changed_original_source_is_rejected_before_decisions_displayed(self):
        summary = json.loads(Path(self.original["receipt_path"]).read_text())
        source_path = Path(summary["source_attempts"][-1]["original_http_file"])
        source_path.write_bytes(source_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "source SHA256"):
            audit_one_stored_cycle(self.folder, **self.kwargs())

    def test_corrupted_sql_decision_is_refused(self):
        dbfile = self.folder / "v7sonic-paper-release.sqlite3"
        with sqlite3.connect(dbfile) as db:
            db.execute(
                "UPDATE paper_decisions SET status='WRONG' "
                "WHERE decision_boundary_ms=? AND symbol='BTCUSDT'",
                (BOUNDARY,),
            )
        with self.assertRaisesRegex(ValueError, "per-market decision tampered"):
            audit_one_stored_cycle(self.folder, **self.kwargs())

    def test_nonexistent_source_or_different_digest_is_refused(self):
        options = self.kwargs()
        options["original_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "private receipt"):
            audit_one_stored_cycle(self.folder, **options)

    def test_no_ledger_ever_created_by_read_only_audit(self):
        dbfile = self.folder / "v7sonic-paper-release.sqlite3"
        dbfile.unlink()
        with self.assertRaisesRegex(PermissionError, "paper ledger"):
            audit_one_stored_cycle(self.folder, **self.kwargs())
        self.assertFalse(dbfile.exists())


if __name__ == "__main__":
    import unittest
    unittest.main()
