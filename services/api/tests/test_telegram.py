import asyncio
from types import SimpleNamespace
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,func
from app.models import SignalPlan,SignalEvent,TelegramDelivery,IndicatorSnapshot
from app.telegram.provider import send,verify_destination,DeliveryError
from app.telegram.worker import prepare,finish,recover_interrupted,GAP_MS
from app.signals.service import canonical_hash,add_event
from test_signal_service import state,seed,pending,publish,BOUNDARY,STEP

SETTINGS=SimpleNamespace(telegram_enabled=True,telegram_token="123456789:"+"a"*30,telegram_chat_id="-1003993483763",
                         telegram_start_at=BOUNDARY,public_origin="https://test.invalid")


def committed(state):
    seed(state);identity=pending(state);publish(state,identity)
    return identity


def test_fenced_outbox_claim_is_durable_deduplicated_and_immutable_levels_match_engine(state):
    identity=committed(state)
    with state.sessions.begin() as session:
        plan=session.get(SignalPlan,identity)
        original=canonical_hash([plan.plan_json,plan.evidence_json])
        job=prepare(session,state.clock[0],SETTINGS)
        assert job and prepare(session,state.clock[0],SETTINGS) is None
        text=job[1]["text"]
        for value in (plan.plan_json["entry"],plan.plan_json["stop"],plan.plan_json["tp1"],plan.plan_json["tp2"],plan.plan_json["tp3"]):assert value in text
        assert all(label in text for label in ("TP1", "TP2", "TP3", "30%", "40%", "move remaining stop to entry", "move remaining stop to TP1"))
        assert "IST" in text and "Entry window ends" in text and "LONG" in text
        assert session.get(TelegramDelivery,job[0]).status=="inflight"
    with state.sessions.begin() as session:
        finish(session,job[0],state.clock[0],456)
        finish(session,job[0],state.clock[0],999)
        assert prepare(session,state.clock[0]+GAP_MS,SETTINGS) is None
        row=session.get(TelegramDelivery,job[0]);assert row.message_id==456 and row.status=="delivered"
        assert canonical_hash([session.get(SignalPlan,identity).plan_json,session.get(SignalPlan,identity).evidence_json])==original
        assert session.scalar(select(func.count()).select_from(TelegramDelivery))==1


@pytest.mark.parametrize("fault,code",[("expired","ENTRY_NO_LONGER_ACTIVE"),("source","SOURCE_REVISED"),("payload","EVIDENCE_OR_PAYLOAD_CHANGED"),("evidence","EVIDENCE_OR_PAYLOAD_CHANGED"),("destination","DESTINATION_CHANGED")])
def test_invalid_or_expired_signal_never_sends(state,fault,code):
    identity=committed(state)
    from app.telegram.worker import enqueue
    with state.sessions.begin() as session:
        enqueue(session,state.clock[0],SETTINGS)
        row=session.scalar(select(TelegramDelivery));plan=session.get(SignalPlan,identity)
        if fault=="expired":state.clock[0]+=300_000
        if fault=="source":session.get(IndicatorSnapshot,("BTCUSDT","1h",BOUNDARY-STEP)).lineage="f"*64
        if fault=="payload":row.payload_json={"chat_id":"another","text":"tampered"}
        if fault=="evidence":row.evidence_hash="f"*64
        if fault=="destination":row.chat_id="-10000000"
        assert prepare(session,state.clock[0],SETTINGS) is None
        assert (row.status,row.error_code)==("skipped",code)


def test_activation_cutoff_prevents_old_signal_broadcast(state):
    committed(state)
    settings=SimpleNamespace(**(vars(SETTINGS)|{"telegram_start_at":state.clock[0]+1}))
    with state.sessions.begin() as session:
        assert prepare(session,state.clock[0],settings) is None
        assert session.scalar(select(func.count()).select_from(TelegramDelivery))==0


def test_interrupted_send_is_unknown_and_never_automatically_retried(state):
    committed(state)
    with state.sessions.begin() as session:job=prepare(session,state.clock[0],SETTINGS)
    with state.sessions.begin() as session:
        recover_interrupted(session)
        assert prepare(session,state.clock[0]+5000,SETTINGS) is None
        row=session.get(TelegramDelivery,job[0]);assert row.status=="unknown" and row.attempts==1


