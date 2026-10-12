"""Isolated SQL persistence verification for V7Sonic.

No production DB connection, Telegram API, network, or exchange execution.
Uses a fresh in-memory SQL database; application migrations are separate.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from unittest import TestCase

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.v7sonic_store import (
    store_private_cycle, inspect_private_cycle,
)
from app.v7sonic_release import STRATEGY_ID, format_private_rehearsal
from app.research.t7sonic_release_preview import build_offline_preview
from test_t7sonic_release_preview import group

BOUNDARY = group()[0][0]["as_of_ms"]
ORIGINAL = "a" * 64


def report(*, with_candidates=True):
    snapshots, quotes = group()
    batch = build_offline_preview(
        snapshots, quotes,
        active_symbols=() if with_candidates else tuple(
            item["symbol"] for item in snapshots
        ),
    )
    rehearsals = [
        {
            "candidate_id": c["candidate_id"],
            "symbol": c["symbol"],
            "direction": c["direction"],
            "expert": c["expert"],
            "expires_at_ms": c["expires_at_ms"],
            "rehearsal_text": format_private_rehearsal(c),
        }
        for c in batch["indicative_candidates"]
    ]
    return {
        "strategy_id": STRATEGY_ID,
        "decision_boundary_ms": batch["decision_boundary_ms"],
        "source_batch_sha256": batch["batch_sha256"],
        "sealed_internal_paper_batch": batch,
        "markets_evaluated": 6,
        "candidate_count": batch["candidate_count"],
        "original_http_responses_verified": 31,
        "new_rehearsals": rehearsals,
        "client_publication_authorized": False,
        "telegram_enqueued": False,
        "orders_authorized": False,
        "persisted_outbox_implemented": False,
        "live_worker_integrated": False,
    }


class V7PrivateSQLTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def tearDown(self):
        self.engine.dispose()

    def store(self, packet=None):
        with self.sessions.begin() as session:
            return store_private_cycle(
                session,
                report=packet if packet is not None else report(),
                original_http_sha256=ORIGINAL,
                recorded_at_ms=BOUNDARY + 2_000,
            )

    def test_six_positive_candidates_create_six_blocked_private_drafts(self):
        out = self.store()
        self.assertEqual(out["status"], "V7_PRIVATE_SQL_BATCH_STORED_UNPUBLISHED")
        self.assertEqual(out["six_market_records"], 6)
        self.assertEqual(out["private_drafts"], 6)
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DecisionCycle)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DecisionRecord)), 6
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DeliveryDraft)), 6
            )
            draft = session.scalars(select(models.V7DeliveryDraft)).first()
            self.assertEqual(draft.state, "BLOCKED_NOT_FOR_CLIENTS")
            self.assertIn("DO NOT TRADE", draft.text)
            self.assertNotIn("TP3", draft.text)
            audit = inspect_private_cycle(session, BOUNDARY)
            self.assertEqual(audit["drafts_blocked"], 6)
            self.assertFalse(audit["client_publication_authorized"])
            self.assertEqual(audit["telegram_messages_sent"], 0)
            for original_type in (
                models.SignalPlan, models.SignalDecision,
                models.SignalSlot, models.SignalEvent, models.TelegramDelivery,
            ):
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(original_type)), 0
                )

    def test_all_six_no_setup_rows_without_fabricated_drafts(self):
        packet = report(with_candidates=False)
        self.assertEqual(packet["candidate_count"], 0)
        out = self.store(packet)
        self.assertEqual(out["private_drafts"], 0)
        with self.sessions() as session:
            self.assertEqual(inspect_private_cycle(session, BOUNDARY)["market_records"], 6)
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DeliveryDraft)),
                0,
            )

    def test_exact_repeat_is_idempotent_and_changed_source_rejected(self):
        first = self.store()
        again = self.store()
        self.assertEqual(again["status"], "EXACT_V7_CYCLE_REPLAY_UNMODIFIED")
        with self.assertRaisesRegex(ValueError, "Conflicting immutable"):
            with self.sessions.begin() as session:
                store_private_cycle(
                    session, report=report(),
                    original_http_sha256="b" * 64,
                    recorded_at_ms=BOUNDARY + 2_000
                )
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DecisionCycle)), 1
            )
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DeliveryDraft)), 6
            )

    def test_failed_transaction_rolls_all_new_rows_back(self):
        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            with self.sessions.begin() as session:
                store_private_cycle(
                    session, report=report(),
                    original_http_sha256=ORIGINAL, recorded_at_ms=BOUNDARY+1000,
                )
                session.flush()
                raise RuntimeError("simulated crash")
        with self.sessions() as session:
            for cls in (
                models.V7DecisionCycle, models.V7DecisionRecord, models.V7DeliveryDraft
            ):
                self.assertEqual(
                    session.scalar(select(func.count()).select_from(cls)), 0
                )

    def test_forged_client_flag_or_changed_draft_does_not_persist(self):
        cases = []
        bad = report()
        bad["client_publication_authorized"] = True
        cases.append(bad)
        bad = report()
        bad["new_rehearsals"][0]["rehearsal_text"] = "fabricated trade"
        cases.append(bad)
        bad = report()
        bad["new_rehearsals"][0]["candidate_id"] = "0" * 64
        cases.append(bad)
        bad = report()
        bad["sealed_internal_paper_batch"]["decision_records"][0]["entry"] = "999"
        cases.append(bad)
        for payload in cases:
            with self.subTest(kind=payload["new_rehearsals"][0]["candidate_id"]):
                with self.assertRaises(ValueError):
                    self.store(payload)
        with self.sessions() as session:
            self.assertEqual(
                session.scalar(select(func.count()).select_from(models.V7DecisionCycle)),
                0
            )

    def test_expired_timestamp_and_draft_tamper_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "timestamp"):
            with self.sessions.begin() as session:
                store_private_cycle(
                    session, report=report(),
                    original_http_sha256=ORIGINAL,
                    recorded_at_ms=BOUNDARY + 30_001,
                )
        self.store()
        with self.sessions.begin() as session:
            draft = session.scalars(select(models.V7DeliveryDraft)).first()
            draft.text = "modified payload"
        with self.sessions() as session:
            with self.assertRaisesRegex(ValueError, "Altered private"):
                inspect_private_cycle(session, BOUNDARY)


if __name__ == "__main__":
    import unittest
    unittest.main()
