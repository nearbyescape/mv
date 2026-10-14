#!/usr/bin/env bash
# V7Sonic Telegram *PRIVATE GROUP* transport test, never a signal publisher.
# One operator-approved text-only test; no DB, Binance, client sends or V4.
# Existing production Telegram service must be stopped. Its actual client
# destination is obtained internally, NEVER echoed or set by the operator.
#
# First: V7_EXPECTED_SHA=<40sha> V7_PRIVATE_TEST_CHAT_ID=<private group ID> \
#          bash deploy/v7sonic-private-telegram-transport.sh --verify
# Then, only after reviewing verification and within same exact SHA:
#        V7_EXPECTED_SHA=<40sha> V7_PRIVATE_TEST_CHAT_ID=<same ID> \
#          V7_PRIVATE_ONE_TEST_SEND_APPROVED=YES \
#          bash deploy/v7sonic-private-telegram-transport.sh --send
#
# A send attempt is marked BEFORE contacting Telegram and never retried
# automatically, even if the provider outcome is unknown.
set -Eeuo pipefail
umask 077

MODE="${1:-}"
case "$MODE" in
  --preflight|--verify|--send) ;;
  *) echo "Usage: $0 --preflight|--verify|--send" >&2; exit 2 ;;
esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SHA="${V7_EXPECTED_SHA:?40-digit reviewed commit required}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || exit 2
test "$(id -u)" -eq 0
test "$(git -C "$ROOT" rev-parse HEAD)" = "$SHA"
test -z "$(git -C "$ROOT" status --porcelain)"
test "$(readlink -f /opt/mv-signal/app)" = /opt/mv-signal/releases/mv-signal-0.14.0

mapfile -t ENGINES < <(docker ps -aq \
  --filter label=com.docker.compose.project=mv-signal \
  --filter label=com.docker.compose.service=engine)
test "${#ENGINES[@]}" -eq 1
test "$(docker inspect -f '{{.State.Running}}' "${ENGINES[0]}")" = false
test "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "${ENGINES[0]}")" = no

# Inspect actual stopped production Telegram service, not an operator-supplied
# client denylist. Refuse absent, duplicate or running clients.
mapfile -t BOTS < <(docker ps -aq \
  --filter label=com.docker.compose.project=mv-signal \
  --filter label=com.docker.compose.service=telegram)
test "${#BOTS[@]}" -eq 1 || {
  echo "STOP: exactly one stopped MV Telegram service required" >&2
  exit 3
}
BOT="${BOTS[0]}"
test "$(docker inspect -f '{{.State.Running}}' "$BOT")" = false

mapfile -t DESTS < <(docker inspect "$BOT" \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | \
  sed -n 's/^MV_TELEGRAM_CHAT_ID=//p')
test "${#DESTS[@]}" -eq 1
CLIENT="${DESTS[0]}"
[[ "$CLIENT" =~ ^-?[1-9][0-9]{0,15}$ ]] || exit 3

if test "$MODE" = --preflight; then
  echo "Production Telegram service: STOPPED"
  echo "Client destination is internally identified and never displayed"
  echo "Network requests: 0; messages: 0"
  echo "Next: create a NEW dedicated Telegram supergroup named V7Sonic Private Test, containing only operator(s) and this bot, and supply its numeric chat ID privately on the VPS."
  exit 0
fi

GROUP="${V7_PRIVATE_TEST_CHAT_ID:-}"
[[ "$GROUP" =~ ^-[1-9][0-9]{6,15}$ ]] || {
  echo "STOP: explicitly set numeric negative private supergroup/group chat ID" >&2
  exit 3
}
test "$GROUP" != "$CLIENT" || {
  echo "STOP: private test destination equals actual client destination" >&2
  exit 3
}
# Additional operator acknowledgement required for any network request.
test "${V7_PRIVATE_TELEGRAM_OPERATOR_APPROVED:-}" = YES || {
  echo "STOP: V7_PRIVATE_TELEGRAM_OPERATOR_APPROVED=YES required" >&2
  exit 3
}

SECRET_MOUNT="$(docker inspect "$BOT" \
  --format '{{range .Mounts}}{{if eq .Destination "/run/secrets/telegram_token"}}{{.Source}}{{end}}{{end}}')"
