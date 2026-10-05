from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, func
from app.main import app
from app.database import get_session
from app.config import get_settings, Settings
from app.auth import service as auth
from app.models import User, UserSession, Invite, AuditEvent, WebNotification, SignalEvent
from app.operations.worker import sync_notifications
from test_signal_service import state, seed, pending, publish

PASSWORD="a long private test password 2026"


@pytest.fixture
def private(state,monkeypatch):
    monkeypatch.setattr(get_settings(),"auth_required",True)
    monkeypatch.setattr(auth,"now_ms",lambda:state.clock[0])
    def sessions():
        with state.sessions() as session:
            yield session
    app.dependency_overrides[get_session]=sessions
    def account(role="admin",address="owner@example.test"):
        with state.sessions.begin() as session:
            invite=auth.create_invite(session,address,role)
        with state.sessions() as session:
            return auth.accept(session,invite["token"],address,"Test member",PASSWORD,"test")
    with TestClient(app) as client:
        yield SimpleNamespace(state=state,client=client,account=account)
    app.dependency_overrides.clear()


def bearer(result):
    return {"Authorization":"Bearer "+result["token"]}


def test_production_refuses_partial_controls_and_accepts_complete_configuration():
    Settings(environment="production",auth_required=True,public_origin="https://mv.jaleshwarima.com",database_url="postgresql+psycopg://test@db/test",service_key="x"*48).check_local_only()
    for changes in ({"auth_required":False},{"paper_enabled":True},{"service_key":"short"},{"public_origin":"http://example.test"},{"database_url":"sqlite:///test.db"}):
        with pytest.raises(RuntimeError):
            Settings(environment="production",**({"auth_required":True,"public_origin":"https://mv.jaleshwarima.com","database_url":"postgresql+psycopg://test@db/test","service_key":"x"*48}|changes)).check_local_only()


def test_auth_required_rejects_development_token(private):
    assert private.client.get("/v1/watchlist",headers={"Authorization":"Bearer mv-local-preview-only"}).status_code==401


def test_single_use_invitation_password_hash_and_session_storage(private):
    result=private.account()
    assert private.client.get("/v1/auth/me",headers=bearer(result)).json()["user"]["role"]=="admin"
    with private.state.sessions() as session:
        user=session.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
        stored=session.scalar(select(UserSession))
        assert stored.token_hash==auth.digest(result["token"]) and stored.token_hash!=result["token"]
        assert session.scalar(select(Invite)).used_at is not None
    response=private.client.post("/v1/auth/accept",json={"token":"invalid-token"*4,"email":"owner@example.test","name":"Test","password":PASSWORD})
    assert response.status_code==400
    assert "password_hash" not in private.client.get("/v1/admin/users",headers=bearer(result)).text


@pytest.mark.parametrize("fault",["expired","used","email","short-password"])
def test_bad_invitation_cannot_create_account(private,fault):
    with private.state.sessions.begin() as session:
        invite=auth.create_invite(session,"viewer@example.test","viewer")
        session.flush()
        row=session.get(Invite,auth.digest(invite["token"]))
        if fault=="expired":row.expires_at=private.state.clock[0]-1
        if fault=="used":row.used_at=private.state.clock[0]
    response=private.client.post("/v1/auth/accept",json={"token":invite["token"],"email":"wrong@example.test" if fault=="email" else invite["email"],"name":"Test","password":"short" if fault=="short-password" else PASSWORD})
    assert response.status_code in (400,422)
    with private.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(User))==0


@pytest.mark.parametrize("role,status",[("viewer",403),("operator",200),("admin",200)])
def test_role_permissions_on_real_market_mutation(private,role,status):
    result=private.account(role)
    assert private.client.get("/v1/watchlist",headers=bearer(result)).status_code==200
    assert private.client.put("/v1/watchlist",headers=bearer(result),json={"symbols":["ETHUSDT"]}).status_code==status
    assert private.client.get("/v1/admin/users",headers=bearer(result)).status_code==(200 if role=="admin" else 403)


def test_operator_cannot_change_signal_slot_when_viewer(private):
    seed(private.state);identity=pending(private.state);publish(private.state,identity)
    account=private.account("viewer")
    assert private.client.post(f"/v1/signals/{identity}/slot",headers=bearer(account),json={"action":"hold"}).status_code==403


def test_revocation_expiry_and_password_rotation(private):
    owner=private.account(); headers=bearer(owner)
    assert private.client.post("/v1/auth/password",headers=headers,json={"current_password":"wrong","new_password":PASSWORD+"new"}).status_code==400
    rotated=private.client.post("/v1/auth/password",headers=headers,json={"current_password":PASSWORD,"new_password":PASSWORD+"new"})
    assert rotated.status_code==200
    assert private.client.get("/v1/auth/me",headers=headers).status_code==401
    fresh=bearer(rotated.json())
    assert private.client.get("/v1/auth/me",headers=fresh).status_code==200
    assert private.client.post("/v1/auth/logout",headers=fresh).status_code==200
    assert private.client.get("/v1/auth/me",headers=fresh).status_code==401
    login=private.client.post("/v1/auth/login",json={"email":"OWNER@example.test","password":PASSWORD+"new"})
    assert login.status_code==200
    private.state.clock[0]+=13*3_600_000
    assert private.client.get("/v1/auth/me",headers=bearer(login.json())).status_code==401


