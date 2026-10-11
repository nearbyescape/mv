"""Synthetic-only external witness request binding. No network, no live evidence."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from urllib.parse import urlencode
import unittest

from app.research.t7sonic_forward_protocol import (
    START_MS, STEP_MS, make_synthetic_precommit,
)
from app.research.t7sonic_forward_coverage import make_synthetic_gap
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_acquisition import request_plan
from services.t7sonic.forward_witness import (
    assemble_witness_request, validate_unsigned_witness_request,
)


def sample():
    reports = [{"symbol": sym, "watch_hypotheses": []} for sym in MARKETS]
    features = {sym: sha256(sym.encode()).hexdigest() for sym in MARKETS}
    packet = make_synthetic_precommit(
        boundary_ms=START_MS, receipt_ms=START_MS+1000,
        market_reports=reports, feature_source_hashes=features
    )
    sources = {}
    for sym in MARKETS:
        frames = {}
        for frame in ("1m", "15m", "1h", "4h"):
            p = request_plan(sym, frame, START_MS)
            frames[frame] = {
                "status": "UNATTESTED_TRANSPORT_GEOMETRY_ONLY",
                "symbol": sym, "frame": frame,
                "boundary_ms": START_MS,
                "raw_sha256": sha256(f"{sym}-{frame}-FAKE".encode()).hexdigest(),
                "raw_bytes": 40000,
                "expected_url": "https://fapi.binance.com/fapi/v1/klines?" +
                                urlencode(p["query"]),
                "receipt_ms_local_clock_unverified": START_MS+1000,
                "provenance": "INJECTED_TEST_RESPONSE",
                "independent_timestamp_verified": False,
                "exchange_response_cryptographically_signed": False,
                "external_evidence_replication_verified": False,
                "trading_authorized": False,
            }
        sources[sym] = {
            "feature_source_sha256": features[sym],
            "frames": frames,
        }
    return packet, sources


class WitnessContractTests(unittest.TestCase):
    def test_all_24_source_digests_required_and_only_unsigned_request_generated(self):
        packet, sources = sample()
        manifest = assemble_witness_request(packet, sources)
        self.assertEqual(manifest["source_receipt_count"], 24)
        self.assertEqual(manifest["source_receipts"][0]["symbol"], "BTCUSDT")
        self.assertEqual(manifest["source_receipts"][-1]["symbol"], "BNBUSDT")
        self.assertEqual(manifest["source_receipts"][-1]["frame"], "4h")
        self.assertEqual(manifest["precommit_batch_sha256"], packet["batch_sha256"])
        self.assertEqual(manifest["event_type"], "WATCH_CYCLE_COMPLETE")
        self.assertFalse(manifest["witness_service_contacted"])
        self.assertFalse(manifest["rfc3161_timestamp_token_verified"])
        self.assertFalse(manifest["independently_timestamped"])
        self.assertFalse(manifest["external_archive_replicated"])
        status = validate_unsigned_witness_request(manifest)
        self.assertFalse(status["trusted_paper_observation"])
        self.assertEqual(status["witness_imprint_sha256"],
                         manifest["witness_imprint_hex_for_external_tsa"])
        self.assertEqual(
            assemble_witness_request(packet, sources)["witness_content_sha256"],
            manifest["witness_content_sha256"],
        )

    def test_any_missing_or_extra_market_and_frame_blocks(self):
        packet, original = sample()
        for missing in MARKETS:
            sources = deepcopy(original)
            sources.pop(missing)
            with self.subTest(market=missing), self.assertRaises(ValueError):
                assemble_witness_request(packet, sources)
        s = deepcopy(original)
        s["FAKEUSDT"] = s[MARKETS[0]]
        with self.assertRaises(ValueError):
            assemble_witness_request(packet, s)
        for bad in ("1m", "4h"):
            s = deepcopy(original)
            s[MARKETS[0]]["frames"].pop(bad)
            with self.subTest(frame=bad), self.assertRaises(ValueError):
                assemble_witness_request(packet, s)

    def test_bad_symbol_digest_time_url_or_false_attestation_blocks(self):
        packet, original = sample()
        modifications = [
            ("symbol", "ETHUSDT"),
            ("boundary_ms", START_MS+STEP_MS),
            ("raw_sha256", "a"*63),
            ("raw_bytes", 0),
            ("expected_url", "https://evil.invalid/klines"),
            ("receipt_ms_local_clock_unverified", START_MS+60001),
            ("provenance", "SIGNED_BINANCE_RECEIPT"),
            ("independent_timestamp_verified", True),
            ("exchange_response_cryptographically_signed", True),
            ("external_evidence_replication_verified", True),
            ("trading_authorized", True),
        ]
        for field, invalid in modifications:
            s = deepcopy(original)
            s["BTCUSDT"]["frames"]["1m"][field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                assemble_witness_request(packet, s)
        s = deepcopy(original)
        s["BTCUSDT"]["feature_source_sha256"] = "f"*64
        with self.assertRaises(ValueError):
            assemble_witness_request(packet, s)

    def test_no_watch_still_requires_24_sources(self):
        packet, sources = sample()
        self.assertEqual(packet["observations"][0]["candidate_directions"], [])
        self.assertEqual(assemble_witness_request(packet, sources)[
            "source_receipt_count"], 24)

    def test_gap_requires_no_source_receipts_and_is_not_no_watch(self):
        packet, _ = sample()
        gap = make_synthetic_gap(
            boundary_ms=START_MS+STEP_MS,
            recorded_ms=START_MS+STEP_MS+65000,
            missing_reasons={"ETHUSDT": "SOURCE_STALE"},
            previous_sha256=packet["batch_sha256"],
            previous_boundary_ms=START_MS
        )
        manifest = assemble_witness_request(
            gap, {}, previous_sha256=packet["batch_sha256"],
            previous_boundary_ms=START_MS
        )
        self.assertEqual(manifest["event_type"], "MISSING_DATA_CYCLE")
        self.assertEqual(manifest["source_receipt_count"], 0)
        self.assertFalse(validate_unsigned_witness_request(manifest)[
            "cryptographically_verified_external_receipt"])
        with self.assertRaises(ValueError):
            assemble_witness_request(
                gap, sample()[1], previous_sha256=packet["batch_sha256"],
                previous_boundary_ms=START_MS
            )
        with self.assertRaises(ValueError):
            assemble_witness_request(gap, {})

    def test_tampered_manifest_and_false_verification_claims_rejected(self):
        packet, sources = sample()
        manifest = assemble_witness_request(packet, sources)
        for key, value in (
            ("witness_content_sha256", "0"*64),
            ("witness_imprint_hex_for_external_tsa", "f"*64),
            ("witness_content_bytes", 1),
            ("rfc3161_timestamp_token_verified", True),
            ("independent_timestamp_trust_status", "CERTIFIED"),
            ("external_archive_replicated", True),
            ("trading_authorized", True),
            ("witness_service_contacted", True),
        ):
            changed = deepcopy(manifest)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_unsigned_witness_request(changed)


if __name__ == "__main__":
    unittest.main()
