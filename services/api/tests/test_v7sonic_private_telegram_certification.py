"""Offline unit certification of V7 private Telegram-only transport."""
from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from app import v7sonic_private_telegram_certification as trial

PRIVATE = "-1003900010101"
CLIENT = "-1003900010202"
FAKE_TOKEN = "123456789:" + "private_test_only_dummy_credential" * 2


class PrivateTransportCertificationTests(TestCase):
    def run_case(self, send_test=False):
        calls=[]
        async def verified(client, cfg):
            calls.append(("getMe/getChat/getChatMember",cfg.telegram_chat_id))
            return {"verified":True,"chat_id":cfg.telegram_chat_id,
                    "chat_type":"supergroup","bot_status":"administrator",
                    "bot_id":123456789,
                    "chat_title":trial.REQUIRED_TEST_GROUP_TITLE}
        async def sent(client,cfg,payload):
            calls.append(("sendMessage",payload["chat_id"],payload["text"]))
            return 789
        with (patch.object(trial,"verify_destination",new=verified),
              patch.object(trial,"send",new=sent)):
            result=asyncio.run(trial.certify_private_test_chat(
                {"telegram_token":FAKE_TOKEN,"telegram_chat_id":PRIVATE},
                approval=True,client_chat_id=CLIENT,
                send_test=send_test,client=object(),
            ))
        return result,calls

    def test_private_getme_chat_member_verification_only_no_send(self):
        result,calls=self.run_case()
        self.assertEqual(len(calls),1)
        self.assertEqual(result["verification"]["chat_id"],PRIVATE)
        self.assertIsNone(result["private_test_message_id"])
        self.assertFalse(result["candidate_or_trading_signal_published"])
        self.assertFalse(result["production_cutover_authorized"])

    def test_private_one_test_message_never_client_or_trade(self):
        result,calls=self.run_case(send_test=True)
        self.assertEqual(result["private_test_message_id"],789)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[1][1],PRIVATE)
        self.assertNotEqual(calls[1][1],CLIENT)
        self.assertIn("DO NOT TRADE",calls[1][2])
        self.assertEqual(result["orders_submitted"],0)

    def test_fake_group_title_or_bot_identity_fails_before_send(self):
        async def mismatched(_client, cfg):
            return {
                "verified":True, "chat_id":cfg.telegram_chat_id,
                "chat_type":"supergroup", "bot_status":"administrator",
                "bot_id":123456789,
                "chat_title":"Real Subscriber Channel",
            }
        async def cannot_send(*_args, **_kwargs):
            raise AssertionError("No send may occur after title mismatch")
        with (patch.object(trial, "verify_destination", new=mismatched),
              patch.object(trial, "send", new=cannot_send)):
            with self.assertRaises(PermissionError):
                asyncio.run(trial.certify_private_test_chat(
                    {"telegram_token":FAKE_TOKEN,"telegram_chat_id":PRIVATE},
                    approval=True,client_chat_id=CLIENT,
                    send_test=True,client=object(),
                ))
        async def wrong_id(_client, cfg):
            return {
                "verified":True, "chat_id":cfg.telegram_chat_id,
                "chat_type":"supergroup", "bot_status":"administrator",
                "bot_id":123456788,
                "chat_title":trial.REQUIRED_TEST_GROUP_TITLE,
            }
        with (patch.object(trial, "verify_destination", new=wrong_id),
              patch.object(trial, "send", new=cannot_send)):
            with self.assertRaises(PermissionError):
                asyncio.run(trial.certify_private_test_chat(
                    {"telegram_token":FAKE_TOKEN,"telegram_chat_id":PRIVATE},
                    approval=True,client_chat_id=CLIENT,
                    send_test=True,client=object(),
                ))

    def test_no_approval_or_same_chat_blocks_all_network(self):
        with self.assertRaises(PermissionError):
            asyncio.run(trial.certify_private_test_chat(
                {"telegram_chat_id":PRIVATE},approval=False,
                client_chat_id=CLIENT,client=object()))
        with self.assertRaises(PermissionError):
            asyncio.run(trial.certify_private_test_chat(
                {"telegram_chat_id":CLIENT},approval=True,
                client_chat_id=CLIENT,client=object()))

    def test_token_file_requires_private_valid_token_and_separate_chat(self):
        with TemporaryDirectory(prefix="v7-private-chat-fixture-") as d:
            path=Path(d)/"private-test-token"
            path.write_text(FAKE_TOKEN)
            path.chmod(0o600)
            settings=trial._credentials(str(path),PRIVATE,CLIENT)
            self.assertEqual(settings["telegram_chat_id"],PRIVATE)
            with self.assertRaisesRegex(PermissionError,"destinations"):
                trial._credentials(str(path),PRIVATE,PRIVATE)
            path.chmod(0o644)
            with self.assertRaisesRegex(PermissionError,"Owner-private"):
                trial._credentials(str(path),PRIVATE,CLIENT)