def test_disabled_user_and_role_changes_revoke_existing_sessions(private):
    owner=private.account();viewer=private.account("viewer","viewer@example.test")
    result=private.client.patch("/v1/admin/users/"+viewer["user"]["id"],headers=bearer(owner),json={"role":"operator","enabled":False})
    assert result.status_code==200
    assert private.client.get("/v1/auth/me",headers=bearer(viewer)).status_code==401
    assert private.client.post("/v1/auth/login",json={"email":"viewer@example.test","password":PASSWORD}).status_code==401


def test_last_administrator_and_invitation_revocation(private):
    owner=private.account();headers=bearer(owner)
    for role,enabled in (("admin",False),("viewer",True)):
        assert private.client.patch("/v1/admin/users/"+owner["user"]["id"],headers=headers,json={"role":role,"enabled":enabled}).status_code==409
    created=private.client.post("/v1/admin/invites",headers=headers,json={"email":"viewer@example.test","role":"viewer"}).json()
    token=created["accept_url"].split("#invite=")[1]
    assert private.client.delete("/v1/admin/invites/"+auth.digest(token),headers=headers).status_code==200
    assert private.client.post("/v1/auth/accept",json={"token":token,"email":"viewer@example.test","name":"Test","password":PASSWORD}).status_code==400
    assert "invite-revoked" in private.client.get("/v1/admin/audit",headers=headers).text


def test_login_throttle_is_durable_and_generic(private):
    private.account()
    for i in range(10):
        response=private.client.post("/v1/auth/login",json={"email":"owner@example.test","password":"bad"})
        assert response.status_code==401
        assert response.json()["detail"]=="Email or password is incorrect"
    blocked=private.client.post("/v1/auth/login",json={"email":"owner@example.test","password":PASSWORD})
    assert blocked.status_code==429 and blocked.headers["retry-after"]=="900"
    private.state.clock[0]+=900001
    assert private.client.post("/v1/auth/login",json={"email":"owner@example.test","password":PASSWORD}).status_code==200


def test_web_delivery_is_idempotent_transactional_and_per_account(private):
    seed(private.state); identity=pending(private.state);publish(private.state,identity)
    owner=private.account();viewer=private.account("viewer","viewer@example.test")
    with private.state.sessions() as session:
        assert sync_notifications(session)==1
        session.rollback()
    with private.state.sessions.begin() as session:
        assert sync_notifications(session)==1
    with private.state.sessions.begin() as session:
        assert sync_notifications(session)==0
    payload=private.client.get("/v1/notifications",headers=bearer(owner)).json()
    assert payload["unread"]==1
    notice=payload["notifications"][0]
    assert notice["signal_id"]==identity
    for _ in range(2):
        assert private.client.post("/v1/notifications/"+notice["id"]+"/read",headers=bearer(owner)).status_code==200
    assert private.client.get("/v1/notifications",headers=bearer(owner)).json()["unread"]==0
    assert private.client.get("/v1/notifications",headers=bearer(viewer)).json()["unread"]==1
    with private.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(WebNotification))==1
        assert session.get(SignalEvent,notice["id"]).created_at==notice["created_at"]


def test_history_cursor_and_paper_default_disabled(private):
    seed(private.state);identity=pending(private.state);publish(private.state,identity)
    owner=private.account();headers=bearer(owner)
    result=private.client.get("/v1/history/signals?limit=1&symbol=BTCUSDT&direction=long",headers=headers).json()
    assert result["signals"][0]["id"]==identity and result["next"] is None
    assert private.client.get("/v1/history/signals?direction=short",headers=headers).json()["signals"]==[]
    assert private.client.get("/v1/history/signals?before_time=1",headers=headers).status_code==422
    assert private.client.get("/v1/history/signals?limit=101",headers=headers).status_code==422
    assert private.client.get("/v1/paper",headers=headers).json()["disabled"] is True