test -n "$SECRET_MOUNT"
TOKEN="$(readlink -e "$SECRET_MOUNT")"
test -f "$TOKEN"
test ! -L "$TOKEN"
test "$(stat -c '%u' "$TOKEN")" -eq 0
test $(( 8#$(stat -c '%a' "$TOKEN") & 8#077 )) -eq 0

IMAGE="mv-v7sonic-auditor:${SHA:0:12}"
docker image inspect "$IMAGE" >/dev/null

STATE="/var/tmp/v7sonic-private-telegram-${SHA:0:12}"
if test ! -d "$STATE"; then
  test ! -e "$STATE" && test ! -L "$STATE"
  install -d -m 0700 "$STATE"
fi
test -d "$STATE" && test ! -L "$STATE"
test "$(stat -c '%u' "$STATE")" -eq 0
test "$(stat -c '%a' "$STATE")" = 700

WORK="$(mktemp -d /var/tmp/v7-private-token-XXXXXXXX)"
chown 10001:10001 "$WORK"
chmod 0700 "$WORK"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
install -o 10001 -g 10001 -m 0400 "$TOKEN" "$WORK/bot-token"

run_private() {
  docker run --rm --pull=never \
    --network bridge --read-only \
    --user 10001:10001 --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --memory 256m --pids-limit 32 \
    --mount "type=bind,source=$WORK/bot-token,target=/run/secrets/v7-token,readonly" \
    -e V7_PRIVATE_TELEGRAM_OPERATOR_APPROVED=YES \
    "$IMAGE" python -m app.v7sonic_private_telegram_certification \
      "$1" \
      --private-chat-id "$GROUP" \
      --client-chat-id "$CLIENT" \
      --bot-token-file /run/secrets/v7-token
}

echo "=== VERIFY EXACT PRIVATE GROUP WITH REAL TELEGRAM GETME/GETCHAT/GETCHATMEMBER ==="
run_private --verify-private > "$WORK/verified.json"
python3 - "$WORK/verified.json" "$GROUP" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
v=p.get("verification",{})
assert p["status"] == "V7_PRIVATE_TELEGRAM_DESTINATION_VERIFIED_ONLY"
assert v.get("verified") is True and v.get("chat_id") == sys.argv[2]
assert v.get("chat_type") in ("group","supergroup"), "Dedicated group required"
assert p["private_test_message_id"] is None
assert p["client_destination_used"] is False
assert p["candidate_or_trading_signal_published"] is False
assert p["production_cutover_authorized"] is False
print("BOT IDENTITY, GROUP DESTINATION AND POSTING PERMISSION: VERIFIED")
print("Group type:",v["chat_type"])
print("Bot status:",v["bot_status"])
print("NO CLIENT PUBLICATION; NO TEST MESSAGE YET")
PY

if test "$MODE" = --verify; then
  echo "PRIVATE TELEGRAM PROVIDER VERIFICATION: PASS"
  exit 0
fi

test "${V7_PRIVATE_ONE_TEST_SEND_APPROVED:-}" = YES || {
  echo "STOP: explicit approval for ONE DO NOT TRADE test message required" >&2
  exit 3
}
# Make this a ONE-SHOT test per source commit. If provider result is
# uncertain, the durable marker remains: never automatically resend.
MARKER="$STATE/one-shot-send-attempted"
( set -C; printf 'Test-chat transport send attempted under SHA %s\n' "$SHA" > "$MARKER" ) || {
  echo "STOP: test send was already attempted; never automatically retry" >&2
  exit 4
}
echo "=== SEND ONE PRIVATE DO NOT TRADE TEXT (NO SIGNAL, NO DATABASE) ==="
run_private --send-private-test > "$WORK/result.json"
python3 - "$WORK/result.json" "$GROUP" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
assert p["status"]=="V7_PRIVATE_TELEGRAM_TEST_SENT_NOT_CLIENT"
assert p["verification"]["chat_id"]==sys.argv[2]
assert p["verification"]["chat_type"] in ("group","supergroup")
assert type(p["private_test_message_id"]) is int and p["private_test_message_id"]>0
assert p["client_destination_used"] is False
assert p["candidate_or_trading_signal_published"] is False
assert p["orders_submitted"]==0
assert p["production_cutover_authorized"] is False
print("ONE PRIVATE TEST MESSAGE DELIVERED, NOT CLIENT:",p["private_test_message_id"])
print("Client publication: DISABLED")
PY
install -o root -g root -m 0600 "$WORK/result.json" "$STATE/private-transport-receipt.json"
echo "ONE-SHOT PRIVATE TELEGRAM PROVIDER RECEIPT: PASS"
echo "Private receipt: $STATE/private-transport-receipt.json"
echo "V4 / production PostgreSQL / Binance order routing: UNTOUCHED"
