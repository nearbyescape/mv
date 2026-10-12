"""Offline evidence export tests: synthetic source bytes, no remote storage."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile, ZipInfo, ZIP_STORED
import unittest

from test_t7sonic_forward_witness import sample
from app.research.t7sonic_forward_protocol import START_MS, STEP_MS
from app.research.t7sonic_forward_coverage import make_synthetic_gap
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_witness import (
    FRAMES, assemble_witness_request,
)
from services.t7sonic.forward_retention import (
    make_offline_bundle, inspect_offline_bundle,
    PACKET_FILE, WITNESS_FILE,
)


def synthetic_watch():
    packet, sources = sample()
    actual = {}
    for symbol in MARKETS:
        actual[symbol] = {}
        for frame in FRAMES:
            raw = (f"{symbol}-{frame}-FAKE").encode()
            actual[symbol][frame] = raw
            sources[symbol]["frames"][frame]["raw_bytes"] = len(raw)
            sources[symbol]["frames"][frame]["raw_sha256"] = sha256(raw).hexdigest()
    manifest = assemble_witness_request(packet, sources)
    return packet, manifest, actual


def synthetic_gap():
    first, _, _ = synthetic_watch()
    packet = make_synthetic_gap(
        boundary_ms=START_MS + STEP_MS,
        recorded_ms=START_MS + STEP_MS + 65_000,
        missing_reasons={"ETHUSDT": "SOURCE_STALE"},
        previous_sha256=first["batch_sha256"],
        previous_boundary_ms=START_MS,
    )
    manifest = assemble_witness_request(
        packet, {},
        previous_sha256=first["batch_sha256"],
        previous_boundary_ms=START_MS,
    )
    return packet, manifest, {}


def modified_zip(original, transform):
    with ZipFile(BytesIO(original)) as z:
        items = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    items = transform(items)
    dst = BytesIO()
    with ZipFile(dst, "w", compression=ZIP_STORED) as z:
        for name, raw in items:
            z.writestr(name, raw)
    return dst.getvalue()


class OfflineRetentionTests(unittest.TestCase):
    def test_all_24_raw_source_bytes_bound_to_witness_packet(self):
        packet, witness, source = synthetic_watch()
        archive = make_offline_bundle(packet, witness, source)
        proof = inspect_offline_bundle(archive)
        self.assertEqual(proof["source_response_count"], 24)
        self.assertEqual(proof["precommit_sha256"], packet["batch_sha256"])
        self.assertEqual(proof["witness_imprint_sha256"],
                         witness["witness_content_sha256"])
        self.assertEqual(proof["archive_sha256"], sha256(archive).hexdigest())
        self.assertFalse(proof["remote_storage_verified"])
        self.assertFalse(proof["independent_timestamp_verified"])
        self.assertFalse(proof["trading_authorized"])
        with ZipFile(BytesIO(archive)) as z:
            self.assertEqual(len(z.infolist()), 26)
            self.assertEqual(z.infolist()[0].filename, PACKET_FILE)
            self.assertEqual(z.infolist()[1].filename, WITNESS_FILE)
        self.assertEqual(archive, make_offline_bundle(packet, witness, source))

    def test_gap_must_store_absence_explicitly_with_no_source_payloads(self):
        packet, witness, sources = synthetic_gap()
        archive = make_offline_bundle(packet, witness, sources)
        result = inspect_offline_bundle(archive)
        self.assertTrue(result["gap_record"])
        self.assertEqual(result["source_response_count"], 0)
        with ZipFile(BytesIO(archive)) as z:
            self.assertEqual(z.namelist(), [PACKET_FILE, WITNESS_FILE])
        with self.assertRaises(ValueError):
            make_offline_bundle(packet, witness, {"BTCUSDT": {}})

    def test_missing_and_mutated_and_extra_input_bytes_rejected(self):
        packet, witness, sources = synthetic_watch()
        for variant in ("missing_market", "missing_frame", "changed_raw", "oversized"):
            bad = deepcopy(sources)
            if variant == "missing_market":
                bad.pop("BNBUSDT")
            elif variant == "missing_frame":
                bad["ETHUSDT"].pop("1h")
            elif variant == "changed_raw":
                bad["BTCUSDT"]["1m"] += b"TAMPER"
            else:
                bad["SOLUSDT"]["4h"] = b"x"*256001
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                make_offline_bundle(packet, witness, bad)

    def test_tampered_zip_member_rejected_without_extraction(self):
        packet, witness, raw = synthetic_watch()
        archive = make_offline_bundle(packet, witness, raw)
        changed = modified_zip(archive, lambda pairs: [
            (name, blob+b"x" if name == "source/BTCUSDT/1m.bin" else blob)
            for name, blob in pairs
        ])
        with self.assertRaises(ValueError):
            inspect_offline_bundle(changed)

    def test_removed_extra_duplicate_and_reordered_member_refused(self):
        packet, witness, sources = synthetic_watch()
        archive = make_offline_bundle(packet, witness, sources)
        alterations = [
            lambda parts: parts[:-1],
            lambda parts: parts+[("source/FAKEUSDT/1m.bin", b"x")],
            lambda parts: list(reversed(parts)),
            lambda parts: parts+[parts[-1]],
        ]
        for fn in alterations:
            with self.subTest(operation=fn.__code__.co_firstlineno):
                with self.assertRaises(ValueError):
                    inspect_offline_bundle(modified_zip(archive, fn))

    def test_invalid_or_unbounded_archive_rejected(self):
        for blob in (b"not zip" * 18, b"x" * 8, b""):
            with self.subTest(size=len(blob)), self.assertRaises(ValueError):
                inspect_offline_bundle(blob)

    def test_decision_witness_pair_substitution_rejected(self):
        packet, witness, sources = synthetic_watch()
        bad = deepcopy(witness)
        bad["precommit_batch_sha256"] = "a"*64
        with self.assertRaises(ValueError):
            make_offline_bundle(packet, bad, sources)
        modified = deepcopy(packet)
        modified["observations"][0]["candidate_active"] = True
        with self.assertRaises(ValueError):
            make_offline_bundle(modified, witness, sources)


if __name__ == "__main__":
    unittest.main()
