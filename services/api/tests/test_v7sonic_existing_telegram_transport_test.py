"""Test operator-approved existing client channel test, all mocked: NO NETWORK."""
import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import v7sonic_existing_telegram_transport_test as diag

BOT = "123456789:" + "a" * 35
CHAT = "-1003993483763"


class ExistingChannelTransportTests(TestCase):
    def test_verify_does_not_send(self):
        calls = []
        async def verify(_client, cfg):
            calls.append("verify")
            return {
                "verified": True, "chat_id": cfg.telegram_chat_id,
                "chat_type": "supergroup", "bot_id": 123456789,
                "bot_status": "administrator", "chat_title": "MV Signal"
            }
        async def never_send(*_args, **_kwargs):
            raise AssertionError("No send in verification-only mode")
        with (patch.object(diag, "verify_destination", new=verify),
              patch.object(diag, "send", new=never_send)):
            proof = asyncio.run(diag.certify_existing_channel(
                token=BOT, client_chat_id=CHAT, approved=True,
                send_test=False, client=object()))
        self.assertEqual(calls, ["verify"])
        self.assertIsNone(proof["test_message_id"])
        self.assertFalse(proof["existing_client_destination_used"])
        self.assertFalse(proof["v7_production_cutover_authorized"])

    def test_one_only_nontrading_message_to_verified_existing_chat(self):
        posted = []
        async def verify(_client, cfg):
            return {"verified":True,"chat_id":cfg.telegram_chat_id,
                    "chat_type":"channel","bot_id":123456789}
        async def send(_client, cfg, payload):
            posted.append(payload)
            return 67
        with (patch.object(diag, "verify_destination", new=verify),
              patch.object(diag, "send", new=send)):
            p = asyncio.run(diag.certify_existing_channel(
                token=BOT, client_chat_id=CHAT, approved=True,
                send_test=True, client=object()))
        self.assertEqual(p["test_message_id"],67)
        self.assertTrue(p["existing_client_destination_used"])
        self.assertEqual(len(posted),1)
        self.assertEqual(posted[0]["chat_id"], CHAT)
        self.assertEqual(posted[0]["text"],diag.TEST_TEXT)
        self.assertIn("DO NOT TRADE",posted[0]["text"])
        self.assertNotIn("USDT",posted[0]["text"])
        self.assertFalse(p["actual_trading_signal_published"])
        self.assertEqual(p["orders_submitted"],0)
        self.assertFalse(p["private_channel_certification"])

    def test_wrong_destination_or_bot_fails_before_send(self):
        async def verify(_client, cfg):
            return {"verified":True,"chat_id":cfg.telegram_chat_id,
                    "chat_type":"supergroup","bot_id":123456788}
        async def never_send(*_args,**_kwargs):
            raise AssertionError("Mismatched bot must not send")
        with (patch.object(diag, "verify_destination", new=verify),
              patch.object(diag, "send", new=never_send)):
            with self.assertRaises(PermissionError):
                asyncio.run(diag.certify_existing_channel(
                    token=BOT,client_chat_id=CHAT,approved=True,
                    send_test=True,client=object()))
        with self.assertRaises(PermissionError):
            asyncio.run(diag.certify_existing_channel(
                token=BOT,client_chat_id=CHAT,approved=False,
                send_test=True,client=object()))

    def test_private_file_permissions(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"token"
            path.write_text(BOT)
            path.chmod(0o600)
            self.assertEqual(diag.private_bot_token(str(path)),BOT)
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                diag.private_bot_token(str(path))
