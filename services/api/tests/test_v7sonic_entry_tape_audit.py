"""Offline audit of the operator's twelve exact public trade-tape bodies.

All source calls mocked. The auditor opens no networks, and preserves
original evidence even when tampering is detected.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.v7sonic_entry_tape_audit import audit_saved_entry_tape
from services.t7sonic import entry_tape_capture_worker as worker
from services.t7sonic.entry_tape_reference import BOUNDARY, WINDOW_END
from test_v7sonic_entry_tape import EntryTapeTests, CANDIDATES


class EntryTapeForensicAuditTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v7-tape-forensic-")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        fixture = EntryTapeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.out = self.folder
        self.fake = fixture
        fixture.request_urls.clear()
        self.source = {
            "status": "V7_SIX_MARKET_ORIGINAL_SOURCE_AND_LEDGER_READONLY_AUDIT_PASS",
            "candidates": [dict(x) for x in CANDIDATES],
            "decision_paper_journal_inserted_ms_local_unattested": BOUNDARY + 2000,
        }
        with patch.object(worker, "audit_one_stored_cycle", return_value=self.source):
            worker.capture_entry_tape(
                "/unmounted-original", str(self.folder),
                public_network_approved=True,
                paper_only_acknowledged=True,
                getter=fixture.getter,
                clock_ms=lambda:WINDOW_END+60000,
            )

    def audit(self):
        with patch(
            "app.v7sonic_entry_tape_audit.audit_one_stored_cycle",
            return_value=self.source,
        ):
            return audit_saved_entry_tape("/unmounted-original", self.folder)

    def test_exact_12_saved_raw_http_bodies_replay_all_print_counts(self):
        report = self.audit()
        self.assertEqual(report["tape_original_body_count_reverified"], 12)
        self.assertEqual(report["status"],
            "ORIGINAL_12_RESPONSE_30S_TAPE_REPLAY_AUDIT_PASS_NO_FILLS")
        self.assertEqual(len(report["replayed_observations"]), 2)
        self.assertFalse(report["client_publication_authorized"])
        self.assertEqual(report["entry_fills_verified"], 0)
        self.assertEqual(report["orders_submitted"], 0)
        self.assertEqual(
            sha256((self.folder /
                f"v7sonic-entry-tape-report-{BOUNDARY}.json").read_bytes()).hexdigest(),
            report["saved_tape_report_sha256"],
        )

    def test_modified_original_http_envelope_rejected(self):
        p = self.folder / f"v7sonic-entry-tape-original-{BOUNDARY}-SOLUSDT-0.json"
        data = json.loads(p.read_text())
        data["original_body_sha256"] = "0" * 64
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.audit()

    def test_changed_original_url_rejected(self):
        p = self.folder / f"v7sonic-entry-tape-original-{BOUNDARY}-SOLUSDT-4.json"
        data = json.loads(p.read_text())
        data["url"] = "https://fapi.binance.com/fapi/v1/aggTrades?symbol=BTCUSDT"
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "provenance mismatch"):
            self.audit()

    def test_tampered_report_reference_results_rejected(self):
        p = self.folder / f"v7sonic-entry-tape-report-{BOUNDARY}.json"
        data = json.loads(p.read_text())
        data["observations"][0]["any_post_journal_trade_price_at_or_above_entry"] = False
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "differ from saved sources"):
            self.audit()

    def test_missing_original_envelope_is_a_hard_failure(self):
        (self.folder /
            f"v7sonic-entry-tape-original-{BOUNDARY}-DOGEUSDT-5.json").unlink()
        with self.assertRaises(PermissionError):
            self.audit()

    def test_an_incomplete_marker_blocks_apparent_success(self):
        (self.folder / f"v7sonic-entry-tape-incomplete-{BOUNDARY}.json").write_text(
            '{"status":"INCOMPLETE_OR_INVALID_ENTRY_TAPE_NO_CONCLUSION"}'
        )
        with self.assertRaisesRegex(ValueError, "INCOMPLETE"):
            self.audit()

    def test_claimed_journal_time_must_equal_original_source(self):
        p = self.folder / f"v7sonic-entry-tape-claim-{BOUNDARY}.json"
        data = json.loads(p.read_text())
        data["recorded_paper_decision_ms_local_unattested"] += 1000
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "journal"):
            self.audit()

    def test_symlinked_original_source_is_not_trusted(self):
        p = self.folder / f"v7sonic-entry-tape-original-{BOUNDARY}-SOLUSDT-1.json"
        target = self.folder / "untrusted-original.json"
        target.write_bytes(p.read_bytes())
        p.unlink()
        p.symlink_to(target)
        with self.assertRaises(PermissionError):
            self.audit()
