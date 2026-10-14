"""No-network negative tests for independent four-cycle local evidence audit."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import v7sonic_pilot_recertify as auditor

GIT_SHA = "a"*40
START = 1791951600000


def body_sha(value: bytes) -> str:
    return sha256(value).hexdigest()


class FourCycleLocalEvidenceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="v7-four-recertify-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bounds = tuple(START + 300000*i for i in range(4))
        self.rows = {}
        for boundary in self.bounds:
            claim = {
                "decision_boundary_ms": boundary,
                "status": "PRIVATE_PAPER_BOUNDARY_CLAIMED",
                "client_publication_authorized": False,
                "telegram_enqueued": False, "orders_authorized": False,
            }
            self.write(f"v7sonic-private-claim-{boundary}.json", claim)
            raw = self.write(f"v7sonic-original-http-{boundary}.json", {
                "decision_boundary_ms": boundary, "bad": False,
            })
            self.rows[boundary] = {
                "boundary_ms": boundary,
                "attempt_count":1,
                "source_attempts":[{
                    "attempt":1,
                    "original_http_file": str(self.root / f"v7sonic-original-http-{boundary}.json"),
                    "original_http_sha256": body_sha(raw),
                }],
                "last_original_http_sha256": body_sha(raw),
                "paper_batch_sha256": "b"*64,
            }
            self.write(f"v7sonic-private-paper-cycle-{boundary}.json",
                       self.rows[boundary])

    def write(self, filename, value):
        raw = (json.dumps(value, sort_keys=True) + "\n").encode()
        (self.root/filename).write_bytes(raw)
        return raw

    def forensic(self, raw):
        return {
            "original_http_responses_hash_checked":31,
            "decision_boundary_ms":raw["decision_boundary_ms"],
            "exact_reconciliation_passed":not raw.get("bad",False),
        }

    def run_audit(self):
        def successful(*_a, **_kw):
            return {"candidates":[], "noncandidates":[
                {"symbol":s,"reason":"NO_SETUP"}
                for s in ("BTCUSDT","ETHUSDT","SOLUSDT",
                          "XRPUSDT","DOGEUSDT","BNBUSDT")
            ]}
        with patch.object(auditor,"replay_original",side_effect=self.forensic):
            with patch.object(auditor,"audit_one_stored_cycle",
                              side_effect=successful) as ledger:
                result = auditor.recertify_pilot(
                    self.root, expected_sha=GIT_SHA,
                    expected_boundaries=self.bounds,
                )
        self.assertEqual(ledger.call_count, 4)
        return result

    def test_four_complete_sources_and_24_decisions_do_not_authorize_clients(self):
        result = self.run_audit()
        self.assertEqual(result["completed_cycles"],4)
        self.assertEqual(result["market_decisions_audited"],24)
        self.assertEqual(result["accepted_original_http_bodies_verified"],124)
        self.assertEqual(result["indicative_candidate_count"],0)
        self.assertEqual(result["telegram_messages_sent"],0)
        self.assertFalse(result["production_cutover_certified"])
        self.assertFalse(result["model_profitability_or_accuracy_certified"])
        self.assertFalse(result["off_server_sha_attestation_verified"])

    def test_exact_one_rejected_then_complete_second_source_chain(self):
        b=self.bounds[2]
        original_name=f"v7sonic-original-http-{b}.json"
        first=self.write(original_name,{
            "decision_boundary_ms":b,"bad":True,
        })
        follow=self.write(f"v7sonic-original-http-{b}-attempt-2.json",{
            "decision_boundary_ms":b,"bad":False,
        })
        self.rows[b]["attempt_count"]=2
        self.rows[b]["source_attempts"]=[
            {"attempt":1,"original_http_file":str(self.root/original_name),
             "original_http_sha256":body_sha(first)},
            {"attempt":2,"original_http_file":str(
                self.root/f"v7sonic-original-http-{b}-attempt-2.json"),
             "original_http_sha256":body_sha(follow)}
        ]
        self.rows[b]["last_original_http_sha256"]=body_sha(follow)
        self.write(f"v7sonic-private-paper-cycle-{b}.json",self.rows[b])
        self.write(f"v7sonic-private-rejected-{b}-1.json",{
            "status":"PRIVATE_PAPER_ANALYSIS_REJECTED",
            "attempt":1, "original_http_sha256":body_sha(first),
            "retry_eligible":True,
            "retry_classification":"EXACT_CROSS_RESOLUTION_RECONCILIATION",
            "client_publication_authorized":False,
            "telegram_enqueued":False,"orders_authorized":False,
        })
        out=self.run_audit()
        self.assertEqual(out["rejected_source_attempts_hash_verified"],1)
        self.assertEqual(out["cycles"][2]["attempts"],2)

    def test_source_tamper_fails_before_any_release(self):
        name=f"v7sonic-original-http-{self.bounds[0]}.json"
        (self.root/name).write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError,"Tampered original"):
            self.run_audit()

    def test_unresolved_gap_never_becomes_a_no_candidate(self):
        self.write(f"v7sonic-private-gap-{self.bounds[1]}.json",{
            "status":"V7_PRIVATE_CAPTURE_FAILED_NO_SIGNAL_OR_SEND",
        })
        with self.assertRaisesRegex(ValueError,"GAPS"):
            self.run_audit()

    def test_missing_claim_and_extraneous_source_rejected(self):
        (self.root/f"v7sonic-private-claim-{self.bounds[0]}.json").unlink()
        with self.assertRaisesRegex(ValueError,"claims"):
            self.run_audit()

    def test_unapproved_rejection_and_false_timestamp_proof_rejected(self):
        self.write(f"v7sonic-private-rejected-{self.bounds[0]}-1.json",{
            "retry_classification":"NOT_RETRYABLE",
        })
        with self.assertRaisesRegex(ValueError,"Orphan/extra"):
            self.run_audit()

    def test_exact_consecutive_four_and_full_sha_required(self):
        with self.assertRaisesRegex(ValueError,"four consecutive"):
            auditor.recertify_pilot(
                self.root, expected_sha=GIT_SHA,
                expected_boundaries=(START,START+600000,START+900000,START+1200000),
            )
        with self.assertRaisesRegex(ValueError,"Exact source SHA"):
            auditor.recertify_pilot(
                self.root, expected_sha="bad",
                expected_boundaries=self.bounds,
            )


if __name__=="__main__":
    import unittest
    unittest.main()
