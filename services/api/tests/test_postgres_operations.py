"""Optional REAL PostgreSQL integration checks, isolated in a disposable schema."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text, func
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import WatchlistItem, SignalPlan, SignalSlot, SignalEvent, WebNotification, User, Invite, ServiceLease
from app.auth import service as auth
from app.operations import lease
from app.operations.worker import sync_notifications
from app.market import views
from app.signals import service
from test_signal_service import BOUNDARY, seed, pending, publish

pytestmark=pytest.mark.skipif(not os.getenv("MV_TEST_PG_URL"),reason="Set MV_TEST_PG_URL for isolated real PostgreSQL checks")
PASSWORD="long PostgreSQL verification password"


def test_postgres_telegram_outbox_commits_once_and_rejects_a_stale_owner(pg):
    from app.telegram.worker import prepare,finish
    from app.models import TelegramDelivery
    from test_telegram import SETTINGS
    seed(pg);identity=pending(pg);publish(pg,identity)
    with lease.singleton("telegram-delivery"):
        with lease.worker_transaction("telegram-delivery",pg.sessions) as session:
            job=prepare(session,pg.clock[0],SETTINGS)
        with lease.worker_transaction("telegram-delivery",pg.sessions) as session:
            assert prepare(session,pg.clock[0]+5000,SETTINGS) is None
            finish(session,job[0],pg.clock[0],123)
        with pg.sessions.begin() as session:
            session.get(ServiceLease,"telegram-delivery").owner=str(uuid4())
        with pytest.raises(lease.LeaseLost):
            with lease.worker_transaction("telegram-delivery",pg.sessions) as session:
                session.get(TelegramDelivery,job[0]).message_id=999
        with pg.sessions() as session:
            row=session.get(TelegramDelivery,job[0]);assert row.status=="delivered" and row.message_id==123


def test_postgres_reset_preserves_foreign_keys_accounts_market_data_and_ai_budget(pg):
    from app.operations.reset import clear_generated,counts
    from test_signal_reset import setup
    from app.models import AIRequest,Candle,EngineCursor
    setup(pg)
    with pg.sessions.begin() as session:
        candle_count=session.scalar(select(func.count()).select_from(Candle))
        result=clear_generated(session,pg.clock[0]+31_000,"verified-independent-backup")
        assert result["deleted"]["signal_plans"]==1 and not any(counts(session).values())
        assert session.scalar(select(func.count()).select_from(Candle))==candle_count
        assert session.scalar(select(func.count()).select_from(User))==1
        assert session.scalar(select(AIRequest)).signal_id is None
        assert session.scalar(select(EngineCursor)).last_open_time==BOUNDARY-3_600_000


def test_postgres_reset_rollback_recovers_all_generated_records(pg):
    from app.operations.reset import clear_generated,counts
    from test_signal_reset import setup
    setup(pg)
    with pg.sessions() as session:before=counts(session)
    with pytest.raises(RuntimeError):
        with pg.sessions.begin() as session:
            clear_generated(session,pg.clock[0]+31_000,"verified-independent-backup")
            raise RuntimeError("interrupted transaction")
    with pg.sessions() as session:assert counts(session)==before


@pytest.fixture
def pg(monkeypatch):
    url=make_url(os.environ["MV_TEST_PG_URL"])
    admin=create_engine(url)
    schema="mv_test_"+uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated=url.update_query_dict({"options":"-csearch_path="+schema})
    engine=create_engine(isolated,pool_size=10)
    Base.metadata.create_all(engine)
    sessions=sessionmaker(engine,expire_on_commit=False)
    clock=[BOUNDARY+1000]
    for module in (service,views,auth): monkeypatch.setattr(module,"now_ms",lambda:clock[0])
    monkeypatch.setattr(lease,"engine",engine)
    monkeypatch.setattr(lease,"Session",sessions)
    lease.OWNERS.clear()
    yield SimpleNamespace(engine=engine,sessions=sessions,clock=clock,url=isolated,schema=schema)
    lease.OWNERS.clear()
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()


def test_postgres_real_migration_up_down_and_reupgrade(pg):
    Base.metadata.drop_all(pg.engine)
    environment={**os.environ,"MV_ENVIRONMENT":"local","MV_AUTH_REQUIRED":"false","MV_DATABASE_URL":pg.url.render_as_string(hide_password=False)}
    for key in ("MV_DATABASE_URL_FILE","MV_SERVICE_KEY_FILE"):environment.pop(key,None)
    for action,target in (("upgrade","head"),("downgrade","base"),("upgrade","head")):
        p=subprocess.run([sys.executable,"-m","alembic",action,target],cwd=Path(__file__).resolve().parents[1],env=environment,capture_output=True,text=True)
        assert p.returncode==0,p.stderr
    with pg.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version"))=="0006"
        assert connection.scalar(text("SELECT count(*) FROM watchlist"))==2


def test_postgres_ai_request_budget_and_stale_owner_cannot_commit_commentary(pg):
    from app.ai.worker import prepare, finish
    from app.models import AIRequest, AIReview
    seed(pg)
    identity = pending(pg)
    publish(pg,identity)
    settings = SimpleNamespace(ai_model="deepseek/deepseek-v4-pro-0813",ai_daily_requests=2)
    with lease.singleton("ai-review"):
        with lease.worker_transaction("ai-review",pg.sessions) as session:
            for _ in range(2):
                session.add(AIRequest(id=str(uuid4()),signal_id=None,started_at=pg.clock[0],status="failed",error_code="DIAGNOSTIC"))
        with lease.worker_transaction("ai-review",pg.sessions) as session:
            assert prepare(session,pg.clock[0],settings) is None
        with pg.sessions() as session:
            assert session.scalar(select(func.count()).select_from(AIRequest))==2
            assert session.get(AIReview,identity).status=="pending"
        with pg.sessions.begin() as session:
            row=session.get(ServiceLease,"ai-review")
            row.owner=str(uuid4())
        with pytest.raises(lease.LeaseLost):
            with lease.worker_transaction("ai-review",pg.sessions) as session:
                session.get(AIReview,identity).status="complete"
        with pg.sessions() as session:
            assert session.get(AIReview,identity).status=="pending"


def test_postgres_concurrent_invitation_accepts_once(pg):
    with pg.sessions.begin() as session:invite=auth.create_invite(session,"viewer@example.test","viewer")
    def accept():
        from fastapi import HTTPException
        with pg.sessions() as session:
            try:
                auth.accept(session,invite["token"],invite["email"],"PG viewer",PASSWORD,"test")
                return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:accept(),range(2)))
    assert sorted(results)==[200,400]
    with pg.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User))==1


def test_postgres_login_budget_is_serialized_under_parallel_requests(pg):
    def consume():
        from fastapi import HTTPException
        with pg.sessions() as session:
            try:auth.throttle(session,"one-account",3);return 200
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:consume(),range(8)))
    assert results.count(200)==3 and results.count(429)==5


def test_postgres_singleton_excludes_second_connection_and_releases(pg):
    with lease.singleton("collector"):
        with pytest.raises(RuntimeError,match="already owns"):
            with lease.singleton("collector"):pass
        with lease.worker_transaction("collector") as session:
            assert session.get(ServiceLease,"collector").owner==lease.OWNERS["collector"]
    with lease.singleton("collector"):
        with lease.worker_transaction("collector"):pass


def test_postgres_stale_owner_cannot_commit_after_handoff(pg):
    with lease.singleton("signal-engine"):
        old=lease.OWNERS["signal-engine"]
        with pg.sessions.begin() as session:
            session.get(ServiceLease,"signal-engine").owner="replacement-token"
        with pytest.raises(lease.LeaseLost):
            with lease.worker_transaction("signal-engine") as session:
                session.add(WatchlistItem(symbol="BADUSDT",sort_order=0))
        with pg.sessions() as session:assert session.get(WatchlistItem,"BADUSDT") is None
        assert lease.OWNERS["signal-engine"]==old


def test_postgres_original_decimal_signal_publication_and_notification_retry(pg):
    seed(pg);identity=pending(pg);publish(pg,identity)
    with pg.sessions.begin() as session:
        plan=session.get(SignalPlan,identity)
        assert plan.plan_json["entry"]=="200.1"
        assert plan.plan_json["stop"]=="193.0"
        assert plan.plan_json["target"]=="214.3"
        assert session.scalar(select(func.count()).select_from(SignalSlot))==1
        assert sync_notifications(session)==1
    with pg.sessions.begin() as session:assert sync_notifications(session)==0
    with pg.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SignalEvent))==1
        assert session.scalar(select(func.count()).select_from(WebNotification))==1


def test_postgres_fenced_worker_failure_rolls_back_heartbeat_and_business_data(pg):
    with lease.singleton("web-delivery"):
        with pg.sessions() as session:before=session.get(ServiceLease,"web-delivery").heartbeat
        with pytest.raises(ValueError):
            with lease.worker_transaction("web-delivery") as session:
                session.add(WatchlistItem(symbol="BTCUSDT",sort_order=0))
                raise ValueError("failure before commit")
        with pg.sessions() as session:
            assert session.get(WatchlistItem,"BTCUSDT") is None
            assert session.get(ServiceLease,"web-delivery").heartbeat==before


def test_postgres_concurrent_last_administrator_protection(pg,monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import get_settings
    from app.main import app
    from app.database import get_session
    monkeypatch.setattr(get_settings(),"auth_required",True)
    accounts=[]
    for address in ("one@example.test","two@example.test"):
        with pg.sessions.begin() as session:invite=auth.create_invite(session,address,"admin")
        with pg.sessions() as session:accounts.append(auth.accept(session,invite["token"],address,"PG admin",PASSWORD,"test"))
    def sessions():
        with pg.sessions() as session:yield session
    app.dependency_overrides[get_session]=sessions
    try:
        with TestClient(app) as client:
            def demote(account):
                return client.patch("/v1/admin/users/"+account["user"]["id"],headers={"Authorization":"Bearer "+account["token"]},json={"role":"viewer","enabled":True}).status_code
            with ThreadPoolExecutor(max_workers=2) as pool:statuses=list(pool.map(demote,accounts))
            assert sorted(statuses)==[200,409]
    finally:app.dependency_overrides.clear()
    with pg.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User).where(User.role=="admin",User.enabled.is_(True)))==1


def test_postgres_market_source_and_publication_transactions_cannot_overlap(pg):
    from threading import Event
    from app.operations.market_lock import lock_market
    locked,release,attempted=Event(),Event(),Event()
    def source_write():
        with pg.sessions.begin() as session:
            lock_market(session,"BTCUSDT")
            locked.set()
            assert release.wait(5)
    def publication():
        assert locked.wait(5)
        with pg.sessions.begin() as session:
            attempted.set()
            lock_market(session,"BTCUSDT")
            return "committed-after-source"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(source_write);second=pool.submit(publication)
        try:
            assert attempted.wait(5)
            # Observe actual PostgreSQL lock waiting, not a sleep-based ordering claim.
            import time
            until=time.monotonic()+3
            blocked=False
            while time.monotonic()<until:
                with pg.engine.connect() as connection:
                    blocked=bool(connection.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted")))
                if blocked:break
                time.sleep(.02)
            assert blocked and not second.done()
        finally:release.set()
        first.result();assert second.result()=="committed-after-source"
