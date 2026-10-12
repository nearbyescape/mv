"""No-network tests for private 1:1 Telegram connectivity probe."""
from __future__ import annotations

import json
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from services.t7sonic import forward_private_telegram as tg

TEST_TOKEN="123456789:"+"T"*35
PROD_TOKEN="987654321:"+"P"*35
TEST_CHAT="123456789"
PROD_CHAT="-1002222222222"
CLOCK=1_800_000_000


def consent(**kw):
    values=dict(
        test_bot_token=TEST_TOKEN,
        production_bot_token=PROD_TOKEN,
        private_test_chat_id=TEST_CHAT,
        production_chat_id=PROD_CHAT,
        authorization_phrase=tg.APPROVAL_PHRASE,
        approved_until_unix_s=CLOCK+90,
    )
    values.update(kw)
    return tg.PrivateTestConsent(**values)


def json_bytes(data):
    return json.dumps(data,separators=(",",":")).encode()


class FakeResponse:
    status=200
    headers={"Content-Type":"application/json"}
    def __init__(self,url,raw):
        self.url=url
        self.raw=raw
    def geturl(self): return self.url
    def read(self,maxbytes):
        assert maxbytes==tg.MAX_RESPONSE_BYTES+1
        return self.raw
    def __enter__(self):return self
    def __exit__(self,*args):return False


class FakeOpener:
    def __init__(self, *, group=False, ambiguous=False, reject=False):
        self.group=group
        self.ambiguous=ambiguous
        self.reject=reject
        self.requests=[]
    def open(self,req,timeout):
        self.requests.append(req)
        assert timeout==tg.HTTP_TIMEOUT_SEC
        assert req.get_method()=="POST"
        assert req.full_url.startswith(
            "https://api.telegram.org/bot"+TEST_TOKEN+"/"
        )
        data=json.loads(req.data)
        assert data["chat_id"]==TEST_CHAT
        if req.full_url.endswith("/getChat"):
            return FakeResponse(req.full_url,json_bytes({
                "ok":True,"result":{"id":int(TEST_CHAT),
                "type":"supergroup" if self.group else "private"}
            }))
        assert req.full_url.endswith("/sendMessage")
        assert data["text"]==tg.TEST_TEXT
        assert data["disable_notification"] is True
        assert data["protect_content"] is True
        if self.ambiguous: raise tg.URLError("lost after sending")
        if self.reject:
            return FakeResponse(req.full_url,b'{broken')
        return FakeResponse(req.full_url,json_bytes({
            "ok":True,"result":{
                "message_id":1234,"text":tg.TEST_TEXT,
                "chat":{"id":int(TEST_CHAT),"type":"private"},
            },
        }))