def test_global_rate_limit_wait_and_safe_retry_receipt(state):
    committed(state)
    with state.sessions.begin() as session:
        job=prepare(session,state.clock[0],SETTINGS)
        finish(session,job[0],state.clock[0],error=DeliveryError("RATE_LIMITED","retry",10))
        assert prepare(session,state.clock[0]+5000,SETTINGS) is None
        assert prepare(session,state.clock[0]+10000,SETTINGS)
        finish(session,job[0],state.clock[0]+10001,456)
        assert session.get(TelegramDelivery,job[0]).attempts==2


@pytest.mark.parametrize("prior",["delivered","unknown","failed",None])
def test_source_withdrawal_alert_requires_a_prior_possible_delivery(state,prior):
    identity=committed(state)
    with state.sessions.begin() as session:
        job=prepare(session,state.clock[0],SETTINGS)
        row=session.get(TelegramDelivery,job[0]);row.status=prior or "skipped"
        add_event(session,identity,"source-revised",state.clock[0]+1)
        session.flush()
        next_job=prepare(session,state.clock[0]+5000,SETTINGS)
        if prior in ("delivered","unknown"):
            assert next_job and "WITHDRAWN" in next_job[1]["text"]
        else:
            assert next_job is None
            assert session.scalar(select(TelegramDelivery).where(TelegramDelivery.event_id!=job[0])).error_code=="NO_PRIOR_DELIVERY"


def test_transaction_rollback_leaves_no_partial_delivery_claim(state):
    committed(state)
    with pytest.raises(RuntimeError):
        with state.sessions.begin() as session:
            assert prepare(session,state.clock[0],SETTINGS)
            raise RuntimeError("crash before commit")
    with state.sessions.begin() as session:assert prepare(session,state.clock[0],SETTINGS)


@pytest.mark.parametrize("response,state_expected,code",[(429,"retry","RATE_LIMITED"),(401,"failed","BOT_UNAUTHORIZED"),(403,"failed","CHAT_FORBIDDEN"),(500,"unknown","PROVIDER_UNAVAILABLE")])
def test_provider_failures_are_sanitized(response,state_expected,code):
    def handler(request):return httpx.Response(response,json={"ok":False,"description":SETTINGS.telegram_token,"parameters":{"retry_after":8}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(DeliveryError) as error:await send(client,SETTINGS,{"chat_id":SETTINGS.telegram_chat_id,"text":"test"})
            assert (error.value.state,error.value.code)==(state_expected,code)
            assert SETTINGS.telegram_token not in str(error.value)
    asyncio.run(run())


@pytest.mark.parametrize("exception,expected",[(httpx.ConnectError,"retry"),(httpx.ReadTimeout,"unknown"),(httpx.WriteTimeout,"unknown")])
def test_network_ambiguity_is_not_blindly_retried(exception,expected):
    def handler(request):raise exception("sensitive URL "+str(request.url),request=request)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(DeliveryError) as error:await send(client,SETTINGS,{"chat_id":SETTINGS.telegram_chat_id,"text":"test"})
            assert error.value.state==expected and SETTINGS.telegram_token not in str(error.value)
    asyncio.run(run())


def test_successful_receipt_destination_verification_and_token_not_logged(caplog):
    def handler(request):
        method=request.url.path.rsplit("/",1)[-1]
        result={"getMe":{"id":123456789,"is_bot":True},"getChat":{"id":int(SETTINGS.telegram_chat_id),"type":"supergroup"},
                "getChatMember":{"status":"member"},"sendMessage":{"message_id":32,"chat":{"id":int(SETTINGS.telegram_chat_id)}}}[method]
        return httpx.Response(200,json={"ok":True,"result":result})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),follow_redirects=False) as client:
            assert (await verify_destination(client,SETTINGS))["verified"]
            assert await send(client,SETTINGS,{"chat_id":SETTINGS.telegram_chat_id,"text":"test"})==32
    asyncio.run(run())
    assert SETTINGS.telegram_token not in caplog.text


def test_wrong_chat_receipt_is_uncertain():
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={"ok":True,"result":{"message_id":1,"chat":{"id":42}}}))) as client:
            with pytest.raises(DeliveryError) as error:await send(client,SETTINGS,{"chat_id":SETTINGS.telegram_chat_id,"text":"test"})
            assert error.value.state=="unknown"
    asyncio.run(run())
