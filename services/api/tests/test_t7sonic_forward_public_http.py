"""Offline-only unit tests for opt-in public HTTPS raw quote endpoints."""
from __future__ import annotations

from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from services.t7sonic import forward_public_http as http


def envelope(kind="bookTicker", symbol="BTCUSDT", *, body=b'{"symbol":"BTCUSDT"}'):
    if kind=="exchangeInfo":
        symbol=None
    url,_=http.approved_public_url(kind,symbol)
    return http.PublicHttpResponse(
        request_url=url,final_url=url,status=200,
        content_type="application/json; charset=utf-8",
        body=body,received_ms_local_claim=1770000000000,
    )


class PublicHTTPTests(TestCase):
    def test_fixed_approved_https_paths_only(self):
        info,_=http.approved_public_url("exchangeInfo")
        tick,_=http.approved_public_url("bookTicker","BTCUSDT")
        self.assertEqual(info, "https://fapi.binance.com/fapi/v1/exchangeInfo")
        self.assertEqual(tick,
                         "https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=BTCUSDT")
        for kind, symbol in (
            ("exchangeInfo","BTCUSDT"),("bookTicker",None),
            ("bookTicker","INVALID"),("order","BTCUSDT"),
        ):
            with self.subTest(kind=kind,symbol=symbol),self.assertRaises(ValueError):
                http.approved_public_url(kind,symbol)

    def test_network_denied_by_default_with_no_opener_call(self):
        with patch.object(http,"build_opener") as opener:
            with self.assertRaises(PermissionError):
                http.optional_public_http_get("exchangeInfo")
            with self.assertRaises(PermissionError):
                http.optional_public_http_get("bookTicker",symbol="BTCUSDT")
            opener.assert_not_called()
            for duration in (0,-1,5,True,float("inf")):
                with self.subTest(duration=duration),self.assertRaises(ValueError):
                    http.optional_public_http_get(
                        "exchangeInfo",network_approved=True,
                        timeout_seconds=duration)
            opener.assert_not_called()

    def test_json_body_validation_no_signed_claims(self):
        report=http.verify_http_response("bookTicker",envelope(),symbol="BTCUSDT")
        self.assertEqual(report["status"],"PUBLIC_REST_BODY_UNATTESTED")
        self.assertFalse(report["data_payload_signed_by_exchange"])
        self.assertFalse(report["orders_authorized"])
        self.assertFalse(report["client_publication_authorized"])

    def test_any_redirect_status_nonjson_invalid_size_or_mismatch_refused(self):
        original=envelope()
        for field,bad in (
            ("request_url","https://evil.invalid"),
            ("final_url","https://evil.invalid"),
            ("status",301),("status",429),("status",True),
            ("content_type","text/html"),("body",b"x"*8193),
            ("body",b""),("received_ms_local_claim",0),
            ("received_ms_local_claim",True),
        ):
            with self.subTest(field=field),self.assertRaises(ValueError):
                http.verify_http_response("bookTicker",replace(original,**{field:bad}),
                                          symbol="BTCUSDT")
        with self.assertRaises(ValueError):
            http.verify_http_response("bookTicker",original,symbol="SOLUSDT")

    def test_mocked_optional_https_uses_no_proxy_no_redirect(self):
        class MockResponse:
            status=200
            headers={"Content-Type":"application/json"}
            def geturl(self): return http.INFO_ENDPOINT
            def read(self,limit):
                assert limit==http.MAX_EXCHANGE_BODY+1
                return b'{"symbols":[]}'
            def __enter__(self): return self
            def __exit__(self,*args): return False
        class MockOpener:
            def open(self,req,*,timeout):
                assert req.full_url==http.INFO_ENDPOINT
                assert req.get_method()=="GET"
                assert 0<timeout<=4
                return MockResponse()
        with patch.object(http,"build_opener",return_value=MockOpener()) as build:
            with patch.object(http.time,"time_ns",
                              return_value=1770000001000*1_000_000):
                env=http.optional_public_http_get(
                    "exchangeInfo",network_approved=True)
            self.assertEqual(env.received_ms_local_claim,1770000001000)
            self.assertTrue(any(isinstance(a,http._NeverRedirect)
                                for a in build.call_args.args))
            self.assertTrue(any(type(a).__name__=="ProxyHandler" and a.proxies=={}
                                for a in build.call_args.args))

    def test_https_errors_and_redirect_fail_closed(self):
        with patch.object(http,"build_opener") as build:
            build.return_value.open.side_effect=http.URLError("refused")
            with self.assertRaisesRegex(ValueError,"fail closed"):
                http.optional_public_http_get(
                    "exchangeInfo",network_approved=True)
        with self.assertRaisesRegex(ValueError,"never follow"):
            http._NeverRedirect().redirect_request(
                None,None,302,"redirect",{},"https://malicious.invalid"
            )
