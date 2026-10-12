"""Phase 2X: synthetic/offline RFC3161 TSA HTTP handoff only.

No network connections; no independent certificate authority is selected;
no timestamp response is cryptographically accepted by this test fixture.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from test_t7sonic_forward_witness import sample
from services.t7sonic.forward_witness import assemble_witness_request
from services.t7sonic.forward_rfc3161 import (
    make_unsigned_rfc3161_query, _openssl,
)
from services.t7sonic.forward_tsa_handoff import (
    prepare_offline_tsa_post, inspect_unverified_tsa_http_envelope,
)

TEST_ENDPOINT = "https://tsa.test-provider.com/rfc3161"
FAKE_CA_SHA = "a" * 64
POLICY_OID = "1.2.3.4.5"


def offline_fixture():
    packet, source = sample()
    manifest = assemble_witness_request(packet, source)
    query = make_unsigned_rfc3161_query(manifest)
    return manifest, query


def plan(manifest, query):
    return prepare_offline_tsa_post(
        manifest, query, tsa_endpoint=TEST_ENDPOINT,
        approved_ca_sha256=FAKE_CA_SHA,
        approved_policy_oid=POLICY_OID,
    )


class TsaHandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.query = offline_fixture()

    def test_valid_synthetic_submission_plan_is_non_networked(self):
        spec = plan(self.manifest, self.query)
        self.assertEqual(spec["status"], "OFFLINE_TSA_SUBMISSION_PLAN_NOT_SENT")
        self.assertEqual(spec["http_method"], "POST")
        self.assertEqual(spec["content_type"], "application/timestamp-query")
        self.assertEqual(spec["accept"], "application/timestamp-reply")
        self.assertEqual(spec["tsa_endpoint"], TEST_ENDPOINT)
        self.assertEqual(spec["witness_imprint_sha256"],
                         self.manifest["witness_content_sha256"])
        self.assertFalse(spec["network_call_implemented"])
        self.assertFalse(spec["request_sent"])
        self.assertFalse(spec["signed_token_verified"])
        self.assertFalse(spec["paper_observation_approved"])
        self.assertFalse(spec["trading_authorized"])

    def test_disallow_unsafe_origin_redirect_targets_and_ambiguous_urls(self):
        urls = [
            "http://tsa.test-provider.com/rfc3161",
            "https://localhost/rfc3161",
            "https://127.0.0.1/rfc3161",
            "https://192.168.1.1/rfc3161",
            "https://[::1]/rfc3161",
            "https://tsa.example/rfc3161",
            "https://tsa.internal/rfc3161",
            "https://tsa.test-provider.com/rfc3161?token=abc",
            "https://user:pass@tsa.test-provider.com/rfc3161",
            "https://tsa.test-provider.com:8443/rfc3161",
            "https://tsa.test-provider.com/rfc3161#fragment",
            "https://tsa.test-provider.com/../rfc3161",
            "https://tsa.test-provider.com/%2e%2e/rfc3161",
            "https://tsa.test-provider.com//rfc3161",
            "https://tsa.test-provider.com\\evil/rfc3161",
            "https://tsa.test-provider.com./rfc3161",
            "https://tsa.test-provider.com",
        ]
        for endpoint in urls:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                prepare_offline_tsa_post(
                    self.manifest, self.query, tsa_endpoint=endpoint,
                    approved_ca_sha256=FAKE_CA_SHA,
                    approved_policy_oid=POLICY_OID,
                )

    def test_missing_preapproved_ca_and_policy_refused(self):
        for digest, oid in (
            ("A"*64, POLICY_OID),
            ("a"*63, POLICY_OID),
            ("0"*64, ""),
            (FAKE_CA_SHA, "not-an-oid"),
            (FAKE_CA_SHA, "1.2"),
        ):
            with self.subTest(digest=digest, oid=oid), self.assertRaises(PermissionError):
                prepare_offline_tsa_post(
                    self.manifest, self.query, tsa_endpoint=TEST_ENDPOINT,
                    approved_ca_sha256=digest,
                    approved_policy_oid=oid,
                )

    def test_changed_witness_and_unrelated_query_refused(self):
        altered = deepcopy(self.manifest)
        altered["witness_content_sha256"] = "b" * 64
        with self.assertRaises(ValueError):
            plan(altered, self.query)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"other.tsq"
            _openssl("-query", "-digest", "f"*64, "-sha256",
                     "-cert", "-out", str(path))
            other_query = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "does not bind"):
            plan(self.manifest, other_query)
        with self.assertRaises(ValueError):
            plan(self.manifest, b"not_der")

    def test_unverified_envelope_never_claims_signed_tsa_receipt(self):
        p = plan(self.manifest, self.query)
        payload = b"synthetic DER-shaped placeholder NOT a real token"
        report = inspect_unverified_tsa_http_envelope(
            p, endpoint=TEST_ENDPOINT, status=200,
            content_type="application/timestamp-reply; charset=binary",
            raw_reply=payload,
        )
        self.assertEqual(report["status"], "UNVERIFIED_TSA_HTTP_REPLY_ONLY")
        self.assertFalse(report["rfc3161_signature_verified"])
        self.assertFalse(report["receipt_time_verified"])
        self.assertFalse(report["paper_study_approved"])

    def test_redirect_http_error_media_type_and_huge_body_refused(self):
        p = plan(self.manifest, self.query)
        for field, value in (
            ("endpoint", "https://different.test-provider.com/rfc3161"),
            ("status", 302),
            ("status", 429),
            ("status", True),
            ("content_type", "application/json"),
            ("raw_reply", b"x" * 65537),
            ("raw_reply", b""),
        ):
            kwargs = {
                "endpoint": TEST_ENDPOINT,
                "status": 200,
                "content_type": "application/timestamp-reply",
                "raw_reply": b"x" * 64,
            }
            kwargs[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                inspect_unverified_tsa_http_envelope(p, **kwargs)

    def test_fake_claim_of_sent_or_verified_response_refused(self):
        p = plan(self.manifest, self.query)
        for field in ("request_sent", "network_call_implemented",
                      "signed_token_verified"):
            changed = deepcopy(p)
            changed[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                inspect_unverified_tsa_http_envelope(
                    changed, endpoint=TEST_ENDPOINT, status=200,
                    content_type="application/timestamp-reply", raw_reply=b"x"*64,
                )


if __name__ == "__main__":
    unittest.main()
