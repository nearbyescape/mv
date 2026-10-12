"""Offline V7 signed-client-delivery outbox acceptance tests.

No public network, production Telegram, or account keys. The fixture
manually certifies one synthetic six-market cycle to exercise this
separate release gate; the real paper worker never performs that step.
"""
from __future__ import annotations

import asyncio
import hmac
from hashlib import sha256
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app import v7sonic_client_delivery as outbox
from app.v7sonic_store import store_private_cycle
from test_v7sonic_store import report, BOUNDARY, ORIGINAL

SIGN_KEY = b"dev-fixture-only-" + b"k"*32
CHAT_ID = "-1003987000001"


class V7ClientOutboxTests(TestCase):
    def setUp(self):
        self.engine=create_engine(
            "sqlite://",connect_args={"check_same_thread":False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions=sessionmaker(self.engine,expire_on_commit=False)
        self.packet=report()
        self.candidate=self.packet["sealed_internal_paper_batch"]["indicative_candidates"][0]
        self.identity=self.candidate["candidate_id"]
        self.now=BOUNDARY+1800
        self.settings=SimpleNamespace(telegram_chat_id=CHAT_ID)
        with self.sessions.begin() as session:
            store_private_cycle(session,report=self.packet,
                                original_http_sha256=ORIGINAL,
                                recorded_at_ms=BOUNDARY+1000)

    def tearDown(self):
        self.engine.dispose()

    def authorize(self, *, certified=True, changed=None):
        candidate=self.candidate
        packet={
            "schema":1,"status":"V7_RELEASE_ELIGIBLE_REVIEWED",
            "candidate_id":self.identity,
            "decision_boundary_ms":BOUNDARY,
            "batch_sha256":self.packet["source_batch_sha256"],
            "destination_chat_id":CHAT_ID,
            "approved_at_ms":BOUNDARY+500,
            "expires_at_ms":candidate["expires_at_ms"],
            "release_operator_id":"test-human-reviewer",
            "risk_review_sha256":"d"*64,
            "portfolio_positions_independently_reviewed":True,
            "source_quality_reviewed":True,
            "client_publication_authorized":True,
            "orders_authorized":False,
        }
        if changed:
            packet.update(changed)
        signature=hmac.new(SIGN_KEY,outbox._canonical(packet),"sha256").hexdigest()
        with self.sessions.begin() as session:
            if certified:
                session.get(models.V7DecisionCycle,BOUNDARY).state="V7_RELEASE_CERTIFIED"
            session.add(models.V7ClientApproval(
                candidate_id=self.identity,decision_boundary_ms=BOUNDARY,
                batch_sha256=self.packet["source_batch_sha256"],
                destination_chat_id=CHAT_ID,
                approved_at_ms=BOUNDARY+500,
                expires_at_ms=candidate["expires_at_ms"],
                approval_json=packet,signature_hmac=signature,
                state="APPROVED",
            ))

    def stage(self, **kwargs):
        with patch.object(outbox, "_ist_open",return_value=True):
            with self.sessions.begin() as session:
                return outbox.enqueue_approved(
                    session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY,
                    client_release_enabled=True,**kwargs,
                )

    def test_unmodified_private_paper_candidate_never_stages_for_clients(self):
        with self.assertRaisesRegex(PermissionError,"global switch"):
            with self.sessions.begin() as session:
                outbox.enqueue_approved(session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY)
        with self.assertRaisesRegex(PermissionError,"No separate"):
            self.stage()
        self.authorize(certified=False)
        with self.assertRaisesRegex(PermissionError,"Uncertified"):
            self.stage()
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7ClientDelivery)
            ),0)
            self.assertEqual(session.get(
                models.V7DeliveryDraft,self.identity
            ).state,"BLOCKED_NOT_FOR_CLIENTS")

    def test_separate_signed_operator_approval_stages_exact_v7_two_target_payload(self):
        self.authorize()
        result=self.stage()
        self.assertEqual(result["status"],"V7_APPROVED_CLIENT_DELIVERY_STAGED")
        self.assertFalse(result["telegram_sent"])
        with self.sessions() as session:
            row=session.get(models.V7ClientDelivery,self.identity)
            self.assertEqual(row.status,"pending")
            self.assertEqual(row.attempts,0)
            self.assertIn("V7Sonic",row.payload_json["text"])
            self.assertIn("TP1 (50%)",row.payload_json["text"])
            self.assertIn("TP2 (50%)",row.payload_json["text"])
            self.assertNotIn("TP3",row.payload_json["text"])
            self.assertNotIn("DO NOT TRADE",row.payload_json["text"])
            self.assertEqual(row.destination_chat_id,CHAT_ID)
            self.assertEqual(self.stage()["status"],
                "EXACT_V7_DELIVERY_ALREADY_STAGED")

    def test_wrong_signing_key_wrong_chat_or_forged_release_rejected(self):
        self.authorize()
        with patch.object(outbox,"_ist_open",return_value=True):
            with self.sessions.begin() as session:
                with self.assertRaisesRegex(PermissionError,"signature"):
                    outbox.enqueue_approved(
                        session,self.identity,now_ms=self.now,
                        chat_id=CHAT_ID,signing_key=b"wrong"*8,
                        client_release_enabled=True
                    )
                with self.assertRaisesRegex(PermissionError,"destination"):
                    outbox.enqueue_approved(
                        session,self.identity,now_ms=self.now,
                        chat_id="-1003987000099",signing_key=SIGN_KEY,
                        client_release_enabled=True
                    )
        with self.sessions.begin() as session:
            approval=session.get(models.V7ClientApproval,self.identity)
            approval.approval_json={**approval.approval_json,
                "portfolio_positions_independently_reviewed":False}
        with self.assertRaisesRegex(PermissionError,"signature"):
            self.stage()

    def test_expiry_offsession_and_missing_risk_review_rejected(self):
        self.authorize(changed={"risk_review_sha256":"bad"})
        with self.assertRaisesRegex(PermissionError,"Complete signed"):
            self.stage()
        with self.sessions.begin() as session:
            approval=session.get(models.V7ClientApproval,self.identity)
            approval.approval_json={**approval.approval_json,
                "risk_review_sha256":"d"*64}
            approval.signature_hmac=hmac.new(
                SIGN_KEY,outbox._canonical(approval.approval_json),
                "sha256").hexdigest()
        with self.assertRaisesRegex(PermissionError,"expired"):
            with patch.object(outbox,"_ist_open",return_value=True):
                with self.sessions.begin() as session:
                    outbox.enqueue_approved(
                        session,self.identity,now_ms=BOUNDARY+30_100,
                        chat_id=CHAT_ID,signing_key=SIGN_KEY,
                        client_release_enabled=True
                    )
        with self.assertRaisesRegex(PermissionError,"expired"):
            with patch.object(outbox,"_ist_open",return_value=False):
                with self.sessions.begin() as session:
                    outbox.enqueue_approved(
                        session,self.identity,now_ms=self.now,
                        chat_id=CHAT_ID,signing_key=SIGN_KEY,
                        client_release_enabled=True
                    )

    def test_single_committed_claim_and_duplicate_claim_prevention(self):
        self.authorize()
        self.stage()
        with patch.object(outbox,"_ist_open",return_value=True):
            with self.sessions.begin() as session:
                item=outbox.claim_one(session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY,
                    client_release_enabled=True)
                self.assertEqual(item[0],self.identity)
            with self.sessions.begin() as session:
                self.assertIsNone(outbox.claim_one(
                    session,self.identity,now_ms=self.now,chat_id=CHAT_ID,
                    signing_key=SIGN_KEY,client_release_enabled=True
                ))
        with self.sessions() as session:
            self.assertEqual(session.get(
                models.V7ClientDelivery,self.identity
            ).attempts,1)

    def test_ambiguous_send_recovery_stays_unknown_without_retry(self):
        self.authorize()
        self.stage()
        with patch.object(outbox,"_ist_open",return_value=True):
            with self.sessions.begin() as session:
                outbox.claim_one(session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY,
                    client_release_enabled=True)
            with self.sessions.begin() as session:
                self.assertEqual(outbox.recover_interrupted(session),1)
            with self.sessions.begin() as session:
                self.assertIsNone(outbox.claim_one(
                    session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY,
                    client_release_enabled=True
                ))
        with self.sessions() as session:
            row=session.get(models.V7ClientDelivery,self.identity)
            self.assertEqual(row.status,"unknown")
            self.assertEqual(row.attempts,1)
            self.assertEqual(row.error_code,"INTERRUPTED_OR_UNCERTAIN")

    def test_delivery_rejects_mutated_pending_payload_before_network(self):
        self.authorize()
        self.stage()
        with self.sessions.begin() as session:
            row=session.get(models.V7ClientDelivery,self.identity)
            row.payload_json={**row.payload_json,"text":"forged"}
        with patch.object(outbox,"_ist_open",return_value=True):
            with self.sessions.begin() as session:
                self.assertIsNone(outbox.claim_one(
                    session,self.identity,now_ms=self.now,
                    chat_id=CHAT_ID,signing_key=SIGN_KEY,
                    client_release_enabled=True
                ))
        with self.sessions() as session:
            self.assertEqual(session.get(
                models.V7ClientDelivery,self.identity
            ).status,"skipped")

    def test_success_mock_telegram_send_receipt_and_no_second_post(self):
        self.authorize()
        self.stage()
        calls=[]
        async def fake_send(client,settings,payload):
            calls.append(payload)
            return 456
        async def run():
            with patch.object(outbox,"_ist_open",return_value=True):
                with patch.object(outbox,"send",new=fake_send):
                    first=await outbox.dispatch_once(
                        self.sessions,self.identity,now_ms=self.now,
                        settings=self.settings,signing_key=SIGN_KEY,
                        client_release_enabled=True,http_client=None)
                    second=await outbox.dispatch_once(
                        self.sessions,self.identity,now_ms=self.now,
                        settings=self.settings,signing_key=SIGN_KEY,
                        client_release_enabled=True,http_client=None)
            self.assertEqual(first["status"],"V7_DELIVERED")
            self.assertEqual(second["status"],"V7_NOT_DISPATCHED")
        asyncio.run(run())
        self.assertEqual(len(calls),1)
        with self.sessions() as session:
            row=session.get(models.V7ClientDelivery,self.identity)
            self.assertEqual(row.message_id,456)
            self.assertEqual(row.attempts,1)
            self.assertEqual(row.status,"delivered")
            self.assertEqual(session.get(
                models.V7DeliveryDraft,self.identity
            ).state,"BLOCKED_NOT_FOR_CLIENTS")

    def test_mock_telegram_failure_is_unknown_without_auto_retry(self):
        self.authorize()
        self.stage()
        calls=[]
        async def failure(client,settings,payload):
            calls.append(payload)
            raise outbox.DeliveryError("PROVIDER_UNAVAILABLE","unknown")
        async def run():
            with patch.object(outbox,"_ist_open",return_value=True):
                with patch.object(outbox,"send",new=failure):
                    first=await outbox.dispatch_once(
                        self.sessions,self.identity,now_ms=self.now,
                        settings=self.settings,signing_key=SIGN_KEY,
                        client_release_enabled=True,http_client=None)
                    second=await outbox.dispatch_once(
                        self.sessions,self.identity,now_ms=self.now,
                        settings=self.settings,signing_key=SIGN_KEY,
                        client_release_enabled=True,http_client=None)
            self.assertEqual(first["status"],"V7_UNKNOWN_NO_RETRY")
            self.assertEqual(second["status"],"V7_NOT_DISPATCHED")
        asyncio.run(run())
        self.assertEqual(len(calls),1)
        with self.sessions() as session:
            self.assertEqual(session.get(
                models.V7ClientDelivery,self.identity
            ).status,"unknown")

    def test_staging_transaction_rollback_does_not_create_delivery(self):
        self.authorize()
        with patch.object(outbox,"_ist_open",return_value=True):
            with self.assertRaisesRegex(RuntimeError,"interrupted"):
                with self.sessions.begin() as session:
                    outbox.enqueue_approved(
                        session,self.identity,now_ms=self.now,
                        chat_id=CHAT_ID,signing_key=SIGN_KEY,
                        client_release_enabled=True
                    )
                    raise RuntimeError("interrupted")
        with self.sessions() as session:
            self.assertIsNone(session.get(
                models.V7ClientDelivery,self.identity
            ))


if __name__=="__main__":
    import unittest
    unittest.main()
