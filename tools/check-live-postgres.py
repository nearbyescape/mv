"""Independent live source/indicator/recovery checks for the local Docker stack."""
import asyncio
from decimal import Decimal, localcontext
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
os.environ["MV_DATABASE_URL"]=(ROOT/"deploy/secrets/database_url").read_text().strip().replace("@db:5432/","@127.0.0.1:55432/")
os.environ["MV_ENVIRONMENT"]="local"
os.environ["MV_AUTH_REQUIRED"]="false"
os.environ.pop("MV_DATABASE_URL_FILE",None)
sys.path.insert(0,str(ROOT/"services/api"))
sys.path.insert(0,str(ROOT/"tools"))
import importlib.util
spec=importlib.util.spec_from_file_location("arithmetic",ROOT/"tools/verify-market-data.py")
arithmetic=importlib.util.module_from_spec(spec);spec.loader.exec_module(arithmetic)
from app.database import Session
from app.market.store import as_bar, history
from app.market.binance import BinancePublic
from app.market.views import collector_health
from app.signals.service import engine_health
from app.models import IndicatorCheckpoint, IndicatorSnapshot, EngineCursor, SignalPlan, WatchlistItem
from sqlalchemy import select
from mv_strategy import IndicatorState
from mv_strategy.signals import STRATEGY_ID
import httpx

async def main():
    results=[]
    with Session() as session:
        assert collector_health(session)["live"]
        assert engine_health(session)["ready"]
        symbols=list(session.scalars(select(WatchlistItem.symbol)))
    async with httpx.AsyncClient(timeout=20) as client:
        public=BinancePublic(client)
        for symbol in symbols:
            for frame in ("1h","4h"):
                with Session() as session:
                    source=[as_bar(c) for c in history(session,symbol,frame)]
                    saved=session.get(IndicatorCheckpoint,(symbol,frame)).state_json
                    snapshot=session.get(IndicatorSnapshot,(symbol,frame,source[-1].open_time))
                    values={k:Decimal(getattr(snapshot,k)) for k in ("ema20","ema50","sma200","atr")}
                replay=IndicatorState(frame)
                for bar in source:replay.advance(bar)
                assert replay.dump()==saved
                for key,value in arithmetic.independent_values(source).items():
                    with localcontext() as ctx:
                        ctx.prec=60;exact=Decimal(value.numerator)/Decimal(value.denominator)
                        assert abs(values[key]-exact)<=Decimal("1e-28")*max(Decimal(1),abs(exact)),key
                direct=await public.klines(symbol,frame,end_time=source[-1].close_time,limit=3)
                assert [bar.digest() for bar in source[-3:]]==[bar.digest() for bar in direct]
                results.append({"symbol":symbol,"timeframe":frame,"bars":len(source),"origin":saved["history_origin"],"lineage":saved["lineage"],"direct_last_three":"exact","independent_indicators":"passed","checkpoint_replay":"bit-for-bit"})
    with Session() as session:
        cursors=[{"symbol":r.symbol,"last_open_time":r.last_open_time,"initialized_at":r.initialized_at} for r in session.scalars(select(EngineCursor).where(EngineCursor.strategy==STRATEGY_ID))]
        plans=list(session.scalars(select(SignalPlan.id)))
    output=ROOT/"artifacts/production-validation/live-market-checks.json"
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps({"streams":results,"cursors":cursors,"published_plan_ids":plans,"execution":"signals-only; no orders"},indent=2),encoding="utf-8")
    print(json.dumps({"streams":results,"cursors":cursors,"plans":len(plans)},indent=2))
asyncio.run(main())
