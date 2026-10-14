#!/usr/bin/env bash
# One-time offline restore and Alembic rehearsal for a SHA-pinned MV backup.
# No production database access, host ports, Telegram, orders or deployment.
set -Eeuo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
SHA="$V7_EXPECTED_SHA"
NAME="$V7_BACKUP_NAME"
DIGEST="$V7_BACKUP_SHA256"
test "$V7_DISPOSABLE_RESTORE_APPROVED" = YES
[[ "$SHA" =~ ^[a-f0-9]{40}$ ]]
[[ "$DIGEST" =~ ^[a-f0-9]{64}$ ]]
[[ "$NAME" =~ ^mv-signal-[0-9]{8}T[0-9]{6}Z[.]dump$ ]]
test "$(id -u)" = 0
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = "/opt/mv-signal/releases/mv-signal-0.14.0"
test "$(docker inspect -f '{{.State.Running}}' mv-signal-engine-1)" = false
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' mv-signal-engine-1)" = no

BKP="$(docker ps -aq --filter label=com.docker.compose.project=mv-signal --filter label=com.docker.compose.service=backup)"
test "$(wc -w <<< "$BKP")" -eq 1
MOUNT="$(docker inspect "$BKP" --format '{{range .Mounts}}{{if eq .Destination "/backups"}}{{.Source}}{{end}}{{end}}')"
DIR="$(readlink -e "$MOUNT")"
test "$DIR" = "/opt/mv-signal/shared/backups"
DUMP="$DIR/$NAME"
test -f "$DUMP" && test ! -L "$DUMP"
test -f "$DUMP.sha256" && test ! -L "$DUMP.sha256"
test "$(sha256sum "$DUMP" | cut -d' ' -f1)" = "$DIGEST"
read -r SIDECAR _ < "$DUMP.sha256"
test "$SIDECAR" = "$DIGEST"

PGIMAGE="postgres:18.6-bookworm@sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650"
docker image inspect "$PGIMAGE" >/dev/null
WORK="$(mktemp -d /var/tmp/v7airgap-XXXXXXXX)"
TOKEN="$(openssl rand -hex 5)"
DB="v7clone_$TOKEN"
CID="mv-v7clone-$TOKEN"
PASSWORD="$(openssl rand -hex 32)"
printf '%s\n' "$PASSWORD" > "$WORK/pw"
printf 'postgresql+psycopg://postgres:%s@127.0.0.1:5432/%s\n' "$PASSWORD" "$DB" > "$WORK/url"
chmod 0600 "$WORK/pw"
chown 10001:10001 "$WORK/url"
chmod 0400 "$WORK/url"
unset PASSWORD
cleanup() {
  rc=$?
  trap - EXIT
  if docker container inspect "$CID" >/dev/null 2>&1; then
    docker rm -f -v "$CID" >/dev/null || rc=1
  fi
  rm -rf -- "$WORK"
  if test "$rc" -ne 0; then echo 'AIRGAPPED CLONE REHEARSAL FAILED CLOSED; PRODUCTION UNTOUCHED' >&2; fi
  exit "$rc"
}
trap cleanup EXIT

echo '=== CREATE PG18 DISPOSABLE CLONE, NO HOST NETWORK/PORTS ==='
docker run -d --name "$CID" --network none \
  --label "v7.airgapped_clone=$DB" \
  --tmpfs /var/lib/postgresql:rw,nosuid,size=1073741824 \
  --shm-size 128m --memory 768m --pids-limit 128 \
  --mount "type=bind,source=$DUMP,target=/input/mv.dump,readonly" \
  --mount "type=bind,source=$WORK/pw,target=/run/secrets/clone-pw,readonly" \
  -e POSTGRES_USER=postgres -e "POSTGRES_DB=$DB" \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/clone-pw \
  "$PGIMAGE" postgres -c listen_addresses=127.0.0.1 >/dev/null
