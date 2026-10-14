#!/usr/bin/env bash
# Operator-only one-shot existing MV subscriber-channel transport test.
# NOT the private Telegram gate; no strategy signals, DB, V4/V7 services, orders.
# --verify calls only Telegram getMe/getChat/getChatMember;
# --send sends a SINGLE immutable "DO NOT TRADE" diagnostic payload,
# with irreversible durable marker acquired BEFORE send attempt.
set -Eeuo pipefail
umask 077

MODE="${1:-}"
case "$MODE" in --preflight|--verify|--send) ;; *)
  echo "Usage: $0 --preflight|--verify|--send" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SHA="${V7_EXPECTED_SHA:?Exact 40-hex reviewed SHA mandatory}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
test "$(id -u)" -eq 0
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = /opt/mv-signal/releases/mv-signal-0.14.0

check_service_stop(){
  local svc="$1" cid
  mapfile -t CIDS < <(docker ps -aq \
    --filter label=com.docker.compose.project=mv-signal \
    --filter "label=com.docker.compose.service=$svc")
  if test "$svc" = engine || test "$svc" = telegram; then
    test "${#CIDS[@]}" -eq 1
  else
    test "${#CIDS[@]}" -le 1
  fi
  for cid in "${CIDS[@]}"; do
    test "$(docker inspect -f '{{.State.Running}}' "$cid")" = false
    if test "$svc" = engine; then
      test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$cid")" = no
    fi
  done
  if test "$svc" = telegram; then BOT="${CIDS[0]}"; fi
}
check_service_stop engine
check_service_stop telegram
check_service_stop telegram-report
check_service_stop ai

mapfile -t IDS < <(docker inspect "$BOT" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' |
  sed -n 's/^MV_TELEGRAM_CHAT_ID=//p')
test "${#IDS[@]}" -eq 1
CLIENT="${IDS[0]}"
[[ "$CLIENT" =~ ^-?[1-9][0-9]{0,15}$ ]] || exit 3

echo "Production V4 and MV Telegram sender: STOPPED"
echo "Existing client destination found in stopped container configuration."

if test "$MODE" = --preflight; then
  echo "Existing-client diagnostic preflight: PASS"
  echo "No Telegram calls and no message sent."
  exit 0
fi

test "${V7_EXISTING_TELEGRAM_TEST_OPERATOR_APPROVED:-}" = YES || {
  echo "STOP: explicit existing-client transport diagnostic approval required" >&2
  exit 3
}
test "${V7_EXISTING_CLIENT_CHAT_ACK:-}" = "$CLIENT" || {
  echo "STOP: manually acknowledged channel ID differs from production client channel" >&2
  exit 3
}
if test "$MODE" = --send; then
  test "${V7_EXISTING_TELEGRAM_ONE_SEND_APPROVED:-}" = YES || {
    echo "STOP: one-time client-channel DO NOT TRADE send not explicitly authorized" >&2
    exit 3
  }
fi

TOKEN_SOURCE="$(docker inspect "$BOT" --format \
  '{{range .Mounts}}{{if eq .Destination "/run/secrets/telegram_token"}}{{.Source}}{{end}}{{end}}')"
test -n "$TOKEN_SOURCE"
TOKEN="$(readlink -e "$TOKEN_SOURCE")"
python3 - "$TOKEN" <<'PY'
import os,stat,sys
p=sys.argv[1]
s=os.stat(p,follow_symlinks=False)
if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)&0o077:
    raise SystemExit("STOP: root-owned non-world/group-readable token file required")
PY

IMAGE="mv-v7sonic-auditor:${SHA:0:12}"
docker image inspect "$IMAGE" >/dev/null
STATE="/var/tmp/v7sonic-existing-client-telegram-one-time-test"
if test ! -e "$STATE"; then
  install -d -m 0700 "$STATE"
fi
test -d "$STATE" && test ! -L "$STATE"
test "$(stat -c '%a' "$STATE")" = 700
test "$(stat -c '%u' "$STATE")" -eq 0

