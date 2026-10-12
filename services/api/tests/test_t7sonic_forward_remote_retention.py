"""Phase 2Z — synthetic memory-store fixture only, no remote/network."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from test_t7sonic_forward_retention import synthetic_watch, synthetic_gap
from services.t7sonic.forward_retention import make_offline_bundle
from services.t7sonic.forward_remote_retention import (
    SIMULATED_PROVIDER, RETENTION_AFTER,
    plan_offline_replication, verify_simulated_readback,
)


class _FakeOffbox:
    """No network: ephemeral dict, NOT independent immutable storage."""
    def __init__(self):
        self.objects = {}

    def put_once(self, plan, data):
        key = plan["object_key"]
        if key in self.objects:
            raise FileExistsError("Mock create-if-absent prevents overwrites")
        version = f"synthetic-version-{len(self.objects)+1}"
        self.objects[key] = (version, bytes(data))
        return {
            "provider": SIMULATED_PROVIDER,
            "account_id": "synthetic-nonprod-account",
            "container": "synthetic-nonprod-bucket",
            "object_key": key,
            "version_id": version,
            "checksum_sha256": sha256(data).hexdigest(),
            "object_bytes": len(data),
            "object_lock_mode": "COMPLIANCE",
            "retain_until_utc": RETENTION_AFTER.isoformat(),
            "put_if_absent": True,
            "overwrite_attempted": False,
            "readback_independent": False,
            "external_time_verified": False,
            "provider_signature_verified": False,
        }

    def read_exact(self, key, version):
        active_version, data = self.objects[key]
        if version != active_version:
            raise FileNotFoundError("Unknown synthetic version")
        return bytes(data)


def sample_payload(gap=False):
    packet, witness, sources = synthetic_gap() if gap else synthetic_watch()
    archive = make_offline_bundle(packet, witness, sources)
    return archive, plan_offline_replication(archive)


class RemoteRetentionContractTests(unittest.TestCase):
    def test_full_watch_replication_dry_run_and_independent_flags_false(self):
        blob, plan = sample_payload()
        self.assertEqual(plan["source_responses"], 24)
        self.assertTrue(plan["create_if_absent"])
        self.assertFalse(plan["overwrite_allowed"])
        self.assertEqual(plan["provider_object_lock_mode_required"], "COMPLIANCE")
        self.assertEqual(plan["storage_provider"], "NOT_SELECTED")
        self.assertFalse(plan["remote_write_implemented"])
        self.assertFalse(plan["paper_study_authorized"])
        self.assertTrue(plan["object_key"].endswith(
            "/" + sha256(blob).hexdigest() + ".zip"
        ))
        store = _FakeOffbox()
        receipt = store.put_once(plan, blob)
        retrieved = store.read_exact(plan["object_key"], receipt["version_id"])
        proof = verify_simulated_readback(plan, receipt=receipt,
                                          retrieved_object=retrieved)
        self.assertTrue(proof["readback_sha256_matches"])
        self.assertEqual(proof["source_response_count"], 24)
        self.assertFalse(proof["off_vps_replication_verified"])
        self.assertFalse(proof["provider_independently_verified"])
        self.assertFalse(proof["independent_timestamp_verified"])
        self.assertFalse(proof["trading_authorized"])

    def test_gap_requires_no_source_bodies_but_still_remote_receipt(self):
        blob, plan = sample_payload(gap=True)
        self.assertEqual(plan["source_responses"], 0)
        self.assertTrue(plan["gap_record"])
        store = _FakeOffbox()
        receipt = store.put_once(plan, blob)
        output = verify_simulated_readback(
            plan, receipt=receipt,
            retrieved_object=store.read_exact(plan["object_key"], receipt["version_id"])
        )
        self.assertTrue(output["gap_record"])
        self.assertEqual(output["source_response_count"], 0)
        self.assertFalse(output["off_vps_replication_verified"])

    def test_double_write_and_incorrect_version_refused_by_fake_backend(self):
        blob, plan = sample_payload()
        store = _FakeOffbox()
        receipt = store.put_once(plan, blob)
        with self.assertRaises(FileExistsError):
            store.put_once(plan, blob)
        with self.assertRaises(FileNotFoundError):
            store.read_exact(plan["object_key"], "not-correct-version")
        self.assertEqual(
            store.read_exact(plan["object_key"], receipt["version_id"]), blob
        )

    def test_tampered_and_truncated_and_swapped_archives_cannot_validate(self):
        blob, plan = sample_payload()
        store = _FakeOffbox()
        receipt = store.put_once(plan, blob)
        gap_blob, _ = sample_payload(gap=True)
        for item in (
            blob[:-1],
            blob[:100],
            bytes([blob[0] ^ 1]) + blob[1:],
            gap_blob,
        ):
            with self.subTest(length=len(item)), self.assertRaises(ValueError):
                verify_simulated_readback(
                    plan, receipt=receipt, retrieved_object=item
                )

    def test_false_remotely_signed_or_audited_receipt_refused(self):
        blob, plan = sample_payload()
        receipt = _FakeOffbox().put_once(plan, blob)
        for key, value in (
            ("provider", "AWS_S3_REAL"),
            ("account_id", "forged/account"),
            ("container", ".."),
            ("object_key", "../traversal"),
            ("version_id", ""),
            ("checksum_sha256", "f"*64),
            ("object_bytes", 0),
            ("object_lock_mode", "GOVERNANCE"),
            ("retain_until_utc", "2026-12-29T00:00:00+00:00"),
            ("retain_until_utc", "2030-01-01"),
            ("put_if_absent", False),
            ("overwrite_attempted", True),
            ("readback_independent", True),
            ("external_time_verified", True),
            ("provider_signature_verified", True),
        ):
            forged = deepcopy(receipt)
            forged[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                verify_simulated_readback(
                    plan, receipt=forged, retrieved_object=blob
                )

    def test_plan_mismatch_and_fake_deployment_switch_refused(self):
        blob, plan = sample_payload()
        receipt = _FakeOffbox().put_once(plan, blob)
        for field, value in (
            ("object_key", "t7sonic/fake"),
            ("archive_sha256", "f"*64),
            ("storage_provider", "S3"),
            ("provider_object_lock_mode_required", "GOVERNANCE"),
            ("minimum_retention_exclusive_utc", "2026-01-01T00:00:00+00:00"),
            ("live_network_implemented", True),
            ("remote_write_implemented", True),
            ("external_tsa_verified", True),
            ("trading_authorized", True),
        ):
            modified = deepcopy(plan)
            modified[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_simulated_readback(
                    modified, receipt=receipt, retrieved_object=blob
                )

    def test_malformed_archive_cannot_be_planned(self):
        for data in (b"", b"notzip", b"1" * 200):
            with self.assertRaises(ValueError):
                plan_offline_replication(data)


if __name__ == "__main__":
    unittest.main()
