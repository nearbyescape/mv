"""Controlled UI transport fixture. Every plan originates in the backend engine."""
from pathlib import Path
import sys
import json
from types import SimpleNamespace
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"services/api"))
sys.path.insert(0,str(ROOT/"services/api/tests"))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import WatchlistItem, MarketContract, SignalDecision, SignalPlan, WebNotification
from app.market.store import apply_bars
from app.market import views
from app.signals import service
from app.operations.worker import sync_notifications
from app.signals.service import evaluate_decision, signal_view, engine_health
from mv_strategy.signals import decision_id, STRATEGY_ID
from test_signal_service import seed, pending, publish, fresh_quote, BOUNDARY, STEP

engine=create_engine("sqlite://")
Base.metadata.create_all(engine)
state=SimpleNamespace(sessions=sessionmaker(engine,expire_on_commit=False),clock=[BOUNDARY+1000])
for module in (views,service):module.now_ms=lambda:state.clock[0]
source,confirmation=seed(state)
identity=pending(state);publish(state,identity)
with state.sessions.begin() as session:
    metadata=session.get(MarketContract,"BTCUSDT").metadata_json
    session.add(WatchlistItem(symbol="ETHUSDT",sort_order=1))
    session.add(MarketContract(symbol="ETHUSDT",valid=True,reason="controlled source fixture",checked_at=state.clock[0],metadata_json=metadata))
    apply_bars(session,"ETHUSDT","1h",source,state.clock[0])
    apply_bars(session,"ETHUSDT","4h",confirmation,state.clock[0])
    identity=decision_id("ETHUSDT",BOUNDARY-STEP)
    row=SignalDecision(id=identity,symbol="ETHUSDT",strategy=STRATEGY_ID,source_open_time=BOUNDARY-STEP,outcome="PENDING",reason="test",updated_at=state.clock[0]-2000,expires_at=BOUNDARY+300000,evidence_json={})
    session.add(row);session.flush()
    assert evaluate_decision(session,row,state.clock[0]) is not None
    evaluate_decision(session,row,state.clock[0],replace(fresh_quote(state),symbol="ETHUSDT"))
    assert row.outcome=="PUBLISHED"
with state.sessions.begin() as session:assert sync_notifications(session)==2
with state.sessions() as session:
    plans=list(session.scalars(select(SignalPlan).order_by(SignalPlan.created_at.desc(),SignalPlan.id.desc())))
    signals=[signal_view(session,p,state.clock[0]) for p in plans]
    notices=[{"id":n.id,"signal_id":n.signal_id,"symbol":session.get(SignalPlan,n.signal_id).symbol,"direction":"long","type":n.type,"created_at":n.created_at,"read":False,"status":"active","entry_actionable":True} for n in session.scalars(select(WebNotification))]
    result={"controlled_fixture":True,"feed":{"server_time":state.clock[0],"engine":engine_health(session),"signals":signals,"decisions":[],"slots":[{"symbol":s["symbol"],"signal_id":s["id"],"state":"reserved"} for s in signals]},"notifications":notices}
target=ROOT/"apps/web/tests/fixtures/operations-feed.json"
target.write_text(json.dumps(result,indent=2),encoding="utf-8")
print("Generated two controlled plans through the backend strategy engine.")
