#!/usr/bin/env bash
# Migration certification on an EXISTING disposable PostgreSQL CLONE only.
# The script refuses any database not named v7clone_* and never reads,
# copies, backs up, connects to, or modifies live production.
#
# Operator separately creates/populates a private clone from a verified
# production backup; V7_CLONE_URL_FILE contains ONLY its psycopg URL (0600).
# V7_CLONE_MIGRATIONS_APPROVED=YES V7_EXPECTED_SHA=<exact40> \
#   V7_CLONE_URL_FILE=/root/private/v7clone-db-url \
#   bash deploy/v7sonic-rehearse-clone-migrations.sh
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SHA="${V7_EXPECTED_SHA:?Exact reviewed SHA required}"
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]] || exit 2
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "${V7_CLONE_MIGRATIONS_APPROVED:-}" = YES
CLONE_FILE="${V7_CLONE_URL_FILE:?Operator supplied clone-only URL file is required}"
test -f "$CLONE_FILE"
test ! -L "$CLONE_FILE"
test "$(stat -c '%a' "$CLONE_FILE")" = 600
test "$(stat -c '%u' "$CLONE_FILE")" = "$(id -u)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"

# Explicitly reject potentially live names, localhost is allowed ONLY
# when the database NAME proves this is a disposable clone.
python3 - "$CLONE_FILE" <<'PY'
import re,sys
from pathlib import Path
from urllib.parse import urlsplit,unquote
uri=Path(sys.argv[1]).read_text().strip()
u=urlsplit(uri)
db=unquote(u.path.lstrip("/"))
if (u.scheme != "postgresql+psycopg" or
    not u.hostname or not re.fullmatch(r"v7clone_[a-z0-9_]{6,48}",db) or
    not u.username or not u.password or u.query or u.fragment):
    raise SystemExit("STOP: requires exact disposable v7clone_* PostgreSQL database URL, no query overrides")
print("Clone database name: "+db)
print("Live database URL: not consulted")
PY

# We cannot infer that the operator-created clone reflects live schema,
# data or a verified offsite backup. Capture evidence for manual review.
IMAGE="mv-v7sonic-clone-migration:${SHA:0:12}"
echo "=== BUILD SEPARATE MIGRATION REHEARSAL IMAGE ==="
docker build --pull=false -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"
REPORT="$(mktemp "/var/tmp/v7sonic-migration-clone-${SHA:0:12}.XXXXXXXX.log")"
echo "Private persistent CI-equivalent rehearsal report: $REPORT"

run_cloned() {
  docker run --rm --pull=never \
    --network host --read-only \
    --user 10001:10001 --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --memory 512m --pids-limit 64 \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001 \
    --mount "type=bind,source=$CLONE_FILE,target=/run/secrets/v7-clone-url,readonly" \
    -e MV_DATABASE_URL_FILE=/run/secrets/v7-clone-url \
    -e MV_ENVIRONMENT=local \
    -e MV_TELEGRAM_ENABLED=false \
    "$IMAGE" "$@"
}

# Every runtime call validates the actual connected DB (not just URI)
# before performing *any* DDL. The clone must already be at 0008
# with a correctly populated schema, and no V7 tables already present.
echo "=== PROVE CLONE DB IDENTITY AND SOURCE REVISION ===" | tee -a "$REPORT"
run_cloned python - <<'PY' | tee -a "$REPORT"
from app.database import engine
from sqlalchemy import text
with engine.connect() as db:
    actual=db.scalar(text("SELECT current_database()"))
    current=db.scalar(text("SELECT version_num FROM alembic_version"))
    tables={t:db.scalar(text("SELECT to_regclass(:n)"),{"n":t}) for t in (
      "v7_decision_cycles","v7_decision_records","v7_delivery_drafts",
      "v7_client_approvals","v7_client_deliveries")}
    if not actual.startswith("v7clone_") or current!="0008" or any(tables.values()):
        raise SystemExit(f"STOP: clone must start at 0008 without V7 tables: {actual} {current} {tables}")
    print("CLONE INITIAL IDENTITY AND REVISION: PASS",actual,current)
PY

# A fixed staging script must never introduce the publisher: migrations
# only; no automatic service start, bot token or outgoing Telegram.
echo "=== UPGRADE CLONE 0008 -> 0010 ===" | tee -a "$REPORT"
run_cloned python -m alembic -c alembic.ini upgrade 0010 2>&1 | tee -a "$REPORT"
echo "=== VERIFY ADDED V7 TABLES ===" | tee -a "$REPORT"
run_cloned python - <<'PY' | tee -a "$REPORT"
from app.database import engine
from sqlalchemy import text
with engine.connect() as db:
    actual=db.scalar(text("SELECT current_database()"))
    current=db.scalar(text("SELECT version_num FROM alembic_version"))
    required=("v7_decision_cycles","v7_decision_records","v7_delivery_drafts",
              "v7_client_approvals","v7_client_deliveries")
    if not actual.startswith("v7clone_") or current!="0010" or any(
      db.scalar(text("SELECT to_regclass(:n)"),{"n":name}) is None for name in required
    ): raise SystemExit("STOP: clone V7 table/migration reconciliation failed")
    print("CLONE 0010 ADDITIVE TABLES: PASS",actual)
PY
echo "=== DOWNGRADE CLONE 0010 -> 0008 ===" | tee -a "$REPORT"
run_cloned python -m alembic -c alembic.ini downgrade 0008 2>&1 | tee -a "$REPORT"
echo "=== RE-UPGRADE CLONE 0008 -> 0010 ===" | tee -a "$REPORT"
run_cloned python -m alembic -c alembic.ini upgrade 0010 2>&1 | tee -a "$REPORT"
echo "=== VERIFY FINAL CLONE REVISION ===" | tee -a "$REPORT"
run_cloned python - <<'PY' | tee -a "$REPORT"
from app.database import engine
from sqlalchemy import text
with engine.connect() as db:
    actual=db.scalar(text("SELECT current_database()"))
    revision=db.scalar(text("SELECT version_num FROM alembic_version"))
    if not actual.startswith("v7clone_") or revision!="0010":
        raise SystemExit("STOP: clone migration final state mismatch")
    print("CLONE UPGRADE / DOWNGRADE / RE-UPGRADE: PASS",actual)
    print("LIVE DB AND PRODUCTION WORKERS: NOT TOUCHED")
PY
echo "CLONE MIGRATION REHEARSAL COMPLETE; NO PRODUCTION DEPLOYMENT: PASS" | tee -a "$REPORT"
