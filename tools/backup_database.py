"""Custom-format PostgreSQL backup. Restore checks use a NEW disposable database."""
import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument("--validation",action="store_true",help="Use the isolated loopback validation stack")
parser.add_argument("--verify-restore",action="store_true",help="Restore into a new temporary database and compare critical table bytes")
args=parser.parse_args()
docker=shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if args.validation:
    os.environ.update(MV_OWNER_EMAIL="validation@example.test",MV_PUBLIC_ORIGIN="https://localhost:3443")
    compose=[docker,"compose","-p","mv-signal-validation","-f","compose.production.yml","-f","compose.validation.yml"]
else:
    compose=[docker,"compose","--env-file","deploy/production.env","-f","compose.production.yml"]
def run(command,**kwargs):
    return subprocess.run(compose+["exec","-T","db"]+command,cwd=ROOT,check=True,**kwargs)

directory=ROOT/"deploy"/"backups"
directory.mkdir(parents=True,exist_ok=True)
if os.name!="nt":directory.chmod(0o700)
stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
backup=directory/("mv-signal-"+stamp+".dump")
partial=backup.with_suffix(".partial")
with partial.open("xb") as target:
    if os.name!="nt":partial.chmod(0o600)
    run(["pg_dump","-U","postgres","-d","mv_signal","-Fc","--no-owner"],stdout=target)
partial.rename(backup)
with backup.open("rb") as source:
    hasher=hashlib.sha256()
    for chunk in iter(lambda:source.read(1024*1024),b""):
        hasher.update(chunk)
    checksum=hasher.hexdigest()
backup.with_suffix(".dump.sha256").write_text(checksum+"  "+backup.name+"\n",encoding="utf-8")
print("Backup written:",backup.name,"SHA256:",checksum)
if args.verify_restore:
    # This command never restores over mv_signal, never drops an existing DB,
    # and only cleans the unique DB successfully created during this invocation.
    restored="mv_restore_verify_"+stamp.lower()
    assert re.fullmatch(r"mv_restore_verify_[a-z0-9]+",restored)
    run(["createdb","-U","postgres","-O","mv",restored])
    try:
        with backup.open("rb") as source:
            run(["pg_restore","-U","postgres","-d",restored,"--no-owner","--role=mv","--exit-on-error"],stdin=source)
        critical = [("watchlist","symbol"),("users","id"),("signal_plans","id"),("signal_events","id"),("signal_decisions","id"),("signal_slots","symbol,strategy"),("candles","symbol,timeframe,open_time"),("indicator_snapshots","symbol,timeframe,open_time"),("engine_cursors","symbol,strategy"),("indicator_checkpoints","symbol,timeframe")]
        version = run(["psql","-U","postgres","-d","mv_signal","-At","-c","SELECT version_num FROM alembic_version"],capture_output=True).stdout.decode().strip()
        if version in ("0005","0006","0007"):
            critical.extend([("ai_reviews","signal_id"),("ai_requests","id")])
        if version in ("0006","0007"):
            critical.extend([("telegram_deliveries","event_id")])
        if version == "0007":
            critical.extend([("signal_outcomes","signal_id"),("decision_opportunities","decision_id")])
        critical.extend([("web_notifications","id"),("notification_reads","user_id,notification_id"),("user_sessions","token_hash"),("invites","token_hash"),("market_contracts","symbol"),("audit_events","id")])
        for table,order in critical:
            sql=f"COPY (SELECT row_to_json(t) FROM (SELECT * FROM {table} ORDER BY {order}) t) TO STDOUT"
            original=run(["psql","-U","postgres","-d","mv_signal","-q","-c",sql],capture_output=True).stdout
            copy=run(["psql","-U","postgres","-d",restored,"-q","-c",sql],capture_output=True).stdout
            if original!=copy:raise SystemExit("Restore differs from current "+table+"; stop workers before a consistency comparison")
        print(f"Restore verified: all {len(critical)} critical tables match byte-for-byte.")
    finally:
        run(["dropdb","-U","postgres",restored])
