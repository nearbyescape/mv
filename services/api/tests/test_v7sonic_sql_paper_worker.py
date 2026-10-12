"""No-network checks for approved V7 capture -> fenced private SQL journaling.

Only testing isolated DB and mocked network/Telegram paths. No live
production data, client delivery or exchange trading.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, v7sonic_release as release
from app.database import Base
from app import v7sonic_sql_paper_worker as worker
from services.t7sonic import release_scheduler as scheduler
from services.t7sonic.early_live_smoke import _save_original_responses
from test_t7sonic_early_live_smoke import data
from test_t7sonic_forward_release_bridge import BOUNDARY


class V7SQLPaperWorkerTests(TestCase):
    def setUp(self):
        self.engine=create_engine(
            "sqlite://", connect_args={"check_same_thread":False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory=sessionmaker(self.engine,expire_on_commit=False)
        self.folder=TemporaryDirectory(prefix="v7-sql-worker-")
        self.root=Path(self.folder.name)
        candles,books,info,book_times=data()
        self.original_path,self.original_sha=_save_original_responses(
            self.root, BOUNDARY,candles,books,info,book_times,
            BOUNDARY+1500,
        )
        with patch.object(release,"_ist_open",return_value=True):
            from services.t7sonic.replay_original_capture import _read_private_file
            self.paper=release.rehearse_original_capture(
                _read_private_file(self.original_path),
                observed_now_ms=BOUNDARY+2000,
                active_symbols=(),previously_seen_candidate_ids=(),
            )
        self.summary_payload={
            "status":"PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND",
            "boundary_ms":BOUNDARY,
            "market_count":6,
            "last_original_http_sha256":self.original_sha,
            "paper_batch_sha256":self.paper["source_batch_sha256"],
            "attempt_count":1,
            "source_attempts":[{
                "attempt":1,
                "original_http_file":self.original_path,
                "original_http_sha256":self.original_sha,
            }],
            "client_publication_authorized":False,
            "telegram_messages_sent":0,
            "orders_submitted":0,
        }
        payload=(json.dumps(self.summary_payload,sort_keys=True)+"\n").encode()
        self.summary_path=self.root/"private-paper-summary.json"
        self.summary_path.write_bytes(payload)
        self.summary_path.chmod(0o600)
        self.summary={
            "status":self.summary_payload["status"],
            "decision_boundary_ms":BOUNDARY,
            "market_count":6,
            "original_http_sha256":self.original_sha,
            "paper_batch_sha256":self.paper["source_batch_sha256"],
            "receipt_path":str(self.summary_path),
            "receipt_sha256":sha256(payload).hexdigest(),
            "client_publication_authorized":False,
            "telegram_messages_sent":0,
            "orders_submitted":0,
        }

    def tearDown(self):
        self.folder.cleanup()
        self.engine.dispose()

    def test_resolve_exact_private_summary_to_last_pinned_http(self):
        path,digest=worker._completed_capture_source(self.summary)
        self.assertEqual(path,self.original_path)
        self.assertEqual(digest,self.original_sha)

    def test_hash_or_summary_tamper_blocks_any_write(self):
        cases=[]
        altered=dict(self.summary);altered["receipt_sha256"]="0"*64
        cases.append(altered)
        altered=dict(self.summary);altered["original_http_sha256"]="0"*64
        cases.append(altered)
        altered=dict(self.summary);altered["telegram_messages_sent"]=1
        cases.append(altered)
        for summary in cases:
            with self.subTest(summary=summary):
                with self.assertRaises((ValueError,PermissionError)):
                    worker._completed_capture_source(summary)
        with self.factory() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ),0)

    def test_fenced_source_to_sql_exact_batch_persists_once(self):
        with patch.object(worker,"Session",self.factory),patch.object(
            release,"_ist_open",return_value=True
        ):
            first=worker._stage_final_capture(
                self.summary, clock_ms=lambda:BOUNDARY+2500,
            )
            repeat=worker._stage_final_capture(
                self.summary, clock_ms=lambda:BOUNDARY+2500,
            )
        self.assertEqual(first["status"],"FENCED_V7_PRIVATE_SQL_CYCLE_NO_CLIENT_SEND")
        self.assertEqual(repeat["status"],"FENCED_V7_PRIVATE_SQL_EXACT_REPLAY_NO_CLIENT_SEND")
        self.assertEqual(first["batch_sha256"],self.summary["paper_batch_sha256"])
        with self.factory() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionRecord)
            ),6)
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.TelegramDelivery)
            ),0)

    def test_cross_ledger_batch_mismatch_rolls_back_db_transaction(self):
        summary={**self.summary,"paper_batch_sha256":"b"*64}
        altered_payload={**self.summary_payload,"paper_batch_sha256":"b"*64}
        body=(json.dumps(altered_payload,sort_keys=True)+"\n").encode()
        self.summary_path.write_bytes(body)
        summary["receipt_sha256"]=sha256(body).hexdigest()
        with patch.object(worker,"Session",self.factory),patch.object(
            release,"_ist_open",return_value=True
        ):
            with self.assertRaisesRegex(ValueError,"batch mismatch"):
                worker._stage_final_capture(
                    summary,clock_ms=lambda:BOUNDARY+2500
                )
        with self.factory() as session:
            self.assertEqual(session.scalar(
                select(func.count()).select_from(models.V7DecisionCycle)
            ),0)

    def test_sql_scheduling_requires_three_explicit_approvals(self):
        with self.assertRaisesRegex(PermissionError,"Three explicit"):
            worker.run_private_sql_paper(self.folder.name)
        with self.assertRaisesRegex(PermissionError,"Three explicit"):
            worker.run_private_sql_paper(
                self.folder.name,
                public_network_approved=True,
                paper_only_acknowledged=True,
            )
        with self.assertRaisesRegex(RuntimeError,"Non-PostgreSQL"):
            worker.run_private_sql_paper(
                self.folder.name,
                public_network_approved=True,
                paper_only_acknowledged=True,
                sql_paper_write_approved=True,
            )

    def test_sql_scheduler_approved_sink_truthfully_reports_database_write(self):
        captured=[]
        def source(path,**kwargs):
            return {
                "status":"PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND",
                "decision_boundary_ms":BOUNDARY,
                "market_count":6,
                "original_http_sha256":self.original_sha,
                "client_publication_authorized":False,
                "telegram_messages_sent":0,
                "orders_submitted":0,
            }
        def sink(receipt):
            captured.append(receipt)
            return {
                "status":"FENCED_V7_PRIVATE_SQL_CYCLE_NO_CLIENT_SEND",
                "decision_boundary_ms":BOUNDARY,
                "source_sha256":self.original_sha,
                "markets_evaluated":6,
                "client_publication_authorized":False,
                "telegram_messages_sent":0,
                "orders_submitted":0,
            }
        with patch.object(release,"_ist_open",return_value=True):
            with patch.object(scheduler,"_check_capacity"):
                result=scheduler.run_private_paper_loop(
                    self.folder.name,
                    public_network_approved=True,
                    paper_only_acknowledged=True,
                    durable_sql_sink=sink,
                    sql_journal_approved=True,
                    capture=source,
                    clock_ms=lambda:BOUNDARY-1000,
                    sleep=lambda _:None,
                    max_cycles=1,
                )
        self.assertEqual(len(captured),1)
        self.assertTrue(result["production_database_writes"])
        self.assertTrue(result["private_sql_journal_approved"])
        self.assertEqual(result["telegram_messages_sent"],0)

    def test_sql_sink_needs_explicit_approval_and_rejects_false_send_result(self):
        with self.assertRaisesRegex(PermissionError,"Database sink forbidden"):
            scheduler.run_private_paper_loop(
                self.folder.name,
                public_network_approved=True,paper_only_acknowledged=True,
                durable_sql_sink=lambda _:None,
            )
        def source(path,**kwargs):
            return {
                "status":"PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND",
                "decision_boundary_ms":BOUNDARY,
                "market_count":6,
                "original_http_sha256":self.original_sha,
                "client_publication_authorized":False,
                "telegram_messages_sent":0,
                "orders_submitted":0,
            }
        def malicious_sink(receipt):
            return {
                "status":"FENCED_V7_PRIVATE_SQL_CYCLE_NO_CLIENT_SEND",
                "decision_boundary_ms":BOUNDARY,
                "source_sha256":self.original_sha,
                "markets_evaluated":6,
                "client_publication_authorized":True,
                "telegram_messages_sent":1,
                "orders_submitted":0,
            }
        with patch.object(release,"_ist_open",return_value=True),patch.object(
            scheduler,"_check_capacity"
        ):
            with self.assertRaisesRegex(ValueError,"SQL sink rejected"):
                scheduler.run_private_paper_loop(
                    self.folder.name,
                    public_network_approved=True,paper_only_acknowledged=True,
                    sql_journal_approved=True,durable_sql_sink=malicious_sink,
                    capture=source,clock_ms=lambda:BOUNDARY-1000,
                    sleep=lambda _:None,max_cycles=1,
                )
        self.assertEqual(len(list(
            self.root.glob("v7sonic-private-gap-*.json")
        )),1)

    def test_database_schema_preflight_requires_revision_0009(self):
        class Fake:
            def __init__(self,revision,missing=None):
                self.revision=revision;self.missing=missing
            def get_bind(self):
                return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
            def scalar(self,sql,params=None):
                if "version_num" in str(sql):
                    return self.revision
                return None if params["table"]==self.missing else params["table"]
        worker._check_private_sql_ready(Fake("0010"))
        with self.assertRaisesRegex(RuntimeError,"exact applied migration"):
            worker._check_private_sql_ready(Fake("0009"))
        with self.assertRaisesRegex(RuntimeError,"table absent"):
            worker._check_private_sql_ready(
                Fake("0010",missing="v7_decision_records")
            )


if __name__=="__main__":
    import unittest
    unittest.main()