class PrivateTelegramTransportTests(TestCase):
    def test_disabled_by_default_even_with_valid_consent(self):
        with patch.object(tg,"build_opener") as opener:
            with self.assertRaises(PermissionError):
                tg.optional_private_telegram_connectivity_test(consent())
            with self.assertRaises(PermissionError):
                tg.optional_private_telegram_connectivity_test(
                    consent(),network_approved=True
                )
            with self.assertRaises(PermissionError):
                tg.optional_private_telegram_connectivity_test(
                    consent(),second_operator_confirmed=True
                )
            opener.assert_not_called()

    def test_cannot_use_production_bot_or_channel(self):
        invalid=[
            ("test_bot_token",PROD_TOKEN),
            ("test_bot_token","1234:bad"),
            ("production_bot_token","no-token"),
            ("private_test_chat_id",PROD_CHAT),
            ("private_test_chat_id","0"),
            ("private_test_chat_id","-123"),
            ("production_chat_id",TEST_CHAT),
            ("authorization_phrase","operator verbal yes"),
            ("approved_until_unix_s",CLOCK),
            ("approved_until_unix_s",CLOCK+301),
            ("approved_until_unix_s",True),
        ]
        with patch.object(tg,"build_opener") as opener:
            for key,value in invalid:
                with self.subTest(key=key,value=str(value)[:10]):
                    with patch.object(tg.time,"time",return_value=CLOCK):
                        with self.assertRaises(PermissionError):
                            tg.optional_private_telegram_connectivity_test(
                                consent(**{key:value}),network_approved=True,
                                second_operator_confirmed=True,
                            )
            opener.assert_not_called()

    def test_success_only_fixed_nontrading_message_to_verified_private_recipient(self):
        fake=FakeOpener()
        with patch.object(tg,"build_opener",return_value=fake) as build:
            with patch.object(tg.time,"time",return_value=CLOCK):
                result=tg.optional_private_telegram_connectivity_test(
                    consent(),network_approved=True,
                    second_operator_confirmed=True
                )
        self.assertEqual(result["status"],
                         "CONFIRMED_PRIVATE_TEST_TEXT_SENT_NOT_A_TRADE_SIGNAL")
        self.assertEqual(result["message_id"],1234)
        self.assertTrue(result["private_chat_type_confirmed"])
        self.assertFalse(result["production_client_channel_contacted"])
        self.assertFalse(result["live_signal_published"])
        self.assertEqual(len(fake.requests),2)
        self.assertTrue(fake.requests[0].full_url.endswith("/getChat"))
        self.assertTrue(fake.requests[1].full_url.endswith("/sendMessage"))
        self.assertEqual(tg.TEST_TEXT.count("DO NOT TRADE"),1)
        self.assertTrue(any(type(x).__name__=="ProxyHandler" and x.proxies=={}
                            for x in build.call_args.args))
        self.assertTrue(any(isinstance(x,tg._NoRedirects)
                            for x in build.call_args.args))

    def test_nonprivate_chat_rejected_before_message_send(self):
        fake=FakeOpener(group=True)
        with patch.object(tg,"build_opener",return_value=fake):
            with patch.object(tg.time,"time",return_value=CLOCK):
                with self.assertRaises(tg.RejectedPrivateTestDelivery):
                    tg.optional_private_telegram_connectivity_test(
                        consent(),network_approved=True,
                        second_operator_confirmed=True
                    )
        self.assertEqual(len(fake.requests),1)

    def test_uncertain_send_is_never_retried(self):
        fake=FakeOpener(ambiguous=True)
        with patch.object(tg,"build_opener",return_value=fake):
            with patch.object(tg.time,"time",return_value=CLOCK):
                with self.assertRaisesRegex(
                    tg.AmbiguousPrivateTestDelivery,"do not retry"
                ):
                    tg.optional_private_telegram_connectivity_test(
                        consent(),network_approved=True,
                        second_operator_confirmed=True
                    )
        self.assertEqual(len(fake.requests),2)

    def test_malformed_send_response_remains_ambiguous(self):
        fake=FakeOpener(reject=True)
        with patch.object(tg,"build_opener",return_value=fake):
            with patch.object(tg.time,"time",return_value=CLOCK):
                with self.assertRaises(tg.AmbiguousPrivateTestDelivery):
                    tg.optional_private_telegram_connectivity_test(
                        consent(),network_approved=True,
                        second_operator_confirmed=True
                    )
        self.assertEqual(len(fake.requests),2)

    def test_wrong_message_id_wrong_chat_and_wrong_text_are_not_confirmed(self):
        valid={"ok":True,"result":{
            "message_id":55,"text":tg.TEST_TEXT,
            "chat":{"id":int(TEST_CHAT),"type":"private"},
        }}
        changes=[
            ("message_id",True),("message_id",0),
            ("text","Trade BTC now"),("chat",{"id":777,"type":"private"}),
            ("chat",{"id":int(TEST_CHAT),"type":"supergroup"}),
        ]
        for key,value in changes:
            payload=json.loads(json.dumps(valid))
            payload["result"][key]=value
            with self.subTest(key=key,value=value):
                with self.assertRaises(tg.AmbiguousPrivateTestDelivery):
                    tg._provider_result(
                        json_bytes(payload),method="sendMessage",
                        expected_chat_id=TEST_CHAT
                    )

    def test_response_rejection_redirects_and_unsupported_methods(self):
        fake=FakeOpener()
        with self.assertRaises(tg.RejectedPrivateTestDelivery):
            tg._one_post(fake,consent(),method="sendPhoto")
        with self.assertRaises(tg.RejectedPrivateTestDelivery):
            tg._NoRedirects().redirect_request(
                None,None,302,"redirect",{},"https://evil.invalid"
            )
        with self.assertRaises(tg.RejectedPrivateTestDelivery):
            tg._provider_result(
                b'{"ok":false}',method="getChat",
                expected_chat_id=TEST_CHAT
            )
        with self.assertRaises(tg.RejectedPrivateTestDelivery):
            tg._provider_result(
                b'x'*8193,method="getChat",
                expected_chat_id=TEST_CHAT
            )

    def test_approval_expiring_before_send_cancels_without_message(self):
        fake=FakeOpener()
        # First time used for start permission; second during re-verification
        # is beyond the expiry. No sendMessage can occur.
        with patch.object(tg,"build_opener",return_value=fake):
            with patch.object(tg.time,"time",
                              side_effect=[CLOCK,CLOCK+120]):
                with self.assertRaises(PermissionError):
                    tg.optional_private_telegram_connectivity_test(
                        consent(approved_until_unix_s=CLOCK+90),
                        network_approved=True,
                        second_operator_confirmed=True
                    )
        self.assertEqual(len(fake.requests),1)


if __name__=="__main__":
    import unittest
    unittest.main()
