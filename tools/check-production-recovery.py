"""Recovery/load checks ONLY against the named local validation project."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]
os.environ["MV_DATABASE_URL"]=(ROOT/"deploy/secrets/database_url").read_text().strip().replace("@db:5432/","@127.0.0.1:55432/")
os.environ["MV_ENVIRONMENT"]="local"
os.environ["MV_AUTH_REQUIRED"]="false"
os.environ.pop("MV_DATABASE_URL_FILE",None)
sys.path.insert(0,str(ROOT/"services/api"))
from app.database import Session
from app.models import IndicatorCheckpoint, EngineCursor, SignalPlan
from sqlalchemy import select

docker=shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
environment={**os.environ,"MV_OWNER_EMAIL":"validation@example.test","MV_PUBLIC_ORIGIN":"https://localhost:3443"}
compose=[docker,"compose","-p","mv-signal-validation","-f","compose.production.yml","-f","compose.validation.yml","--profile","live-validation"]
def command(arguments,check=True):
    return subprocess.run(compose+arguments,cwd=ROOT,env=environment,check=check,capture_output=True,text=True,timeout=90)
def snapshot():
    with Session() as session:
        return {"checkpoints":{r.symbol+":"+r.timeframe:r.state_json for r in session.scalars(select(IndicatorCheckpoint))},
                "cursors":{r.symbol:{"last_open_time":r.last_open_time,"initialized_at":r.initialized_at} for r in session.scalars(select(EngineCursor))},
                "plans":{r.id:{"plan":r.plan_json,"evidence":r.evidence_json,"hash":r.evidence_hash} for r in session.scalars(select(SignalPlan))}}

result={"scope":"Local Linux Docker production configuration, BTC/ETH, 8 concurrent readers; not VPS capacity or an endurance run"}
with httpx.Client(base_url="https://localhost:3443",verify=False,timeout=12) as client:
    response=client.post("/api/auth/login",headers={"Origin":"https://localhost:3443"},json={"email":"owner@mv-validation.example.test","password":"MV private validation password 2026!"})
    response.raise_for_status()
    before=snapshot()
    duplicate=command(["run","--rm","--no-deps","engine","python","-m","app.signals.worker","--once"],check=False)
    assert duplicate.returncode!=0 and "already owns" in duplicate.stderr
    result["duplicate_engine"]="rejected before mutation"
    command(["stop","collector","engine"])
    try:
        subprocess.run([sys.executable,str(ROOT/"tools/backup_database.py"),"--validation","--verify-restore"],cwd=ROOT,check=True)
    finally:
        command(["up","-d","collector","engine"])
    command(["restart","db"])
    # Worker retry/backoff is real; probe with short non-blocking sleeps.
    until=time.monotonic()+85
    ready=False
    while time.monotonic()<until:
        try:
            state=client.get("/api/system").json()
            if state.get("ready"):
                ready=True;break
        except (httpx.HTTPError,ValueError):pass
        time.sleep(1)
    assert ready,"Production workers did not recover within 85 seconds"
    after=snapshot()
    for key,saved in before["checkpoints"].items():
        restored=after["checkpoints"][key]
        assert restored["history_origin"]==saved["history_origin"]
        assert restored["count"]>=saved["count"]
        if restored["count"]==saved["count"]:assert restored==saved
    for symbol,saved in before["cursors"].items():
        assert after["cursors"][symbol]["initialized_at"]==saved["initialized_at"]
        assert after["cursors"][symbol]["last_open_time"]>=saved["last_open_time"]
    for identity,plan in before["plans"].items():assert after["plans"][identity]==plan
    result["database_and_worker_recovery"]="ready; seed origins/cursors/immutable plans preserved"
    result["plans_before"]=len(before["plans"]);result["plans_after"]=len(after["plans"])
    routes=["/api/signals","/api/notifications","/api/history","/api/markets","/api/system"]
    def read(index):
        started=time.perf_counter();response=client.get(routes[index%len(routes)])
        response.raise_for_status()
        return (time.perf_counter()-started)*1000
    with ThreadPoolExecutor(max_workers=8) as pool:latencies=sorted(pool.map(read,range(200)))
    result["read_burst"]={"requests":200,"concurrency":8,"errors":0,"p50_ms":round(statistics.median(latencies),2),"p95_ms":round(latencies[189],2),"p99_ms":round(latencies[197],2),"max_ms":round(latencies[-1],2)}
    client.post("/api/auth/logout",headers={"Origin":"https://localhost:3443"})
target=ROOT/"artifacts/production-validation/recovery-and-load.json"
target.write_text(json.dumps(result,indent=2),encoding="utf-8")
print(json.dumps(result,indent=2))
