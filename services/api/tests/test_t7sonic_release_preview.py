"""Complete six-market dry-run release pipeline; no network or Telegram."""
from __future__ import annotations

from copy import deepcopy
import unittest

from app.research.t7sonic_validation_plan import MARKETS
from app.research.t7sonic_release_preview import (
    build_offline_preview, format_explicit_test_message, run_offline_release_input,
)
from test_t7sonic_release_candidate import breakout, quote


def group():
    samples, quotes = [], []
    for symbol in MARKETS:
        source = breakout()
        source["symbol"] = symbol
        samples.append(source)
        quotes.append(quote(symbol=symbol))
    return samples, quotes


class ReleaseBatchTests(unittest.TestCase):
    def test_complete_exactly_six_market_cycle_prepares_deterministic_paper_candidates(self):
        samples, quotes = group()
        out = build_offline_preview(samples, quotes)
        self.assertEqual(out["markets_expected"], 6)
        self.assertEqual(out["markets_evaluated"], 6)
        self.assertEqual(out["candidate_count"], 6)
        self.assertEqual([p["symbol"] for p in out["indicative_candidates"]],
                         list(MARKETS))
        self.assertFalse(out["telegram_enqueued"])
        self.assertFalse(out["client_publication_authorized"])
        self.assertFalse(out["real_money_orders_authorized"])
        self.assertFalse(out["market_data_source_authenticated"])
        self.assertEqual(out, build_offline_preview(*group()))
        self.assertEqual(len(out["batch_sha256"]), 64)
        message = format_explicit_test_message(out["indicative_candidates"][0])
        self.assertIn("DO NOT TRADE", message)
        self.assertIn("TP1 / TP2", message)
        self.assertIn("Not authorized for client publication", message)

    def test_missing_reordered_duplicate_or_extra_market_fails_closed(self):
        samples, quotes = group()
        cases = [
            (samples[:-1], quotes),
            (samples+[deepcopy(samples[0])], quotes),
            (list(reversed(samples)), quotes),
            (samples, quotes[:-1]),
            (samples, list(reversed(quotes))),
        ]
        for i, (s, q) in enumerate(cases):
            with self.subTest(i=i), self.assertRaises(ValueError):
                build_offline_preview(s, q)
        samples[4]["symbol"] = samples[0]["symbol"]
        with self.assertRaises(ValueError):
            build_offline_preview(samples, quotes)

    def test_as_of_mismatch_and_stale_quote_fails_closed(self):
        samples, quotes = group()
        samples[-1]["as_of_ms"] += 300_000
        with self.assertRaises(ValueError):
            build_offline_preview(samples, quotes)
        samples, quotes = group()
        quotes[3]["observed_at_ms"] -= 100_000
        with self.assertRaises(ValueError):
            build_offline_preview(samples, quotes)

    def test_existing_active_market_locked_without_blocking_peers(self):
        samples, quotes = group()
        result = build_offline_preview(
            samples, quotes, active_symbols=("ETHUSDT",)
        )
        self.assertEqual(result["candidate_count"], 5)
        self.assertEqual(result["no_candidate"][0], {
            "symbol": "ETHUSDT", "reason": "ACTIVE_POSITION_LOCK"
        })

    def test_repeat_candidate_id_not_queued_in_preview(self):
        samples, quotes = group()
        first = build_offline_preview(samples, quotes)
        ids = tuple(c["candidate_id"] for c in first["indicative_candidates"])
        repeated = build_offline_preview(
            samples, quotes, previously_seen_candidate_ids=ids
        )
        self.assertEqual(repeated["candidate_count"], 6)
        self.assertTrue(all(
            p["delivery_status"] == "SUPPRESSED_DUPLICATE_IN_OFFLINE_PREVIEW"
            for p in repeated["indicative_candidates"]
        ))
        self.assertFalse(repeated["telegram_enqueued"])

    def test_offline_file_payload_runner_contains_internal_only_messages(self):
        samples, quotes = group()
        payload = {
            "schema": 1, "snapshots": samples,
            "quotes": quotes, "active_symbols": [],
            "previously_seen_candidate_ids": [],
        }
        out = run_offline_release_input(payload)
        self.assertEqual(out["markets_evaluated"], 6)
        self.assertEqual(len(out["internal_test_messages"]), 6)
        self.assertTrue(all("DO NOT TRADE" in x for x in out["internal_test_messages"]))
        self.assertFalse(out["client_publication_authorized"])
        self.assertFalse(out["telegram_enqueued"])
        for field in ("active_symbols", "previously_seen_candidate_ids"):
            bad = deepcopy(payload)
            bad[field] = None
            with self.assertRaises(ValueError):
                run_offline_release_input(bad)
        bad = deepcopy(payload)
        bad["client_publication_authorized"] = True
        with self.assertRaises(ValueError):
            run_offline_release_input(bad)

    def test_refuse_internal_message_for_nonpaper_or_actionable_fake(self):
        samples, quotes = group()
        candidate = build_offline_preview(
            samples, quotes
        )["indicative_candidates"][0]
        for field, value in (
            ("status", "PUBLISHED"), ("publishable_signal", True),
            ("executable_order", True), ("policy", "OTHER"),
        ):
            v = deepcopy(candidate)
            v[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                format_explicit_test_message(v)


if __name__ == "__main__":
    unittest.main()
