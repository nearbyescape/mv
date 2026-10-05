import asyncio
import json
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select, func
from app.ai.provider import ReviewError, evidence_payload, validate_commentary, request_review
from app.ai.worker import prepare, finish, recover_interrupted
from app.models import AIRequest, AIReview, SignalPlan
from test_signal_service import state, seed, pending, publish

SETTINGS = SimpleNamespace(ai_model="deepseek/deepseek-v4-pro-0813",ai_daily_requests=2,
                           openrouter_key="test-server-only",public_origin="https://test.invalid")

def committed(state):
    seed(state)
    identity = pending(state)
    publish(state,identity)
    return identity

def commentary(payload):
    return {"assessment":"consistent","summary":"The completed candle ordering and confirmation agree with the recorded direction.",
            "check_ids":[next(c["id"] for c in payload["checks"] if c["passed"])],
            "limitations":["Reference quotes are not assured fills."]}

def test_persisted_request_before_network_and_commentary_never_changes_financial_plan(state):
    identity = committed(state)
    with state.sessions.begin() as session:
        plan = session.get(SignalPlan,identity)
        original = json.dumps([plan.plan_json,plan.evidence_json,plan.evidence_hash],sort_keys=True)
        job = prepare(session,state.clock[0],SETTINGS)
    with state.sessions.begin() as session:
        assert session.get(AIRequest,job[0]).status == "inflight"
        assert prepare(session,state.clock[0],SETTINGS) is None
        finish(session,job[0],identity,state.clock[0],commentary(job[2]),{"cost":0.001})
        finish(session,job[0],identity,state.clock[0],{"summary":"overwrite attempt"})
    with state.sessions() as session:
        plan = session.get(SignalPlan,identity)
        assert json.dumps([plan.plan_json,plan.evidence_json,plan.evidence_hash],sort_keys=True)==original
        assert session.get(AIReview,identity).response_json == commentary(job[2])

def test_daily_limit_survives_restart_and_network_ambiguity_is_not_rebilled(state):
    identity = committed(state)
    with state.sessions.begin() as session:
        job = prepare(session,state.clock[0],SETTINGS)
        finish(session,*job[:2],state.clock[0],error=ReviewError("HTTP_503",True))
    now = state.clock[0]+120_001
    with state.sessions.begin() as session:
        job = prepare(session,now,SETTINGS)
        assert job is not None
        recover_interrupted(session,now)
        assert session.get(AIReview,identity).status == "failed"
        assert prepare(session,now+120_001,SETTINGS) is None
        assert session.scalar(select(func.count()).select_from(AIRequest)) == 2

def test_bound_to_exact_immutable_evidence_and_tampered_completion_hidden(state):
    identity = committed(state)
    with state.sessions.begin() as session:
        job = prepare(session,state.clock[0],SETTINGS)
    with state.sessions.begin() as session:
        plan = session.get(SignalPlan,identity)
        plan.evidence_hash = "f"*64
        finish(session,*job[:2],state.clock[0],commentary(job[2]))
    with state.sessions() as session:
        assert session.get(AIReview,identity).status == "invalidated"
        assert session.get(AIReview,identity).response_json is None

@pytest.mark.parametrize("change,code",[
    ({"check_ids":["invented"]},"UNSUPPORTED_CHECK_REFERENCE"),
    ({"entry":"123"},"INVALID_SCHEMA"),
    ({"summary":"<script>malicious commentary</script>"},"INVALID_COMMENTARY"),
    ({"summary":"This strategy has guaranteed returns."},"INVALID_COMMENTARY"),
])
def test_schema_and_evidence_reference_rejections(state,change,code):
    identity = committed(state)
    with state.sessions() as session:
        payload = evidence_payload(session.get(SignalPlan,identity))
    content = commentary(payload)
    content.update(change)
    with pytest.raises(ReviewError) as error:
        validate_commentary(json.dumps(content),payload)
    assert error.value.code == code

def test_provider_budget_auth_schema_and_no_key_in_stored_output(state):
    identity = committed(state)
    with state.sessions() as session:
        payload = evidence_payload(session.get(SignalPlan,identity))
    def handler(request):
        body = json.loads(request.content)
        assert request.headers["Authorization"] == "Bearer test-server-only"
        assert body["max_tokens"]==800 and body["provider"]["require_parameters"]
        assert body["provider"]["max_price"] == {"prompt":1,"completion":5}
        assert "test-server-only" not in json.dumps(body)
        return httpx.Response(200,json={"choices":[{"finish_reason":"stop","message":{"content":json.dumps(commentary(payload))}}],
            "usage":{"cost":0.001,"prompt_tokens":100,"secret":"not-stored"},"id":"provider-id","model":SETTINGS.ai_model})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result,usage = await request_review(client,SETTINGS,payload)
            assert result==commentary(payload) and "secret" not in usage
    asyncio.run(check())

@pytest.mark.parametrize("status,retry",[(401,False),(402,False),(429,True),(503,True)])
def test_provider_errors_have_redacted_codes(state,status,retry):
    identity = committed(state)
    with state.sessions() as session:
        payload = evidence_payload(session.get(SignalPlan,identity))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(status,text="sensitive provider body"))) as client:
            with pytest.raises(ReviewError) as error:
                await request_review(client,SETTINGS,payload)
            assert error.value.code == "HTTP_"+str(status) and error.value.retryable is retry
    asyncio.run(check())
