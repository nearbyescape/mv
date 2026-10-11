"""Synthetic-only forward precommit protocol, not live signals or verified receipts."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import unittest

from app.research.t7sonic_experts import RESEARCH_ONLY_STATUS
from app.research.t7sonic_forward_protocol import (
    END_MS, START_MS, STEP_MS, FIRST_PREVIOUS_SHA,
    frozen_forward_protocol, make_synthetic_precommit,
    verify_synthetic_chain,
)
from app.research.t7sonic_validation_plan import MARKETS


def inputs(when, active=True):
    hashes = {market: sha256(market.encode()).hexdigest() for market in MARKETS}
    reports = []
    for symbol in MARKETS:
        watches = []
        if symbol == "BTCUSDT" and active:
            watches.append({
                "status": RESEARCH_ONLY_STATUS,
                "symbol": symbol,
                "as_of_ms": when,
                "source_sha256": hashes[symbol],
                "expert": "failed_breakout_reversal",
                "direction": "SHORT",
                "publishable_signal": False,
                "executable_order": False,
                "entry_price": None,
                "stop_loss": None,
                "take_profit": None,
            })
        reports.append({"symbol": symbol, "watch_hypotheses": watches})
    return reports, hashes


def packet(when=START_MS, *, active=True, previous_sha256=FIRST_PREVIOUS_SHA,
           previous_boundary_ms=None, receipt_delay=1000):
    reports, hashes = inputs(when, active)
    return make_synthetic_precommit(
        boundary_ms=when,
        receipt_ms=when + receipt_delay,
        market_reports=reports,
        feature_source_hashes=hashes,
        previous_sha256=previous_sha256,
        previous_boundary_ms=previous_boundary_ms,
    )


class ForwardPrecommitTests(unittest.TestCase):
    def test_protocol_is_frozen_and_not_live(self):
        plan = frozen_forward_protocol()
        self.assertEqual(plan["utc_calendar_days"], 75)
        self.assertEqual(plan["candidate_expert"], "failed_breakout_reversal")
        self.assertEqual(plan["start_utc"], "2026-10-15T00:00:00+00:00")
        self.assertEqual(plan["end_exclusive_utc"], "2026-12-29T00:00:00+00:00")
        self.assertEqual(plan["markets"], list(MARKETS))
        self.assertFalse(plan["trusted_timestamp_receipts_implemented"])
        self.assertFalse(plan["real_time_binance_collector_implemented"])
        self.assertFalse(plan["live_signal_publication_authorized"])
        self.assertFalse(plan["production_engine_may_restart"])
        digest = plan.pop("protocol_sha256")
        self.assertEqual(digest, sha256(json.dumps(
            plan, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest())

    def test_six_markets_always_recorded_including_no_watch(self):
        record = packet()
        self.assertEqual(record["market_count"], 6)
        self.assertEqual([x["symbol"] for x in record["observations"]], list(MARKETS))
        self.assertEqual(record["observations"][0]["candidate_directions"], ["SHORT"])
        self.assertTrue(record["observations"][0]["candidate_active"])
        self.assertTrue(all(
            not x["candidate_active"] for x in record["observations"][1:]
        ))
        self.assertFalse(record["trusted_timestamp_receipt"])
        self.assertFalse(record["future_labels_computed"])
        self.assertFalse(record["signals_authorized"])
        self.assertFalse(record["orders_authorized"])

    def test_empty_candidate_packet_does_not_get_censored(self):
        record = packet(active=False)
        self.assertTrue(all(
            x["candidate_directions"] == [] for x in record["observations"]
        ))
        self.assertEqual(verify_synthetic_chain([record])["packets"], 1)

    def test_reject_unlocked_date_and_untrusted_receipt_claims(self):
        for when in (START_MS-STEP_MS, END_MS, START_MS+1, 0, "2026-10-15"):
            with self.subTest(when=when), self.assertRaises(ValueError):
                packet(when)
        for delay in (-1, 60_001, "1000", 1.0):
            with self.subTest(delay=delay), self.assertRaises(ValueError):
                packet(receipt_delay=delay)
        self.assertEqual(packet(receipt_delay=60_000)["boundary_ms"], START_MS)

    def test_missing_duplicate_market_or_actionable_hypothesis_rejected(self):
        reports, hashes = inputs(START_MS)
        for modified in (reports[1:], reports + [reports[0]]):
            with self.assertRaises(ValueError):
                make_synthetic_precommit(
                    boundary_ms=START_MS, receipt_ms=START_MS,
                    market_reports=modified, feature_source_hashes=hashes,
                )
        malicious = deepcopy(reports)
        malicious[0]["watch_hypotheses"][0]["publishable_signal"] = True
        with self.assertRaises(ValueError):
            make_synthetic_precommit(
                boundary_ms=START_MS, receipt_ms=START_MS,
                market_reports=malicious, feature_source_hashes=hashes,
            )
        for key, value in (("entry_price", "42"),
                           ("as_of_ms", START_MS+STEP_MS),
                           ("source_sha256", "0"*64),
                           ("expert", "v6hbr")):
            malicious = deepcopy(reports)
            malicious[0]["watch_hypotheses"][0][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                make_synthetic_precommit(
                    boundary_ms=START_MS, receipt_ms=START_MS,
                    market_reports=malicious, feature_source_hashes=hashes,
                )

    def test_sha_link_and_noncontiguous_packet_fail_closed(self):
        first = packet()
        second = packet(
            START_MS + STEP_MS,
            previous_sha256=first["batch_sha256"],
            previous_boundary_ms=START_MS,
        )
        self.assertEqual(verify_synthetic_chain([first, second])["packets"], 2)
        broken = deepcopy(second)
        broken["observations"][0]["candidate_directions"] = ["LONG"]
        with self.assertRaisesRegex(ValueError, "modified"):
            verify_synthetic_chain([first, broken])
        with self.assertRaises(ValueError):
            verify_synthetic_chain([second])
        with self.assertRaises(ValueError):
            packet(START_MS + 2*STEP_MS,
                   previous_sha256=first["batch_sha256"],
                   previous_boundary_ms=START_MS)
        with self.assertRaises(ValueError):
            packet(START_MS+STEP_MS)

    def test_source_digests_and_prior_chain_digest_cannot_be_missing(self):
        reports, hashes = inputs(START_MS)
        hashes.pop("BNBUSDT")
        with self.assertRaises(ValueError):
            make_synthetic_precommit(
                boundary_ms=START_MS, receipt_ms=START_MS,
                market_reports=reports, feature_source_hashes=hashes,
            )
        with self.assertRaises(ValueError):
            packet(previous_sha256="a"*64)


if __name__ == "__main__":
    unittest.main()
