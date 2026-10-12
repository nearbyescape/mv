"""V7Sonic *manual* Telegram connectivity probe for a distinct test bot.

Only a fixed non-trading text may be sent, to a verified PRIVATE 1:1
Telegram chat, using a bot token different from production. No strategy,
signal, client channel, background job, outbox or production DB access.

Network is OFF by default and requires TWO explicit caller approvals and a
short-lived human-provided deadline. THIS MODULE MUST NEVER BE CALLED BY
THE SIGNAL ENGINE. Unit tests inject a fake HTTP opener, not Telegram.

Telegram Bot API is HTTPS but provider receipts are not an independent
timestamp or proof of positive trading expectancy. An uncertain send is
NOT retried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener,
)

TOKEN_RE = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,150}\Z")
POSITIVE_CHAT_ID = re.compile(r"[1-9][0-9]{0,15}\Z")
APPROVAL_PHRASE = "I_APPROVE_ONE_PRIVATE_TEST_MESSAGE_NOT_CLIENT_SIGNALS"
TEST_TEXT = (
    "V7Sonic internal connectivity test only. "
    "DO NOT TRADE. No live strategy or trading signal is being published."
)
MAX_RESPONSE_BYTES = 8192
HTTP_TIMEOUT_SEC = 5.0


class AmbiguousPrivateTestDelivery(RuntimeError):
    """A Telegram send might have succeeded; DO NOT RETRY automatically."""


class RejectedPrivateTestDelivery(RuntimeError):
    """No delivery certification; operator action required."""


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RejectedPrivateTestDelivery("Telegram redirect forbidden")


@dataclass(frozen=True)
class PrivateTestConsent:
    test_bot_token: str
    production_bot_token: str
    private_test_chat_id: str
    production_chat_id: str
    authorization_phrase: str
    approved_until_unix_s: int


def validate_private_test_consent(consent: PrivateTestConsent, *,
                                  now_unix_s: int) -> None:
    """Disallow prod token/channel, group chats and expired approvals."""
    if not isinstance(consent, PrivateTestConsent):
        raise PermissionError("Explicit private test consent is required")
    if (not isinstance(consent.test_bot_token,str) or
            not isinstance(consent.production_bot_token,str) or
            not TOKEN_RE.fullmatch(consent.test_bot_token) or
            not TOKEN_RE.fullmatch(consent.production_bot_token) or
            consent.test_bot_token == consent.production_bot_token):
        raise PermissionError("Dedicated TEST bot token distinct from production")
    if (not isinstance(consent.private_test_chat_id,str) or
            not POSITIVE_CHAT_ID.fullmatch(consent.private_test_chat_id) or
            not isinstance(consent.production_chat_id,str) or
            not re.fullmatch(r"-?[1-9][0-9]{0,15}",consent.production_chat_id)
            or consent.private_test_chat_id == consent.production_chat_id):
        raise PermissionError("Dedicated private 1:1 test chat distinct from client channel")
    if (consent.authorization_phrase != APPROVAL_PHRASE or
            type(now_unix_s) is not int or
            type(consent.approved_until_unix_s) is not int or
            not now_unix_s < consent.approved_until_unix_s <= now_unix_s+300):
        raise PermissionError("Fresh explicit one-message operator approval required")


def _provider_result(raw: bytes, *, method: str,
                     expected_chat_id: str) -> dict:
    if (not isinstance(raw,bytes) or
            not 2 <= len(raw) <= MAX_RESPONSE_BYTES):
        raise RejectedPrivateTestDelivery("Malformed bounded Telegram response")
    try:
        data=json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RejectedPrivateTestDelivery("Telegram response not valid JSON") from exc
    if not isinstance(data,dict) or data.get("ok") is not True or not isinstance(
        data.get("result"),dict
    ):
        raise RejectedPrivateTestDelivery("Telegram API returned a failed response")
    result=data["result"]
    if method=="getChat":
        if (str(result.get("id")) != expected_chat_id or
                result.get("type") != "private"):
            raise RejectedPrivateTestDelivery("Test destination is not the exact private 1:1 chat")
    elif method=="sendMessage":
        chat=result.get("chat")
        msg=result.get("message_id")
        if (not isinstance(chat,dict) or str(chat.get("id")) != expected_chat_id or
                chat.get("type") != "private" or type(msg) is not int or msg <= 0 or
                result.get("text") != TEST_TEXT):
            raise AmbiguousPrivateTestDelivery(
                "Unverifiable Telegram send receipt. Never auto-retry."
            )
    else:
        raise RejectedPrivateTestDelivery("Unknown fixed Telegram method")
    return result


def _one_post(opener, consent: PrivateTestConsent, *,
              method: str) -> bytes:
    """Fixed API origin, no proxies, no redirects, no external provider URL."""
    if method not in ("getChat","sendMessage"):
        raise RejectedPrivateTestDelivery("Only fixed Telegram test methods allowed")
    endpoint=(
        "https://api.telegram.org/bot"+
        consent.test_bot_token+"/"+method
    )
    body={
        "chat_id":consent.private_test_chat_id,
    }
    if method=="sendMessage":
        body.update({
            "text": TEST_TEXT,
            "disable_notification": True,
            "disable_web_page_preview": True,
            "protect_content": True,
        })
    request=Request(
        endpoint,
        data=json.dumps(body,separators=(",",":")).encode("utf-8"),
        method="POST",
        headers={"Content-Type":"application/json","Accept":"application/json"},
    )
    started=False
    try:
        started=True
        with opener.open(request,timeout=HTTP_TIMEOUT_SEC) as response:
            status=response.status
            final_url=response.geturl()
            response_type=response.headers.get("Content-Type","")
            raw=response.read(MAX_RESPONSE_BYTES+1)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        if method=="sendMessage" and started:
            raise AmbiguousPrivateTestDelivery(
                "Telegram send outcome uncertain; do not retry automatically"
            ) from None
        raise RejectedPrivateTestDelivery(
            "Private test recipient could not be verified"
        ) from None
    if (type(status) is not int or status != 200 or
            final_url != endpoint or
            response_type.partition(";")[0].lower().strip() !=
            "application/json"):
        if method=="sendMessage":
            raise AmbiguousPrivateTestDelivery(
                "Telegram send response untrusted; do not retry"
            )
        raise RejectedPrivateTestDelivery("Telegram getChat response untrusted")
    return raw


def optional_private_telegram_connectivity_test(
    consent: PrivateTestConsent, *,
    network_approved: bool=False,
    second_operator_confirmed: bool=False,
) -> dict:
    """Send exactly ONE non-trading test message ONLY after two explicit gates.

    Network calls: POST getChat, then POST sendMessage. Never retries.
    Does not touch the mock-paper outbox; it is not a client delivery test.
    Bot credentials and chat IDs are never returned or logged.
    """
    if network_approved is not True or second_operator_confirmed is not True:
        raise PermissionError("No Telegram contact without two independent opt-ins")
    now=int(time.time())
    validate_private_test_consent(consent,now_unix_s=now)
    context=ssl.create_default_context()
    if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
        raise RuntimeError("Strict CA/hostname verification mandatory")
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),_NoRedirects())
    check=_one_post(opener,consent,method="getChat")
    _provider_result(
        check,method="getChat",expected_chat_id=consent.private_test_chat_id
    )
    # Approval is revalidated before the irreversible POST.
    validate_private_test_consent(consent,now_unix_s=int(time.time()))
    received=_one_post(opener,consent,method="sendMessage")
    try:
        parsed=_provider_result(
            received,method="sendMessage",
            expected_chat_id=consent.private_test_chat_id
        )
    except RejectedPrivateTestDelivery as exc:
        raise AmbiguousPrivateTestDelivery(
            "Send receipt invalid; never auto-retry"
        ) from None
    return {
        "status":"CONFIRMED_PRIVATE_TEST_TEXT_SENT_NOT_A_TRADE_SIGNAL",
        "message_id":parsed["message_id"],
        "message_text":TEST_TEXT,
        "private_chat_type_confirmed":True,
        "production_bot_used":False,
        "production_client_channel_contacted":False,
        "live_signal_published":False,
        "trade_orders_authorized":False,
    }