WORK="$(mktemp -d /var/tmp/v7sonic-client-diag-XXXXXXXX)"
chown 10001:10001 "$WORK"
chmod 0700 "$WORK"
trap 'rm -rf -- "$WORK"' EXIT
install -o 10001 -g 10001 -m 0400 "$TOKEN" "$WORK/token"

run_diag(){
  docker run --rm --pull=never \
    --network bridge --read-only --user 10001:10001 \
    --cap-drop ALL --security-opt no-new-privileges:true \
    --memory 256m --pids-limit 32 \
    --mount "type=bind,source=$WORK/token,target=/run/secrets/diag-bot-token,readonly" \
    -e V7_EXISTING_TELEGRAM_TEST_OPERATOR_APPROVED=YES \
    -e V7_EXISTING_TELEGRAM_ONE_SEND_APPROVED="${V7_EXISTING_TELEGRAM_ONE_SEND_APPROVED:-NO}" \
    "$IMAGE" python -m app.v7sonic_existing_telegram_transport_test \
      "$1" --client-chat-id "$CLIENT" \
      --bot-token-file /run/secrets/diag-bot-token
}
check_report(){
  python3 - "$1" "$2" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
stage=sys.argv[2]
v=p["verification"]
assert v["verified"] is True
assert v["chat_type"] in ("group","supergroup","channel")
assert p["actual_trading_signal_published"] is False
assert p["v7_production_cutover_authorized"] is False
assert p["private_channel_certification"] is False
assert p["orders_submitted"] == 0
if stage=="verify":
    assert p["status"]=="V7_EXISTING_CLIENT_CHANNEL_VERIFIED_NO_SEND"
    assert p["test_message_id"] is None
    print("EXISTING MV TELEGRAM BOT/DESTINATION: VERIFIED")
    print("No message sent")
else:
    assert p["status"]=="V7_EXISTING_CLIENT_CHANNEL_TEST_SENT_DO_NOT_TRADE"
    assert type(p["test_message_id"]) is int and p["test_message_id"] > 0
    print("ONE DO NOT TRADE TEST DELIVERED TO EXISTING CHANNEL")
    print("Telegram message ID:",p["test_message_id"])
print("Chat type:",v["chat_type"])
print("Bot permission:",v.get("bot_status"))
PY
}

echo "=== VERIFY REAL BOT, EXACT EXISTING CHANNEL, AND POSTING RIGHTS ==="
run_diag --verify-existing > "$WORK/verify.json"
check_report "$WORK/verify.json" verify
if test "$MODE" = --verify; then
  echo "EXISTING-CHANNEL VERIFY: PASS (NO CLIENT MESSAGE SENT)"
  exit 0
fi

# Durable marker is GLOBAL, not per SHA, to avoid accidental duplicate sends
# across source revisions. Once created, never auto-retry even on unknown.
MARKER="$STATE/send-attempted"
( set -C; printf 'An explicitly authorized existing-channel test was attempted; NEVER AUTO-RETRY. Source %s\n' "$SHA" > "$MARKER" ) || {
  echo "STOP: existing-client test was previously attempted. Never repeat automatically." >&2
  exit 4
}
check_service_stop engine
check_service_stop telegram
check_service_stop telegram-report
echo "=== SEND ONE NONTRADING DIAGNOSTIC TO EXISTING SUBSCRIBER CHANNEL ==="
run_diag --send-one-existing > "$WORK/send.json"
check_report "$WORK/send.json" send
install -o root -g root -m 0600 "$WORK/send.json" "$STATE/provider-receipt.json"
echo "EXISTING-CLIENT-CHANNEL ONE-SHOT TRANSPORT TEST: PASS"
echo "Provider receipt: $STATE/provider-receipt.json"
echo "Private-channel certification: NOT PERFORMED"
echo "Production trading signals, order routing and V4 restart: DISABLED"
