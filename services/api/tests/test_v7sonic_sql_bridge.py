"""V7 original-source to isolated SQL write bridge regression.

No production DB, HTTP, Telegram or exchange API calls. A fresh ephemeral
SQLite database exercises the same SQLAlchemy transaction boundaries.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, v7sonic_release as release
from app.database import Base
from app.v7sonic_sql_bridge import stage_private_original_sql_cycle
from services.t7sonic.early_live_smoke import _save_original_responses
from test_t7sonic_early_live_smoke import data
from test_t7sonic_forward_release_bridge import BOUNDARY

FAKE_ID = "b" * 64


class V7SQLBridgeTests(TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.root = TemporaryDirectory(prefix="v7-sql-bridge-")
        candles, books, info, quote_times = data()
        self.path, self.sha = _save_original_responses(
            Path(self.root.name),
            BOUNDARY,
            candles, books, info, quote_times,
            BOUNDARY + 1_500,
        )

    def tearDown(self):
        self.root.cleanup()
        self.engine.dispose()

    def run_bridge(self, *, sha=None, now=None, path=None):
        with patch.object(release, "_ist_open", return_value=True):
            with self.sessions.begin() as session:
                return stage_private_original_sql_cycle(
                    session,
                    original_path=path or self.path,
                    original_http_sha256=sha or self.sha,
                    observed_now_ms=BOUNDARY + 2_000 if now is None else now,
                )

    def test_six_rows_stored_in_separate_sql_tables_only(self):
        result = self.run_bridge()
        self.assertEqual(
            result["status"], "FENCED_V7_PRIVATE_SQL_CYCLE_NO_CLIENT_SEND"
        )
        self.assertEqual(result["markets_evaluated"], 6)
        self.assertEqual(result["source_sha256"], self.sha)
        self.assertFalse(result["client_publication_authorized"])
        self.assertEqual(result["telegram_messages_sent"], 0)
        self.assertEqual(result["orders_submitted"], 0)
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ), 1)
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionRecord)
            ), 6)
            for cls in (
                models.SignalDecision, models.SignalPlan, models.SignalEvent,
                models.TelegramDelivery, models.SignalSlot,
            ):
                self.assertEqual(session.scalar(
                    select(func.count()).select_from(cls)
                ), 0)

    def test_repeated_capture_replays_sealed_cycle_without_extra_rows(self):
        self.run_bridge()
        second = self.run_bridge()
        self.assertEqual(
            second["status"], "FENCED_V7_PRIVATE_SQL_EXACT_REPLAY_NO_CLIENT_SEND"
        )
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ), 1)
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionRecord)
            ), 6)

    def test_legacy_reserved_or_held_slot_blocks_same_symbol(self):
        with self.sessions.begin() as session:
            session.add(models.SignalDecision(
                id=FAKE_ID, symbol="BTCUSDT", strategy="LEGACY-V4-TEST",
                source_open_time=BOUNDARY - 3_600_000,
                outcome="PUBLISHED", reason="test",
                updated_at=BOUNDARY, expires_at=BOUNDARY + 100_000,
                attempts=0, evidence_json={},
            ))
            session.flush()
            session.add(models.SignalPlan(
                id=FAKE_ID, symbol="BTCUSDT", strategy="LEGACY-V4-TEST",
                created_at=BOUNDARY, expires_at=BOUNDARY + 100_000,
                plan_json={}, evidence_json={}, evidence_hash="a" * 64,
            ))
            session.flush()
            session.add(models.SignalSlot(
                symbol="BTCUSDT", strategy="LEGACY-V4-TEST",
                signal_id=FAKE_ID, state="held",
            ))
        result=self.run_bridge()
        self.assertEqual(result["legacy_locked_markets"], ["BTCUSDT"])
        with self.sessions() as session:
            row=session.scalar(select(models.V7DecisionRecord).where(
                models.V7DecisionRecord.symbol=="BTCUSDT"
            ))
            self.assertEqual(row.outcome, "NO_CANDIDATE")
            self.assertEqual(row.decision_json["reason"], "ACTIVE_POSITION_LOCK")
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.SignalSlot)
            ), 1)

    def test_digest_tamper_and_permission_failure_do_not_write(self):
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.run_bridge(sha="0"*64)
        evidence = Path(self.path)
        evidence.chmod(0o644)
        try:
            with self.assertRaises(PermissionError):
                self.run_bridge()
        finally:
            evidence.chmod(0o600)
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ), 0)

    def test_expired_cycle_never_backfilled_or_persisted(self):
        with self.assertRaisesRegex(ValueError, "Stale"):
            self.run_bridge(now=BOUNDARY+30_100)
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionRecord)
            ), 0)

    def test_worker_fence_failure_prevents_db_mutation(self):
        from app import v7sonic_sql_bridge as module
        with patch.object(module, "assert_fence",
                          side_effect=RuntimeError("LOST_V7_FENCE")):
            with self.assertRaisesRegex(RuntimeError,"LOST_V7_FENCE"):
                self.run_bridge()
        with self.sessions() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ), 0)

    def test_caller_transaction_rollback_removes_every_v7_row(self):
        with patch.object(release, "_ist_open", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "interrupted transaction"):
                with self.sessions.begin() as session:
                    stage_private_original_sql_cycle(
                        session, original_path=self.path,
                        original_http_sha256=self.sha,
                        observed_now_ms=BOUNDARY+2_000,
                    )
                    raise RuntimeError("interrupted transaction")
        with self.sessions() as session:
            for cls in (
                models.V7DecisionCycle, models.V7DecisionRecord, models.V7DeliveryDraft,
            ):
                self.assertEqual(session.scalar(
                    select(func.count()).select_from(cls)
                ), 0)


if __name__ == "__main__":
    import unittest
    unittest.main()
