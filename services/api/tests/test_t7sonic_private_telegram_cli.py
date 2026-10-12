"""Offline-only manual Telegram CLI preflight; never contact Telegram."""
from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from services.t7sonic import private_telegram_cli as cli
from services.t7sonic.forward_private_telegram import APPROVAL_PHRASE

TEST_TOKEN="123456789:"+"T"*35
PROD_TOKEN="987654321:"+"P"*35
CONFIG={
    "test_bot_token": TEST_TOKEN,
    "production_bot_token": PROD_TOKEN,
    "private_test_chat_id":"123456789",
    "production_chat_id":"-1002222222222",
}


class ManualTelegramCLI(unittest.TestCase):
    def setUp(self):
        self.directory=TemporaryDirectory(prefix="v7sonic-cli-")
        self.path=Path(self.directory.name)/"private.json"
        self.path.write_text(json.dumps(CONFIG))
        self.path.chmod(0o600)

    def tearDown(self):
        self.directory.cleanup()

    def options(self, **updates):
        opts={
            "config":str(self.path),
            "send_fixed_test":False,
            "network_approved":False,
            "second_confirmation":False,
            "approval_phrase":None,
        }
        opts.update(updates)
        return Namespace(**opts)

    def test_default_file_preflight_requires_zero_network(self):
        with patch.object(cli,"optional_private_telegram_connectivity_test") as sender:
            with patch.object(cli.time,"time",return_value=1_800_000_000):
                info=cli.run_manual(self.options())
        self.assertEqual(info["status"],"PRIVATE_TEST_CONFIG_VALIDATED_NO_NETWORK")
        self.assertFalse(info["provider_chat_type_checked_live"])
        self.assertFalse(info["network_contacted"])
        self.assertFalse(info["test_message_delivery_verified"])
        self.assertEqual(info["telegram_messages_sent"],0)
        sender.assert_not_called()
        self.assertNotIn(TEST_TOKEN,json.dumps(info))
        self.assertNotIn(PROD_TOKEN,json.dumps(info))
        self.assertNotIn(CONFIG["production_chat_id"],json.dumps(info))

    def test_non_private_or_symlink_secret_file_refused(self):
        self.path.chmod(0o644)
        with self.assertRaises(PermissionError):
            cli.read_private_config(str(self.path))
        self.path.chmod(0o600)
        symlink=Path(self.directory.name)/"link.json"
        symlink.symlink_to(self.path)
        with self.assertRaises(PermissionError):
            cli.read_private_config(str(symlink))
        with self.assertRaises(PermissionError):
            cli.read_private_config("private.json")
        self.assertEqual(cli.read_private_config(str(self.path)),CONFIG)

    def test_incomplete_invalid_bot_or_same_channel_refused(self):
        for update in (
            {"test_bot_token": PROD_TOKEN},
            {"private_test_chat_id": CONFIG["production_chat_id"]},
            {"private_test_chat_id": "-1004444444444"},
            {"production_chat_id": CONFIG["private_test_chat_id"]},
            {"extra": "invalid"},
        ):
            modified={**CONFIG,**update}
            self.path.write_text(json.dumps(modified))
            with self.subTest(modified=update),self.assertRaises(
                    (ValueError,PermissionError)):
                cli.run_manual(self.options())
        self.path.write_text(json.dumps(CONFIG))

    def test_no_send_without_all_three_explicit_gates(self):
        with patch.object(cli,"optional_private_telegram_connectivity_test") as sender:
            with patch.object(cli.time,"time",return_value=1_800_000_000):
                for missing in ("network_approved","second_confirmation",
                                "approval_phrase"):
                    settings={
                        "send_fixed_test":True,
                        "network_approved":True,
                        "second_confirmation":True,
                        "approval_phrase":APPROVAL_PHRASE,
                    }
                    settings[missing]=False if missing != "approval_phrase" else None
                    with self.subTest(missing=missing),self.assertRaises(PermissionError):
                        cli.run_manual(self.options(**settings))
                with self.assertRaises(PermissionError):
                    cli.run_manual(self.options(network_approved=True))
        sender.assert_not_called()

    def test_explicit_send_routes_only_fixed_test_transport(self):
        stub={
            "status":"CONFIRMED_PRIVATE_TEST_TEXT_SENT_NOT_A_TRADE_SIGNAL",
            "message_id":123,
            "production_client_channel_contacted":False,
            "live_signal_published":False,
        }
        with patch.object(cli,"optional_private_telegram_connectivity_test",
                          return_value=stub) as sender:
            with patch.object(cli.time,"time",return_value=1_800_000_000):
                out=cli.run_manual(self.options(
                    send_fixed_test=True,
                    network_approved=True,
                    second_confirmation=True,
                    approval_phrase=APPROVAL_PHRASE,
                ))
        sender.assert_called_once()
        (_,),params=sender.call_args
        self.assertEqual(params["network_approved"],True)
        self.assertEqual(params["second_operator_confirmed"],True)
        self.assertEqual(_.test_bot_token,TEST_TOKEN)
        self.assertEqual(_.production_bot_token,PROD_TOKEN)
        self.assertFalse(out["production_strategy_restarted"])
        self.assertFalse(out["live_trade_signal_published"])

    def test_malformed_or_oversized_file_rejected(self):
        for body in ("{}", "broken json", "x"*2049):
            self.path.write_text(body)
            with self.subTest(size=len(body)),self.assertRaises((ValueError,PermissionError)):
                cli.read_private_config(str(self.path))


if __name__=="__main__":
    unittest.main()
