"""Phase 2W RFC3161 offline crypto tests: only self-created mock TSA certificates.

No real trading data, network calls, stored private keys or production
trust anchors. A locally minted TSA is NEVER eligible as an independent
source of paper-study timestamp evidence.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

from test_t7sonic_forward_witness import sample
from services.t7sonic.forward_witness import assemble_witness_request
from services.t7sonic.forward_rfc3161 import (
    make_unsigned_rfc3161_query,
    verify_offline_rfc3161_response,
)

POLICY = "1.2.3.4.5"


def run(*args):
    done = subprocess.run(
        ["openssl", *map(str, args)], capture_output=True,
        timeout=15, check=False, env={"PATH": os.defpath},
    )
    if done.returncode:
        raise AssertionError(
            "Local OpenSSL mock-TSA fixture setup failed: " +
            done.stderr.decode("utf-8", "replace")[:1200]
        )
    return done.stdout.decode("utf-8", "replace")


class OfflineRfc3161Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="t7sonic-fake-tsa-")
        cls.d = Path(cls.directory.name)
        cls.key = cls.d / "fake-tsa.key"
        cls.cert = cls.d / "fake-tsa.pem"
        run(
            "req", "-new", "-x509", "-newkey", "rsa:2048",
            "-nodes", "-days", "2",
            "-keyout", cls.key, "-out", cls.cert,
            "-subj", "/CN=SYNTHETIC UNIT TEST TSA NEVER A REAL TRUST ANCHOR",
            "-addext", "extendedKeyUsage = critical,timeStamping",
            "-addext", "keyUsage = critical,digitalSignature",
        )
        cls.trust = cls.cert.read_bytes()
        cls.trust_sha = sha256(cls.trust).hexdigest()
        cls.cfg = cls.d / "fake-tsa.cnf"
        (cls.d / "serial").write_text("01\n")
        cls.cfg.write_text(
            "[tsa]\n"
            "default_tsa = test_tsa\n"
            "[test_tsa]\n"
            f"serial = {cls.d / 'serial'}\n"
            "crypto_device = builtin\n"
            f"signer_cert = {cls.cert}\n"
            f"certs = {cls.cert}\n"
            f"signer_key = {cls.key}\n"
            "signer_digest = sha256\n"
            f"default_policy = {POLICY}\n"
            f"other_policies = {POLICY}\n"
            "digests = sha256\n"
            "accuracy = secs:1\n"
            "ordering = yes\n"
            "tsa_name = yes\n"
            "ess_cert_id_chain = no\n"
            "ess_cert_id_alg = sha256\n"
        )
        packet, sources = sample()
        cls.manifest = assemble_witness_request(packet, sources)
        cls.query = make_unsigned_rfc3161_query(cls.manifest)
        (cls.d / "query.tsq").write_bytes(cls.query)
        response = cls.d / "fake-response.tsr"
        run(
            "ts", "-reply", "-config", cls.cfg,
            "-queryfile", cls.d / "query.tsq",
            "-out", response,
        )
        cls.response = response.read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def checked(self, **overrides):
        options = {
            "approved_trust_anchor_sha256": self.trust_sha,
            "approved_policy_oid": POLICY,
        }
        options.update(overrides)
        return verify_offline_rfc3161_response(
            self.manifest, self.query, self.response, self.trust, **options
        )

    def test_der_query_binds_exact_24_source_manifest_digest_and_nonce(self):
        self.assertTrue(16 <= len(self.query) <= 4096)
        self.assertEqual(self.manifest["source_receipt_count"], 24)
        text = run("ts", "-query", "-in", self.d/"query.tsq", "-text")
        self.assertIn("Nonce:", text)
        self.assertIn("Hash Algorithm: sha256", text)
        self.assertIn("Certificate required: yes", text)

    def test_valid_local_signature_must_fail_if_signed_time_outside_window(self):
        # Token is cryptographically valid but created before October 15.
        # Never pretend that this mock TSA provides an independent witness.
        verified = run(
            "ts", "-verify", "-queryfile", self.d/"query.tsq",
            "-in", self.d/"fake-response.tsr", "-CAfile", self.cert,
        )
        self.assertIn("Verification: OK", verified)
        with self.assertRaisesRegex(ValueError, "OUTSIDE forward"):
            self.checked()

    def test_trust_digest_and_policy_must_be_pinned_not_inferred_from_token(self):
        with self.assertRaises(PermissionError):
            self.checked(approved_trust_anchor_sha256="0"*64)
        with self.assertRaises(PermissionError):
            self.checked(approved_policy_oid="")
        with self.assertRaises(ValueError):
            self.checked(approved_policy_oid="1.2.3.4.6")

    def test_query_digest_mismatch_and_nonce_change_rejected(self):
        wrong = deepcopy(self.manifest)
        wrong["witness_content_sha256"] = "f"*64
        with self.assertRaises(ValueError):
            verify_offline_rfc3161_response(
                wrong, self.query, self.response, self.trust,
                approved_trust_anchor_sha256=self.trust_sha,
                approved_policy_oid=POLICY,
            )
        # Fresh random nonce with same SHA imprint must not match signed token.
        different = make_unsigned_rfc3161_query(self.manifest)
        self.assertNotEqual(self.query, different)
        with self.assertRaises(ValueError):
            verify_offline_rfc3161_response(
                self.manifest, different, self.response, self.trust,
                approved_trust_anchor_sha256=self.trust_sha,
                approved_policy_oid=POLICY,
            )

    def test_mutated_token_and_wrong_root_fail_signature(self):
        corrupted = bytearray(self.response)
        corrupted[-25] ^= 1
        with self.assertRaises(ValueError):
            verify_offline_rfc3161_response(
                self.manifest, self.query, bytes(corrupted), self.trust,
                approved_trust_anchor_sha256=self.trust_sha,
                approved_policy_oid=POLICY,
            )
        # A different synthetic CA cannot authorize original mock token.
        with tempfile.TemporaryDirectory(prefix="t7sonic-other-ca-") as tmp:
            cert = Path(tmp)/"other.pem"
            key = Path(tmp)/"other.key"
            run(
                "req", "-new", "-x509", "-newkey", "rsa:2048",
                "-nodes", "-days", "2", "-keyout", key, "-out", cert,
                "-subj", "/CN=Untrusted Fake TSA",
                "-addext", "extendedKeyUsage = critical,timeStamping",
                "-addext", "keyUsage = critical,digitalSignature",
            )
            other = cert.read_bytes()
            with self.assertRaises(ValueError):
                verify_offline_rfc3161_response(
                    self.manifest, self.query, self.response, other,
                    approved_trust_anchor_sha256=sha256(other).hexdigest(),
                    approved_policy_oid=POLICY,
                )


if __name__ == "__main__":
    unittest.main()
