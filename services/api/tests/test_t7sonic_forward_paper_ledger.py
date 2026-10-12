"""V7Sonic persisted paper journal tests, zero network, production DB untouched."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app.research.t7sonic_release_preview import build_offline_preview
from services.t7sonic.forward_paper_ledger import (
    PrivatePaperLedger, validate_internal_batch,
)
from test_t7sonic_release_preview import group


def paper_preview():
    return build_offline_preview(*group())


class PrivateLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="v7sonic-paper-only-")
        self.dbpath = Path(self.temp.name)/"v7sonic-paper-trial.sqlite3"
        self.preview = paper_preview()
        self.boundary = self.preview["decision_boundary_ms"]

    def tearDown(self):
        self.temp.cleanup()

    def test_durable_all_six_market_decisions_after_restart(self):
        with self.assertRaises(PermissionError):
            PrivatePaperLedger(self.dbpath)
        with PrivatePaperLedger(
            self.dbpath, local_write_approved=True
        ) as ledger:
            result = ledger.record(
                self.preview, observed_at_ms=self.boundary+1_000
            )
            self.assertEqual(result["status"], "SIX_MARKET_CYCLE_STORED")
            self.assertEqual(result["six_decisions_accounted_for"], 6)
            self.assertEqual(result["candidate_count"], 6)
            self.assertFalse(result["telegram_or_client_delivery"])
            self.assertFalse(result["off_vps_storage_verified"])
            self.assertEqual(ledger.audit(self.boundary)["candidate_count"], 6)
        with PrivatePaperLedger(
            self.dbpath, local_write_approved=True
        ) as reopened:
            self.assertTrue(reopened.audit(self.boundary)["six_decisions_verified"])
            count = reopened.db.execute(
                "SELECT count(*) FROM paper_decisions"
            ).fetchone()[0]
            self.assertEqual(count, 6)

    def test_exact_replay_idempotent_mutated_same_boundary_rejected(self):
        with PrivatePaperLedger(
            self.dbpath, local_write_approved=True
        ) as ledger:
            first = ledger.record(
                self.preview, observed_at_ms=self.boundary+1_000
            )
            replay = ledger.record(
                self.preview, observed_at_ms=self.boundary+2_000
            )
            self.assertEqual(replay["status"], "EXACT_REPLAY_NO_MUTATION")
            self.assertEqual(replay["batch_sha256"], first["batch_sha256"])
            original, quotes = group()
            quotes[0]["ask"] = "103.11"
            alternative = build_offline_preview(original, quotes)
            self.assertNotEqual(
                alternative["batch_sha256"], self.preview["batch_sha256"]
            )
            with self.assertRaises(ValueError):
                ledger.record(
                    alternative, observed_at_ms=self.boundary+1_001
                )
            self.assertEqual(
                ledger.db.execute(
                    "SELECT count(*) FROM paper_cycles"
                ).fetchone()[0],1
            )

    def test_expiration_is_internal_status_not_publication(self):
        with PrivatePaperLedger(self.dbpath,local_write_approved=True) as ledger:
            ledger.record(self.preview, observed_at_ms=self.boundary+500)
            expire_at = self.preview["indicative_candidates"][0]["expires_at_ms"]
            self.assertEqual(ledger.expire(now_ms=expire_at-1), 0)
            self.assertEqual(ledger.expire(now_ms=expire_at), 6)
            self.assertEqual(ledger.expire(now_ms=expire_at+1000), 0)
            statuses = {
                x[0] for x in ledger.db.execute(
                    "SELECT lifecycle FROM paper_decisions"
                )
            }
            self.assertEqual(statuses,{"EXPIRED_UNSENT"})
            self.assertFalse(ledger.audit(self.boundary)["client_publication_authorized"])

    def test_no_setup_recorded_distinct_from_missing_data(self):
        samples, quotes = group()
        preview = build_offline_preview(
            samples, quotes, active_symbols=("BTCUSDT",)
        )
        self.assertEqual(preview["candidate_count"],5)
        with PrivatePaperLedger(self.dbpath,local_write_approved=True) as ledger:
            with self.assertRaisesRegex(ValueError, "Missing decision batch"):
                ledger.audit(self.boundary)
            ledger.record(preview,observed_at_ms=self.boundary+1000)
            self.assertEqual(
                ledger.db.execute(
                    "SELECT lifecycle FROM paper_decisions WHERE symbol='BTCUSDT'"
                ).fetchone()[0],"NO_SETUP"
            )
            self.assertEqual(ledger.audit(self.boundary)["candidate_count"],5)

    def test_tampered_or_partial_batch_fails_without_writes(self):
        failed = [
            ("markets_evaluated", 5),
            ("batch_sha256", "f"*64),
            ("telegram_enqueued", True),
            ("client_publication_authorized", True),
            ("real_money_orders_authorized", True),
            ("candidate_count", 7),
            ("decision_records", self.preview["decision_records"][:-1]),
        ]
        with PrivatePaperLedger(self.dbpath,local_write_approved=True) as ledger:
            for key, value in failed:
                candidate = deepcopy(self.preview)
                candidate[key] = value
                with self.subTest(key=key),self.assertRaises(ValueError):
                    ledger.record(candidate,observed_at_ms=self.boundary+1000)
            alter = deepcopy(self.preview)
            alter["decision_records"][0]["entry"] = "0.01"
            with self.assertRaises(ValueError):
                ledger.record(alter,observed_at_ms=self.boundary+1000)
            alter = deepcopy(self.preview)
            alter["indicative_candidates"][0]["entry"] = "0.01"
            with self.assertRaises(ValueError):
                ledger.record(alter,observed_at_ms=self.boundary+1000)
            self.assertEqual(
                ledger.db.execute("SELECT count(*) FROM paper_cycles").fetchone()[0],0
            )
            self.assertEqual(
                ledger.db.execute("SELECT count(*) FROM paper_decisions").fetchone()[0],0
            )

    def test_outside_cutoff_rejected_without_state_change(self):
        with PrivatePaperLedger(self.dbpath,local_write_approved=True) as ledger:
            for observed in (
                self.boundary-1,self.boundary+60_001,
                True, "untrusted",
            ):
                with self.subTest(observed=observed),self.assertRaises(ValueError):
                    ledger.record(self.preview, observed_at_ms=observed)
            self.assertEqual(
                ledger.db.execute("SELECT count(*) FROM paper_cycles").fetchone()[0],0
            )

    def test_storage_path_is_private_cannot_use_production_paths(self):
        with self.assertRaises(ValueError):
            PrivatePaperLedger(
                Path(self.temp.name)/"mv-production.db",
                local_write_approved=True
            )
        link = Path(self.temp.name)/"v7sonic-paper-link.sqlite3"
        target=Path(self.temp.name)/"v7sonic-paper-real.sqlite3"
        target.write_bytes(b"")
        link.symlink_to(target)
        with self.assertRaises(ValueError):
            PrivatePaperLedger(link,local_write_approved=True)
        with tempfile.TemporaryDirectory() as directory:
            open_parent=Path(directory)
            open_parent.chmod(0o755)
            with self.assertRaises(PermissionError):
                PrivatePaperLedger(
                    open_parent/"v7sonic-paper-test.sqlite3",
                    local_write_approved=True,
                )

    def test_audit_detects_mutated_disk_plan_without_republishing(self):
        with PrivatePaperLedger(self.dbpath,local_write_approved=True) as ledger:
            ledger.record(self.preview, observed_at_ms=self.boundary+1000)
            ledger.db.execute(
                "UPDATE paper_decisions SET body_json='{}' WHERE symbol='BTCUSDT'"
            )
            with self.assertRaises(ValueError):
                ledger.audit(self.boundary)
            self.assertEqual(
                ledger.db.execute(
                    "SELECT count(*) FROM paper_decisions"
                ).fetchone()[0],6
            )


if __name__ == "__main__":
    unittest.main()
