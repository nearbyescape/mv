"""Synthetic six-market coverage and outage bookkeeping, no live feed."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import unittest

from app.research.t7sonic_experts import RESEARCH_ONLY_STATUS
from app.research.t7sonic_forward_protocol import (
    START_MS, STEP_MS, make_synthetic_precommit, _digest,
)
from app.research.t7sonic_forward_coverage import (
    make_synthetic_gap, verify_synthetic_coverage,
    make_external_witness_request, GAP_STATUS,
)
from app.research.t7sonic_validation_plan import MARKETS


def sample_reports(boundary):
    digests = {sym: sha256(sym.encode()).hexdigest() for sym in MARKETS}
    reports = [{"symbol": sym, "watch_hypotheses": []} for sym in MARKETS]
    reports[0]["watch_hypotheses"].append({
        "status": RESEARCH_ONLY_STATUS, "symbol": MARKETS[0],
        "as_of_ms": boundary, "source_sha256": digests[MARKETS[0]],
        "expert": "failed_breakout_reversal", "direction": "SHORT",
        "publishable_signal": False, "executable_order": False,
        "entry_price": None, "stop_loss": None, "take_profit": None,
    })
    return reports, digests


def watch_at(boundary, prev_sha="0"*64, prior=None):
    reports, digests = sample_reports(boundary)
    return make_synthetic_precommit(
        boundary_ms=boundary, receipt_ms=boundary+1000,
        market_reports=reports, feature_source_hashes=digests,
        previous_sha256=prev_sha, previous_boundary_ms=prior,
    )


def gap_at(boundary, prev_sha="0"*64, prior=None, problems=None, delay=62000):
    return make_synthetic_gap(
        boundary_ms=boundary, recorded_ms=boundary+delay,
        missing_reasons=({"ETHUSDT": "SOURCE_STALE"} if problems is None else problems),
        previous_sha256=prev_sha, previous_boundary_ms=prior,
    )


class ForwardCoverageTests(unittest.TestCase):
    def test_watch_gap_watch_preserves_complete_five_minute_schedule(self):
        one = watch_at(START_MS)
        gap = gap_at(START_MS+STEP_MS, one["batch_sha256"], START_MS)
        three = watch_at(START_MS+2*STEP_MS, gap["batch_sha256"], START_MS+STEP_MS)
        proof = verify_synthetic_coverage([one, gap, three])
        self.assertEqual(proof["complete_six_market_watch_cycles"], 2)
        self.assertEqual(proof["missing_source_or_deadline_cycles"], 1)
        self.assertEqual(proof["coverage_fraction"], "0.666667")
        self.assertFalse(proof["independently_timestamped"])
        self.assertFalse(proof["signals_authorized"])
        self.assertFalse(proof["orders_authorized"])
        self.assertEqual([x["symbol"] for x in gap["observations"]], list(MARKETS))
        self.assertEqual(gap["observations"][0]["state"],
                         "NOT_EVALUATED_DUE_TO_PARTIAL_SOURCE_FAILURE")
        self.assertEqual(gap["observations"][1]["state"], "DATA_MISSING")
        self.assertIsNone(gap["observations"][0]["candidate_directions"])
        self.assertIsNone(gap["observations"][1]["candidate_directions"])

    def test_source_outage_is_not_a_no_watch_event(self):
        first = gap_at(START_MS, problems={"BTCUSDT": "SOURCE_UNAVAILABLE"})
        self.assertEqual(first["status"], GAP_STATUS)
        proof = verify_synthetic_coverage([first])
        self.assertEqual(proof["missing_source_or_deadline_cycles"], 1)
        self.assertEqual(proof["complete_six_market_watch_cycles"], 0)
        bad = deepcopy(first)
        bad["observations"][0]["candidate_directions"] = []
        bad["batch_sha256"] = _digest({
            key: value for key, value in bad.items() if key != "batch_sha256"
        })
        with self.assertRaisesRegex(ValueError, "Gap cannot"):
            verify_synthetic_coverage([bad])

    def test_gap_bad_reason_and_missing_market_are_rejected(self):
        for reasons in (
            {}, {"FAKEUSDT": "SOURCE_STALE"},
            {"BTCUSDT": "NO_WATCH"}, {"BTCUSDT": None},
        ):
            with self.subTest(reasons=reasons), self.assertRaises(ValueError):
                gap_at(START_MS, problems=reasons)
        with self.assertRaises(ValueError):
            make_synthetic_gap(
                boundary_ms=START_MS, recorded_ms=START_MS,
                missing_reasons={"BTCUSDT": "SOURCE_STALE"},
                previous_sha256="a"*64,
            )
        with self.assertRaises(ValueError):
            gap_at(START_MS, delay=-1)
        with self.assertRaises(ValueError):
            gap_at(START_MS, delay=STEP_MS*2+1)

    def test_omitted_or_reordered_boundary_rejected(self):
        first = watch_at(START_MS)
        gap = gap_at(START_MS+STEP_MS, first["batch_sha256"], START_MS)
        watch = watch_at(START_MS+2*STEP_MS, gap["batch_sha256"], START_MS+STEP_MS)
        with self.assertRaises(ValueError):
            verify_synthetic_coverage([first, watch])
        with self.assertRaises(ValueError):
            verify_synthetic_coverage([gap])
        with self.assertRaises(ValueError):
            gap_at(START_MS+2*STEP_MS, first["batch_sha256"], START_MS)

    def test_tampering_and_fake_timestamp_claims_rejected(self):
        first = watch_at(START_MS)
        gap = gap_at(START_MS+STEP_MS, first["batch_sha256"], START_MS)
        tampered = deepcopy(gap)
        tampered["reasons_by_symbol"]["ETHUSDT"] = "ENGINE_FAILURE"
        with self.assertRaisesRegex(ValueError, "Tampered"):
            verify_synthetic_coverage([first, tampered])
        forged_claim = deepcopy(first)
        forged_claim["receipt_ms_untrusted_claim"] = START_MS + 90000
        forged_claim["batch_sha256"] = _digest({
            key: value for key, value in forged_claim.items()
            if key != "batch_sha256"
        })
        with self.assertRaises(ValueError):
            verify_synthetic_coverage([forged_claim])

    def test_witness_request_does_not_claim_timestamp_proof(self):
        record = watch_at(START_MS)
        witness = make_external_witness_request(record)
        self.assertEqual(witness["record_digest_sha256"], record["batch_sha256"])
        self.assertEqual(witness["status"],
                         "UNSUBMITTED_EXTERNAL_TIMESTAMP_REQUEST")
        self.assertFalse(witness["external_witness_service_configured"])
        self.assertFalse(witness["trusted_timestamp_receipt"])
        self.assertFalse(witness["receipt_signature_verified"])


if __name__ == "__main__":
    unittest.main()
