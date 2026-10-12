"""Mock-only private dry-run outbox: no Telegram API or production writes."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from services.t7sonic.forward_paper_ledger import PrivatePaperLedger
from services.t7sonic.forward_private_outbox import PaperTestOutbox
from test_t7sonic_forward_paper_ledger import paper_preview

TEST_CHAT = "-1001111111111"
CLIENT_CHAT = "-1002222222222"


class PrivateTestOutboxTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory(prefix="v7sonic-private-outbox-")
        self.path = Path(self.directory.name) / "v7sonic-paper-simulated.sqlite3"
        self.batch = paper_preview()
        self.boundary = self.batch["decision_boundary_ms"]

    def tearDown(self):
        self.directory.cleanup()

    def open(self):
        return PrivatePaperLedger(
            self.path, local_write_approved=True
        )

    def queue(self, db):
        db.record(self.batch, observed_at_ms=self.boundary+1000)
        adapter = PaperTestOutbox(
            db, private_test_chat_id=TEST_CHAT,
            production_chat_id=CLIENT_CHAT,
        )
        return adapter

    def test_all_six_test_messages_prepared_once_no_telegram_sender(self):
        with self.open() as db:
            box=self.queue(db)
            prep=box.prepare(self.batch,now_ms=self.boundary+2000)
            self.assertEqual(prep["newly_prepared"],6)
            self.assertEqual(prep["telegram_messages_sent"],0)
            self.assertFalse(prep["real_telegram_request_implemented"])
            second=box.prepare(self.batch,now_ms=self.boundary+3000)
            self.assertEqual(second["newly_prepared"],0)
            state=box.counts()
            self.assertEqual(state["by_state"]["PREPARED_SIMULATION_ONLY"],6)
            self.assertEqual(state["production_client_messages_sent"],0)
            msgs=db.db.execute("SELECT text FROM private_test_outbox").fetchall()
            self.assertEqual(len(msgs),6)
            self.assertTrue(all(
                "DO NOT TRADE" in t[0] and
                "Not authorized for client publication" in t[0]
                for t in msgs
            ))

    def test_mock_ack_is_clearly_not_real_telegram_delivery(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+2000)
            identity=self.batch["indicative_candidates"][0]["candidate_id"]
            reserved=box.claim_simulated_attempt(
                identity,now_ms=self.boundary+3000
            )
            self.assertEqual(
                reserved["status"],"SIMULATED_ATTEMPT_RESERVED_NO_NETWORK"
            )
            self.assertEqual(reserved["messages_sent"],0)
            with self.assertRaises(PermissionError):
                box.claim_simulated_attempt(
                    identity,now_ms=self.boundary+3001
                )
            fake=box.mark_simulated_ack(
                identity,now_ms=self.boundary+4000,
                simulated_message_id="FAKE-123",
            )
            self.assertEqual(fake["status"],"SIMULATED_ACK_NOT_SENT")
            self.assertEqual(fake["telegram_messages_sent"],0)
            with self.assertRaises(PermissionError):
                box.mark_simulated_ack(
                    identity,now_ms=self.boundary+4001,
                    simulated_message_id="FAKE-999",
                )

    def test_unknown_outcome_stays_blocked_forever_even_after_reopen(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+2000)
            identity=self.batch["indicative_candidates"][0]["candidate_id"]
            box.claim_simulated_attempt(identity,now_ms=self.boundary+3000)
            box.block_ambiguous(identity,now_ms=self.boundary+3100)
            self.assertEqual(
                box.counts()["by_state"]["AMBIGUOUS_BLOCKED_NO_RETRY"],1
            )
        with self.open() as db:
            box=PaperTestOutbox(db,private_test_chat_id=TEST_CHAT,
                                production_chat_id=CLIENT_CHAT)
            self.assertEqual(box.fail_closed_after_restart(
                now_ms=self.boundary+5000
            ),0)
            with self.assertRaises(PermissionError):
                box.claim_simulated_attempt(
                    identity,now_ms=self.boundary+5000
                )
            self.assertEqual(
                box.prepare(self.batch,now_ms=self.boundary+5000)["newly_prepared"],0
            )

    def test_restart_orphaned_attempt_becomes_ambiguous_no_auto_retry(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+1000)
            identity=self.batch["indicative_candidates"][0]["candidate_id"]
            box.claim_simulated_attempt(
                identity,now_ms=self.boundary+2000
            )
        with self.open() as db:
            box=PaperTestOutbox(db,private_test_chat_id=TEST_CHAT,
                                production_chat_id=CLIENT_CHAT)
            self.assertEqual(
                box.fail_closed_after_restart(now_ms=self.boundary+3000),1
            )
            self.assertEqual(
                box.counts()["by_state"]["AMBIGUOUS_BLOCKED_NO_RETRY"],1
            )
            with self.assertRaises(PermissionError):
                box.claim_simulated_attempt(
                    identity,now_ms=self.boundary+3001
                )

    def test_production_chat_identity_and_missing_production_identity_denied(self):
        with self.open() as db:
            for test, prod in (
                (TEST_CHAT,TEST_CHAT), ("",CLIENT_CHAT),
                (TEST_CHAT,""), ("user",CLIENT_CHAT),
                ("-1001","-1001"), (TEST_CHAT,None),
            ):
                with self.subTest(test=test,prod=prod), self.assertRaises(PermissionError):
                    PaperTestOutbox(
                        db,private_test_chat_id=test,
                        production_chat_id=prod,
                    )

    def test_changed_destination_cannot_requeue_existing_candidate(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+1000)
            other=PaperTestOutbox(
                db,private_test_chat_id="-1003333333333",
                production_chat_id=CLIENT_CHAT
            )
            with self.assertRaises(ValueError):
                other.prepare(self.batch,now_ms=self.boundary+2000)
            self.assertEqual(
                box.counts()["by_state"]["PREPARED_SIMULATION_ONLY"],6
            )

    def test_missing_source_cycle_forged_client_or_missing_persistence_fails(self):
        with self.open() as db:
            box=PaperTestOutbox(
                db,private_test_chat_id=TEST_CHAT,
                production_chat_id=CLIENT_CHAT
            )
            with self.assertRaises(ValueError):
                box.prepare(self.batch,now_ms=self.boundary+1000)
            db.record(self.batch,observed_at_ms=self.boundary+1000)
            for key,val in (
                ("client_publication_authorized",True),
                ("telegram_enqueued",True),
                ("candidate_count",7),
            ):
                altered=deepcopy(self.batch)
                altered[key]=val
                with self.subTest(key=key),self.assertRaises(ValueError):
                    box.prepare(altered,now_ms=self.boundary+1000)
            self.assertEqual(
                box.counts()["by_state"].get("PREPARED_SIMULATION_ONLY",0),0
            )

    def test_expired_unsent_never_recreated(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+1000)
            identity=self.batch["indicative_candidates"][0]["candidate_id"]
            expired=self.batch["indicative_candidates"][0]["expires_at_ms"]
            with self.assertRaisesRegex(ValueError,"expired"):
                box.claim_simulated_attempt(identity,now_ms=expired)
            self.assertEqual(
                box.counts()["by_state"]["EXPIRED_UNSENT"],1
            )
            with self.assertRaises(PermissionError):
                box.claim_simulated_attempt(identity,now_ms=expired+1)
            self.assertEqual(
                box.counts()["by_state"].get("SIMULATED_ACK_NOT_SENT",0),0
            )

    def test_non_fake_ack_refused(self):
        with self.open() as db:
            box=self.queue(db)
            box.prepare(self.batch,now_ms=self.boundary+1000)
            identity=self.batch["indicative_candidates"][0]["candidate_id"]
            box.claim_simulated_attempt(identity,now_ms=self.boundary+2000)
            for invalid in ("12345","", "FAKE-../../etc", "FAKE-"+"a"*100):
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                    box.mark_simulated_ack(
                        identity,now_ms=self.boundary+2500,
                        simulated_message_id=invalid
                    )
            self.assertEqual(
                box.counts()["by_state"]["SIMULATED_ATTEMPT_RESERVED"],1
            )


if __name__ == "__main__":
    unittest.main()
