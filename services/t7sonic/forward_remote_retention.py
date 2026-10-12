"""Phase 2Z — offline, content-addressed external-retention contract.

This module does NOT connect to remote storage, require cloud credentials,
write local source data or certify that anything is stored off-VPS. It
defines a strict immutable-object *request plan* and verifies an injected
synthetic store's exact-version readback against a complete Phase 2Y bundle.

A mock receipt, readback and object-lock claim from the same caller can be
forged. Genuine certification requires independently approved off-VPS
provider credentials/permissions, storage lock policy, immutable provider
audit trail, independently sourced readback, and external witnessed time.
Do not label this code as operational replication or run it in production.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re

from services.t7sonic.forward_retention import (
    MAX_ARCHIVE_BYTES, inspect_offline_bundle,
)

ROOT = "t7sonic/v7sonic-forward-research/sha256"
RETENTION_AFTER = datetime(2027, 4, 1, tzinfo=timezone.utc)
SIMULATED_PROVIDER = "OFFLINE_FAKE_PROVIDER_ONLY"
PLAN_STATUS = "OFFLINE_REMOTE_RETENTION_REQUEST_NOT_SENT"
MAX_RECEIPT_TEXT = 256


def _sha(value: object) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _safe_id(value: object) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= MAX_RECEIPT_TEXT
            and bool(re.fullmatch(r"[A-Za-z0-9._+:-]+", value))
            and value not in (".", ".."))


def plan_offline_replication(archive: bytes) -> dict:
    """Prepare one immutable content-addressed object without uploading."""
    proof = inspect_offline_bundle(archive)
    digest = sha256(archive).hexdigest()
    if proof["archive_sha256"] != digest:
        raise ValueError("Bundle digest not stable")
    prefix = f"{ROOT}/{digest[:2]}"
    key = f"{prefix}/{digest}.zip"
    return {
        "schema": 1,
        "status": PLAN_STATUS,
        "storage_provider": "NOT_SELECTED",
        "storage_account": "NOT_SELECTED",
        "bucket_or_container": "NOT_SELECTED",
        "object_key": key,
        "archive_sha256": digest,
        "archive_bytes": len(archive),
        "decision_precommit_sha256": proof["precommit_sha256"],
        "unsigned_witness_sha256": proof["witness_imprint_sha256"],
        "source_responses": proof["source_response_count"],
        "gap_record": proof["gap_record"],
        "create_if_absent": True,
        "overwrite_allowed": False,
        "delete_allowed": False,
        "object_version_id_required": True,
        "provider_object_lock_mode_required": "COMPLIANCE",
        "minimum_retention_exclusive_utc": RETENTION_AFTER.isoformat(),
        "server_side_checksum_algorithm": "SHA256",
        "independent_readback_required": True,
        "independent_off_server_audit_required": True,
        "source_archive_is_not_a_signed_exchange_response": True,
        "live_network_implemented": False,
        "remote_write_implemented": False,
        "external_tsa_verified": False,
        "production_engine_may_restart": False,
        "paper_study_authorized": False,
        "trading_authorized": False,
    }


def verify_simulated_readback(
    plan: dict, *, receipt: dict,
    retrieved_object: bytes,
) -> dict:
    """Check claimed exact object/version readback, *not* its independence.

    Accepts only fake-provider fixture receipts: a real provider could not
    pass by merely supplying self-reported metadata. Real-provider
    attestation is intentionally not implemented.
    """
    if not isinstance(plan, dict) or not isinstance(receipt, dict):
        raise ValueError("Plan and fake-provider receipt required")
    if (plan.get("status") != PLAN_STATUS or
            plan.get("live_network_implemented") is not False or
            plan.get("remote_write_implemented") is not False or
            plan.get("storage_provider") != "NOT_SELECTED" or
            plan.get("create_if_absent") is not True or
            plan.get("overwrite_allowed") is not False or
            plan.get("delete_allowed") is not False or
            plan.get("provider_object_lock_mode_required") != "COMPLIANCE" or
            plan.get("minimum_retention_exclusive_utc") != RETENTION_AFTER.isoformat() or
            plan.get("server_side_checksum_algorithm") != "SHA256" or
            plan.get("external_tsa_verified") is not False or
            plan.get("trading_authorized") is not False):
        raise ValueError("Unapproved storage plan cannot be certified")
    digest = plan.get("archive_sha256")
    if not _sha(digest) or plan.get("object_key") != (
            f"{ROOT}/{digest[:2]}/{digest}.zip"):
        raise ValueError("Storage key must be SHA256 content addressed")
    if (not isinstance(retrieved_object, bytes) or
            not 100 <= len(retrieved_object) <= MAX_ARCHIVE_BYTES or
            plan.get("archive_bytes") != len(retrieved_object) or
            sha256(retrieved_object).hexdigest() != digest):
        raise ValueError("Read-back bytes differ from required source archive")

    # Revalidate all 24 source byte hashes + decision/witness internals.
    audited = inspect_offline_bundle(retrieved_object)
    if (audited["precommit_sha256"] != plan.get("decision_precommit_sha256") or
            audited["witness_imprint_sha256"] != plan.get("unsigned_witness_sha256") or
            audited["source_response_count"] != plan.get("source_responses") or
            audited["gap_record"] is not plan.get("gap_record")):
        raise ValueError("Archive evidence does not match storage contract")

    required_fields = {
        "provider", "account_id", "container", "object_key",
        "version_id", "checksum_sha256", "object_bytes",
        "object_lock_mode", "retain_until_utc",
        "put_if_absent", "overwrite_attempted",
        "readback_independent", "external_time_verified",
        "provider_signature_verified",
    }
    if set(receipt) != required_fields:
        raise ValueError("Incomplete or unreviewed storage receipt")
    try:
        retain_until = datetime.fromisoformat(receipt["retain_until_utc"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid claimed provider retention date") from exc
    if (retain_until.tzinfo is None or
            retain_until.astimezone(timezone.utc) < RETENTION_AFTER):
        raise ValueError("Claimed retention does not meet frozen minimum")

    if (receipt["provider"] != SIMULATED_PROVIDER or
            not _safe_id(receipt["account_id"]) or
            not _safe_id(receipt["container"]) or
            not _safe_id(receipt["version_id"]) or
            receipt["object_key"] != plan["object_key"] or
            receipt["checksum_sha256"] != digest or
            type(receipt["object_bytes"]) is not int or
            receipt["object_bytes"] != len(retrieved_object) or
            receipt["object_lock_mode"] != "COMPLIANCE" or
            receipt["put_if_absent"] is not True or
            receipt["overwrite_attempted"] is not False or
            receipt["readback_independent"] is not False or
            receipt["external_time_verified"] is not False or
            receipt["provider_signature_verified"] is not False):
        raise ValueError("Remote receipt does not match unsigned test restrictions")

    return {
        "status": "SIMULATED_REPLICA_READBACK_PASS_NOT_OFF_VPS_PROOF",
        "content_addressed_object_key": plan["object_key"],
        "archive_sha256": digest,
        "source_response_count": audited["source_response_count"],
        "gap_record": audited["gap_record"],
        "receipt_version_id_untrusted": receipt["version_id"],
        "readback_sha256_matches": True,
        "provider_independently_verified": False,
        "provider_lock_policy_independently_verified": False,
        "off_vps_replication_verified": False,
        "independent_timestamp_verified": False,
        "paper_study_certified": False,
        "trading_authorized": False,
    }