test "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CID")" = none
test "$(docker inspect -f '{{index .Config.Labels "v7.airgapped_clone"}}' "$CID")" = "$DB"
test -z "$(docker port "$CID")"
READY=NO
for _ in $(seq 1 90); do
  if docker exec "$CID" pg_isready -h 127.0.0.1 -U postgres -d "$DB" >/dev/null 2>&1; then READY=YES; break; fi
  sleep 1
done
test "$READY" = YES
query() {
  docker exec -u postgres "$CID" psql -X -U postgres -d "$DB" -qAt -v ON_ERROR_STOP=1 -c "$1"
}
revision() { query 'SELECT version_num FROM alembic_version'; }

echo '=== RESTORE PINNED BACKUP INTO ISOLATED CLONE ==='
docker exec "$CID" pg_restore --list /input/mv.dump >/dev/null
docker exec -u postgres "$CID" pg_restore --exit-on-error --no-owner --no-acl \
  -U postgres -d "$DB" /input/mv.dump
test "$(revision)" = 0008

manifest() {
  tables="$(query "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' AND left(tablename,3)<>'v7_' AND tablename<>'alembic_version' ORDER BY tablename")"
  test -n "$tables"
  query "SELECT table_name || ':' || column_name || ':' || data_type || ':' || is_nullable || ':' || ordinal_position FROM information_schema.columns WHERE table_schema='public' AND left(table_name,3)<>'v7_' AND table_name<>'alembic_version' ORDER BY table_name,ordinal_position"
  while IFS= read -r table; do
    [[ "$table" =~ ^[a-z_][a-z0-9_]*$ ]] || return 1
    count="$(query "SELECT count(*) FROM public.\"$table\"")"
    [[ "$count" =~ ^[0-9]+$ ]] || return 1
    echo "$table:$count"
  done <<< "$tables"
}
manifest > "$WORK/baseline"
BASELINE="$(sha256sum "$WORK/baseline" | cut -d' ' -f1)"
echo "RESTORE PG REVISION: 0008; LEGACY BASELINE SHA256: $BASELINE"

IMAGE="mv-v7-clone:$(echo "$SHA" | cut -c1-12)"
docker build --pull=false -f "$ROOT/services/api/Dockerfile" -t "$IMAGE" "$ROOT"
migrate() {
  test "$(revision)" = "$3"
  test "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CID")" = none
  docker run --rm --pull=never --network "container:$CID" --read-only \
    --user 10001:10001 --cap-drop ALL --security-opt no-new-privileges:true \
    --memory 512m --pids-limit 64 \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=67108864,uid=10001,gid=10001 \
    --mount "type=bind,source=$WORK/url,target=/run/secrets/v7-url,readonly" \
    -e MV_DATABASE_URL_FILE=/run/secrets/v7-url \
    -e MV_ENVIRONMENT=local -e MV_TELEGRAM_ENABLED=false \
    "$IMAGE" python -m alembic -c alembic.ini "$1" "$2"
}
verify() {
  test "$(revision)" = "$1"
  for table in v7_decision_cycles v7_decision_records v7_delivery_drafts v7_client_approvals v7_client_deliveries; do
    found="$(query "SELECT to_regclass('public.$table') IS NOT NULL")"
    if test "$1" = 0010; then test "$found" = t; else test "$found" = f; fi
  done
  manifest > "$WORK/current"
  cmp -s "$WORK/baseline" "$WORK/current"
  echo "Alembic $1, required V7 DDL, all legacy table counts/columns: PASS"
}
echo '=== 0008 -> 0010 ==='
migrate upgrade 0010 0008
verify 0010
echo '=== 0010 -> 0008 ==='
migrate downgrade 0008 0010
verify 0008
echo '=== 0008 -> 0010 AGAIN ==='
migrate upgrade 0010 0008
verify 0010
echo 'AIRGAPPED MV BACKUP RESTORE AND V7 MIGRATION ROUNDTRIP: PASS'
echo "BACKUP SHA256: $DIGEST"
echo "LEGACY FINGERPRINT SHA256: $BASELINE"
echo 'Offsite copy and profitability: NOT VERIFIED'
echo 'Disposable clone will be destroyed; production database unchanged'
