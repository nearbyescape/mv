"""One explicitly authorized DO NOT TRADE transport test to existing client Telegram.

Separate from private-chat certification and all V7 trading publication code.
No DB, no exchange, no scheduler, no portfolio state, no executable signal.
Default CLI operation is zero network. A one-shot lock is owned by the
operator-only VPS wrapper and is acquired BEFORE sending.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace

import httpx

from app.telegram.provider import verify_destination, send

_CHAT = re.compile(r"-?[1-9][0-9]{0,15}\Z")
_TOKEN = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,150}\Z")

TEST_TEXT = (
    "⚠️ TEST ONLY — DO NOT TRADE\n\n"
    "MV Intelligent Model V7Sonic — Telegram transport verification.\n"
    "This is a connectivity test, NOT a trading signal.\n"
    "No entry, stop loss, take profit or trade is being recommended.\n"
    "V7Sonic production publication remains disabled."
)


def private_bot_token(path_str: str) -> str:
    path = Path(path_str)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PermissionError("An absolute non-symlink token file is mandatory")
    stat = path.stat()
    if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise PermissionError("Private token file owned by worker is required")
    if not 30 <= stat.st_size <= 200:
        raise PermissionError("Bad token file length")
    token = path.read_text(encoding="utf-8").strip()
    if not _TOKEN.fullmatch(token):
        raise PermissionError("Invalid token configuration")
    return token


async def certify_existing_channel(*, token: str, client_chat_id: str,
                                   approved: bool, send_test: bool = False,
                                   client=None) -> dict:
    if approved is not True or not _TOKEN.fullmatch(token) or not _CHAT.fullmatch(client_chat_id):
        raise PermissionError("Explicit approved fixed client chat and bot required")
    config = SimpleNamespace(telegram_token=token, telegram_chat_id=client_chat_id)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    try:
        evidence = await verify_destination(client, config)
        if (evidence.get("verified") is not True or
                evidence.get("chat_id") != client_chat_id or
                evidence.get("chat_type") not in ("group", "supergroup", "channel") or
                evidence.get("bot_id") != int(token.split(":", 1)[0])):
            raise PermissionError("Actual client Telegram destination/bot could not be verified")
        mid = None
        if send_test:
            mid = await send(client, config, {
                "chat_id": client_chat_id,
                "text": TEST_TEXT,
                "link_preview_options": {"is_disabled": True},
            })
        return {
            "status": ("V7_EXISTING_CLIENT_CHANNEL_TEST_SENT_DO_NOT_TRADE"
                       if send_test else "V7_EXISTING_CLIENT_CHANNEL_VERIFIED_NO_SEND"),
            "verification": evidence,
            "test_message_id": mid,
            "test_text_sha256": sha256(TEST_TEXT.encode()).hexdigest(),
            "tested_at_utc_local_unattested": datetime.now(timezone.utc).isoformat(),
            "existing_client_destination_used": send_test,
            "actual_trading_signal_published": False,
            "orders_submitted": 0,
            "v7_production_cutover_authorized": False,
            "private_channel_certification": False,
        }
    finally:
        if own_client:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description="V7Sonic existing-client-channel DO NOT TRADE test")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify-existing", action="store_true")
    group.add_argument("--send-one-existing", action="store_true")
    parser.add_argument("--client-chat-id")
    parser.add_argument("--bot-token-file")
    args = parser.parse_args()
    if not args.verify_existing and not args.send_one_existing:
        if args.client_chat_id or args.bot_token_file:
            parser.error("Credentials require an explicit test-only operation")
        print(json.dumps({"status": "V7_EXISTING_TELEGRAM_OFFLINE_PREFLIGHT",
                          "network_requests": 0, "telegram_messages_sent": 0,
                          "client_trading_publication_authorized": False}))
        return
    if (os.getenv("V7_EXISTING_TELEGRAM_TEST_OPERATOR_APPROVED") != "YES" or
            not args.client_chat_id or not args.bot_token_file):
        raise PermissionError("Operator approval, actual client destination and token required")
    if (args.send_one_existing and
            os.getenv("V7_EXISTING_TELEGRAM_ONE_SEND_APPROVED") != "YES"):
        raise PermissionError("Explicit one-send opt-in required")
    token = private_bot_token(args.bot_token_file)
    report = asyncio.run(certify_existing_channel(
        token=token, client_chat_id=args.client_chat_id, approved=True,
        send_test=args.send_one_existing,
    ))
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