@pytest.mark.parametrize("publication,matches",[
    ("2026-10-04T18:29:59.999+00:00",False),
    ("2026-10-04T18:30:00+00:00",True),
    ("2026-10-05T18:29:59.999+00:00",True),
    ("2026-10-05T18:30:00+00:00",False),
])
def test_history_ist_day_boundaries_and_cursor_preserve_frozen_plan(private,publication,matches):
    from copy import deepcopy
    from datetime import datetime
    from app.models import SignalPlan
    seed(private.state);identity=pending(private.state);publish(private.state,identity)
    headers=bearer(private.account())
    timestamp=int(datetime.fromisoformat(publication).timestamp()*1000)
    # Move only publication-index metadata in this isolated query scenario;
    # all risk/evidence bytes still originate from the real strategy engine.
    with private.state.sessions.begin() as session:
        row=session.get(SignalPlan,identity)
        frozen=deepcopy(row.plan_json)
        row.created_at=timestamp
    response=private.client.get('/v1/history/signals?date=2026-10-05&limit=1&direction=long&symbol=BTCUSDT',headers=headers)
    assert response.status_code==200
    assert [s['id'] for s in response.json()['signals']]==([identity] if matches else [])
    assert response.json()['next'] is None
    cursor=private.client.get(f'/v1/history/signals?date=2026-10-05&before_time={timestamp}&before_id={identity}',headers=headers)
    assert cursor.status_code==200 and cursor.json()['signals']==[]
    assert private.client.get('/v1/history/signals',headers=headers).json()['signals'][0]['id']==identity
    with private.state.sessions() as session:
        assert session.get(SignalPlan,identity).plan_json==frozen


def test_history_date_rejects_invalid_calendar_days_and_requires_authentication(private):
    headers=bearer(private.account())
    for date in ('2026-02-30','2026-13-01','2026-2-1','not-a-date'):
        assert private.client.get('/v1/history/signals',params={'date':date},headers=headers).status_code==422
    assert private.client.get('/v1/history/signals?date=2026-10-05').status_code==401


def test_production_gateway_key_is_required_even_for_login(private,monkeypatch):
    settings=get_settings()
    monkeypatch.setattr(settings,"environment","production")
    monkeypatch.setattr(settings,"service_key","server-key"*8)
    assert private.client.post("/v1/auth/login",json={"email":"owner@example.test","password":PASSWORD}).status_code==401
    assert private.client.get("/v1/watchlist",headers={"Authorization":"Bearer mv-local-preview-only"}).status_code==401


def test_hash_concurrency_budget_fails_closed():
    auth.HASH_BUDGET.acquire();auth.HASH_BUDGET.acquire()
    try:
        with pytest.raises(Exception) as exc:
            auth.hash_password(PASSWORD)
        assert exc.value.status_code==429
    finally:
        auth.HASH_BUDGET.release();auth.HASH_BUDGET.release()


def test_maintenance_preserves_expiry_but_blocks_new_publication(private,monkeypatch):
    import asyncio
    from app.signals import worker
    from app.models import EngineStatus, SignalPlan
    seed(private.state);identity=pending(private.state)
    monkeypatch.setattr(get_settings(),"maintenance",True)
    engine=worker.SignalWorker(None)
    asyncio.run(engine.tick())
    with private.state.sessions() as session:
        assert session.get(SignalPlan,identity) is None
        assert session.get(EngineStatus,"engine").state=="maintenance"
    assert private.client.get("/v1/operations/ready",headers=bearer(private.account())).status_code==503


def test_notification_cursor_preserves_equal_timestamp_order(private):
    from uuid import uuid4
    seed(private.state);identity=pending(private.state);publish(private.state,identity)
    with private.state.sessions.begin() as session:
        for _ in range(4):session.add(SignalEvent(id=str(uuid4()),signal_id=identity,type="test-audit",created_at=private.state.clock[0],payload_json={"controlled":True}))
    with private.state.sessions.begin() as session:assert sync_notifications(session)==5
    headers=bearer(private.account())
    first=private.client.get("/v1/notifications?limit=3",headers=headers).json()
    cursor=first["next"]
    second=private.client.get("/v1/notifications",headers=headers,params={"limit":3,**cursor}).json()
    ids=[n["id"] for n in first["notifications"]+second["notifications"]]
    assert len(ids)==len(set(ids))==5 and second["next"] is None


def test_source_revision_disables_entry_before_the_periodic_withdrawal_scan(private):
    from dataclasses import replace
    from decimal import Decimal
    from app.market.store import apply_bars
    from app.models import SignalPlan
    source,_=seed(private.state);identity=pending(private.state);publish(private.state,identity)
    with private.state.sessions() as session:original=dict(session.get(SignalPlan,identity).plan_json)
    with private.state.sessions.begin() as session:
        apply_bars(session,"BTCUSDT","1h",[replace(source[-1],high=source[-1].high+Decimal("0.1"))],private.state.clock[0])
    account=private.account("operator")
    view=private.client.get("/v1/signals/"+identity,headers=bearer(account)).json()
    assert view["status"]=="withdrawn" and not view["entry_actionable"]
    assert not any(e["type"]=="source-revised" for e in view["events"])
    assert private.client.post("/v1/signals/"+identity+"/slot",headers=bearer(account),json={"action":"hold"}).status_code==409
    with private.state.sessions() as session:assert session.get(SignalPlan,identity).plan_json==original
