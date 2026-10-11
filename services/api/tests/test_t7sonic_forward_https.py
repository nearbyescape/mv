"""Phase 2U source allowlist and negative-path tests: no external HTTP calls."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal as D
import json
from unittest import TestCase
from unittest.mock import patch

from app.research.t7sonic_forward_protocol import START_MS
from services.t7sonic.forward_acquisition import request_plan
from services.t7sonic import forward_https as https


def synthetic_1m():
    plan = request_plan("BTCUSDT", "1m", START_MS)
    begin = plan["query"]["startTime"]
    rows = []
    for i in range(480):
        t = begin + i*60_000
        p = D("100") + D(i)*D(".0005")
        rows.append([
            t, str(p), str(p+D(".1")), str(p-D(".1")),
            str(p), "1", t+59999, "0", 1, "0", "0", "0",
        ])
    return plan, json.dumps(rows, separators=(",", ":")).encode()


def synthetic_envelope(plan, data):
    return https.TransportEnvelope(
        status=200, final_url=https.expected_url(plan),
        content_type="application/json; charset=utf-8", raw_body=data,
        received_ms=START_MS+1500,
        provenance=https.SYNTHETIC_SOURCE,
    )


class HttpsEnvelopeTests(TestCase):
    def test_expected_origin_and_exact_source_request(self):
        plan, raw = synthetic_1m()
        url = https.expected_url(plan)
        self.assertTrue(url.startswith("https://fapi.binance.com/fapi/v1/klines?"))
        self.assertIn("symbol=BTCUSDT", url)
        self.assertIn("interval=1m", url)
        self.assertNotIn("apiKey", url)
        for key, value in (
            ("host", "attacker.invalid"), ("path", "/fapi/v1/order"),
            ("method", "POST"), ("boundary_ms", START_MS+300000),
        ):
            altered = deepcopy(plan)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                https.expected_url(altered)
        p = deepcopy(plan)
        p["query"]["limit"] = 1500
        with self.assertRaises(ValueError):
            https.expected_url(p)

    def test_injected_no_network_response_has_unwitnessed_digest(self):
        plan, raw = synthetic_1m()
        bars, proof = https.inspect_with_injected_transport(
            plan, lambda _: synthetic_envelope(plan, raw)
        )
        self.assertEqual(len(bars), 480)
        self.assertEqual(proof["status"], "UNATTESTED_TRANSPORT_GEOMETRY_ONLY")
        self.assertEqual(proof["native_rows_validated"], 480)
        self.assertEqual(proof["raw_bytes"], len(raw))
        self.assertFalse(proof["independent_timestamp_verified"])
        self.assertFalse(proof["trading_authorized"])
        self.assertFalse(proof["external_evidence_replication_verified"])

    def test_reject_wrong_domain_redirect_status_type_and_oversize(self):
        plan, raw = synthetic_1m()
        envelope = synthetic_envelope(plan, raw)
        for field, bad in (
            ("final_url", "https://evil.invalid/fapi/v1/klines"),
            ("status", 301),
            ("status", 429),
            ("status", True),
            ("content_type", "text/html"),
            ("raw_body", b"x" * 256001),
            ("received_ms", START_MS-1),
            ("received_ms", START_MS+60001),
            ("received_ms", "2026-10-15"),
            ("provenance", "SIGNED_BINANCE_ATTESTATION"),
        ):
            with self.subTest(field=field, bad=str(bad)[:40]):
                e = https.TransportEnvelope(**{
                    **envelope.__dict__, field: bad
                })
                with self.assertRaises(ValueError):
                    https.inspect_transport_response(plan, e)

    def test_wrong_row_geometry_rejected_even_when_http_200(self):
        plan, raw = synthetic_1m()
        rows = json.loads(raw)
        rows[10][0] = rows[9][0]
        bad = json.dumps(rows).encode()
        with self.assertRaises(ValueError):
            https.inspect_with_injected_transport(
                plan, lambda _: synthetic_envelope(plan, bad)
            )

    def test_injected_adapter_cannot_claim_verified_tls(self):
        plan, raw = synthetic_1m()
        e = synthetic_envelope(plan, raw)
        elevated = https.TransportEnvelope(**{
            **e.__dict__,
            "provenance": "LOCAL_SYSTEM_CA_TLS_NO_INDEPENDENT_WITNESS",
        })
        with self.assertRaisesRegex(ValueError, "synthetic"):
            https.inspect_with_injected_transport(plan, lambda _: elevated)

    def test_https_is_explicitly_disabled_by_default(self):
        plan, _ = synthetic_1m()
        with patch.object(https, "build_opener") as network:
            with self.assertRaises(PermissionError):
                https.optional_https_get(plan)
            network.assert_not_called()
            for timeout in (-2, 0, 9, float("inf"), True):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    https.optional_https_get(
                        plan, network_approved=True, timeout_seconds=timeout
                    )
            network.assert_not_called()

    def test_https_rejects_future_request_before_connection(self):
        plan, _ = synthetic_1m()
        with patch.object(https.time, "time_ns", return_value=(START_MS-1)*1_000_000):
            with patch.object(https, "build_opener") as network:
                with self.assertRaisesRegex(ValueError, "before it occurs"):
                    https.optional_https_get(plan, network_approved=True)
                network.assert_not_called()

    def test_https_rejects_expired_cutoff_before_connection(self):
        plan, _ = synthetic_1m()
        with patch.object(https.time, "time_ns",
                          return_value=(START_MS+60001)*1_000_000):
            with patch.object(https, "build_opener") as network:
                with self.assertRaisesRegex(ValueError, "Deadline already missed"):
                    https.optional_https_get(plan, network_approved=True)
                network.assert_not_called()

    def test_mocked_ca_eligible_approved_transport_has_no_redirect(self):
        plan, raw = synthetic_1m()
        class FakeResponse:
            status = 200
            headers = {"Content-Type": "application/json"}
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                return False
            def geturl(self):
                return https.expected_url(plan)
            def read(self, limit):
                assert limit == 256001
                return raw
        class FakeOpener:
            def open(self, request, *, timeout):
                assert request.full_url == https.expected_url(plan)
                assert request.get_method() == "GET"
                assert 0 < timeout <= 8
                return FakeResponse()
        with patch.object(https.time, "time_ns",
                          return_value=(START_MS+1000)*1_000_000):
            with patch.object(https, "build_opener", return_value=FakeOpener()) as builder:
                env = https.optional_https_get(plan, network_approved=True)
                self.assertEqual(env.received_ms, START_MS+1000)
                self.assertEqual(env.provenance,
                                 "LOCAL_SYSTEM_CA_TLS_NO_INDEPENDENT_WITNESS")
                self.assertEqual(builder.call_count, 1)
                self.assertTrue(any(isinstance(x, https._NoRedirects)
                                    for x in builder.call_args.args))
                self.assertTrue(any(
                    type(x).__name__ == "ProxyHandler" and x.proxies == {}
                    for x in builder.call_args.args))
                _, proof = https.inspect_transport_response(plan, env)
                self.assertFalse(proof["independent_timestamp_verified"])

    def test_rejection_and_tls_failure_paths_fail_closed(self):
        plan, _ = synthetic_1m()
        with patch.object(https.time, "time_ns",
                          return_value=(START_MS+1000)*1_000_000):
            with patch.object(https, "build_opener") as opener:
                opener.return_value.open.side_effect = https.URLError("blocked")
                with self.assertRaisesRegex(ValueError, "failed closed"):
                    https.optional_https_get(plan, network_approved=True)
        redirect = https._NoRedirects()
        with self.assertRaisesRegex(ValueError, "Redirect forbidden"):
            redirect.redirect_request(None, None, 302, "redirection", {},
                                      "https://attacker.invalid/")


if __name__ == "__main__":
    import unittest
    unittest.main()
