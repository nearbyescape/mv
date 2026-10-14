"""Operator-only Telegram private-test-chat transport certification.

This is NOT a V7 client publisher. No candidate, destination discovery,
database write, exchange call, or production worker is possible here.

Default CLI mode is pure offline NO NETWORK. Online requires an explicit
private TEST chat ID, an independently supplied different CLIENT chat ID
only as a denylist, a token file, and an operator opt-in.
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
import stat

import httpx

from app.telegram.provider import send, verify_destination

_CHAT = re.compile(r"-?[1-9][0-9]{0,15}\Z")
_TOKEN = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,150}\Z")
TEST_MARKER = "MV Intelligent Model V7Sonic — PRIVATE TRANSPORT TEST ONLY. DO NOT TRADE. No live signal or client publication is authorized."
REQUIRED_TEST_GROUP_TITLE = "V7Sonic Private Test"


def _credentials(token_file, private_chat_id, client_chat_id):
    if (not isinstance(token_file, str) or
            not isinstance(private_chat_id, str) or
            not isinstance(client_chat_id, str) or
            not _CHAT.fullmatch(private_chat_id) or
            not _CHAT.fullmatch(client_chat_id) or
            private_chat_id == client_chat_id):
        raise PermissionError("Explicit distinct TEST and client-denylist destinations required")
    path = Path(token_file)
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.stat().st_uid != os.getuid()
            or path.stat().st_mode & 0o077 or
            not 30 <= path.stat().st_size <= 200):
        raise PermissionError("Owner-private exact bot token file required")
    token = path.read_text().strip()
    if not _TOKEN.fullmatch(token):
        raise PermissionError("Malformed private test bot credentials")
    return {"telegram_token": token, "telegram_chat_id": private_chat_id}


async def certify_private_test_chat(settings, *, approval, client_chat_id,
                                    send_test=False, client=None):
    """Real network ONLY with operator opt-in and strict separate test chat."""
    if (approval is not True or
            not _CHAT.fullmatch(settings["telegram_chat_id"]) or
            not _CHAT.fullmatch(client_chat_id) or
            client_chat_id == settings["telegram_chat_id"]):
        raise PermissionError("Private test authorization/destination required")
    from types import SimpleNamespace
    cfg=SimpleNamespace(**settings)
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(trust_env=False, follow_redirects=False)
    try:
        verification = await verify_destination(client, cfg)
        if (verification.get("verified") is not True or
                verification.get("chat_id") != cfg.telegram_chat_id or
                verification.get("chat_type") not in ("group", "supergroup") or
                verification.get("chat_title") != REQUIRED_TEST_GROUP_TITLE or
                verification.get("bot_id") != int(cfg.telegram_token.split(":",1)[0])):
            raise PermissionError("Provider did not verify expected private test chat")
        message_id = None
        if send_test:
            message_id = await send(client, cfg, {
                "chat_id": cfg.telegram_chat_id,
                "text": TEST_MARKER,
                "link_preview_options": {"is_disabled": True},
            })
        return {
            "status": ("V7_PRIVATE_TELEGRAM_TEST_SENT_NOT_CLIENT"
                       if send_test else "V7_PRIVATE_TELEGRAM_DESTINATION_VERIFIED_ONLY"),
            "verification": verification,
            "test_text_sha256": sha256(TEST_MARKER.encode()).hexdigest(),
            "private_test_message_id": message_id,
            "tested_at_utc_unattested": datetime.now(timezone.utc).isoformat(),
            "client_destination_used": False,
            "candidate_or_trading_signal_published": False,
            "orders_submitted": 0,
            "production_cutover_authorized": False,
        }
    finally:
        if own_client:
            await client.aclose()


def main():
    parser=argparse.ArgumentParser(description="V7 private Telegram TEST-chat proof")
    parser.add_argument("--verify-private", action="store_true")
    parser.add_argument("--send-private-test", action="store_true")
    parser.add_argument("--private-chat-id")
    parser.add_argument("--client-chat-id")
    parser.add_argument("--bot-token-file")
    args=parser.parse_args()
    if not args.verify_private and not args.send_private_test:
        if any((args.private_chat_id,args.client_chat_id,args.bot_token_file)):
            parser.error("Credentials require explicit private-only operation")
        print(json.dumps({"status":"V7_PRIVATE_TELEGRAM_OFFLINE_PREFLIGHT",
            "network_requests":0,"client_publication_authorized":False,
            "orders_submitted":0},sort_keys=True))
        return
    if (os.getenv("V7_PRIVATE_TELEGRAM_OPERATOR_APPROVED") != "YES" or
            not args.private_chat_id or not args.client_chat_id or
            not args.bot_token_file):
        raise PermissionError("Explicit private network testing approval and all inputs required")
    settings=_credentials(args.bot_token_file,args.private_chat_id,args.client_chat_id)
    result=asyncio.run(certify_private_test_chat(
        settings, approval=True, client_chat_id=args.client_chat_id,
        send_test=args.send_private_test,
    ))
    # Do not print bot token or client chat ID. Verification chat ID is
    # intentionally the operator-provided PRIVATE destination only.
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=="__main__":
    main()
