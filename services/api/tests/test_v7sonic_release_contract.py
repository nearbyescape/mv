"""No-network production handoff contract tests for V7Sonic.

These explicitly do NOT test publication, trading execution, or profitability.
"""
from __future__ import annotations

import json
from copy import deepcopy
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from pathlib import Path

from app import v7sonic_release as handoff
from services.t7sonic.early_live_smoke import _save_original_responses
from services.t7sonic.replay_original_capture import _read_private_file
from test_t7sonic_early_live_smoke import data
from test_t7sonic_forward_release_bridge import BOUNDARY
from test_t7sonic_release_candidate import breakout, quote, indicative_plan
from app.research.t7sonic_release_preview import build_offline_preview
from app.research.t7sonic_validation_plan import MARKETS


class V7ReleaseContractTests(TestCase):
    def receipt(self):
        candles, books, info, times = data()
        with TemporaryDirectory(prefix="v7-release-contract-") as temp:
            path, _digest = _save_original_responses(
                Path(temp), BOUNDARY,
                candles, books, info, times, BOUNDARY+1_500,
            )
            return _read_private_file(path)

    def test_realistic_original_31_source_rehearsal_never_publishes(self):
        original = self.receipt()
        with patch.object(handoff, "_ist_open", return_value=True):
            result = handoff.rehearse_original_capture(
                original, observed_now_ms=BOUNDARY+2_000,
                active_symbols=(), previously_seen_candidate_ids=(),
            )
        self.assertEqual(result["original_http_responses_verified"],31)
        self.assertEqual(result["markets_evaluated"],len(MARKETS))
        self.assertEqual(result["strategy_id"],handoff.STRATEGY_ID)
        self.assertFalse(result["client_publication_authorized"])
        self.assertFalse(result["telegram_enqueued"])
        self.assertFalse(result["orders_authorized"])
        self.assertFalse(result["persisted_outbox_implemented"])
        self.assertFalse(result["live_worker_integrated"])
        self.assertEqual(len(result["new_rehearsals"]),result["candidate_count"])

    def test_synthetic_positive_candidate_formats_two_targets_only(self):
        candidate=indicative_plan(breakout(),quote())
        text=handoff.format_private_rehearsal(candidate)
        self.assertIn("DO NOT TRADE",text)
        self.assertIn("TP1 (50%",text)
        self.assertIn("TP2 (50%",text)
        self.assertNotIn("TP3",text)
        self.assertIn("Five-minute decision",text)
        self.assertIn("Not authorized for clients",text)

    def test_batch_added_delivery_status_does_not_change_candidate_hash(self):
        markets=[]; quotes=[]
        for symbol in MARKETS:
            snap=breakout()
            snap["symbol"]=symbol
            markets.append(snap)
            quotes.append(quote(symbol=symbol))
        result=build_offline_preview(markets,quotes)
        self.assertEqual(result["candidate_count"],6)
        for item in result["indicative_candidates"]:
            self.assertIn("DO NOT TRADE",handoff.format_private_rehearsal(item))

    def test_tampered_or_fake_candidate_rejected_before_format(self):
        original=indicative_plan(breakout(),quote())
        cases=[]
        v=deepcopy(original)
        v["entry"]="999"
        cases.append(v)
        v=deepcopy(original)
        v["publishable_signal"]=True
        cases.append(v)
        v=deepcopy(original)
        v["direction"]="SHORT"
        cases.append(v)
        v=deepcopy(original)
        v["take_profit_1"]=v["stop_loss"]
        cases.append(v)
        for candidate in cases:
            with self.assertRaises(ValueError):
                handoff.format_private_rehearsal(candidate)

    def test_exact_stale_and_outside_session_fail_closed(self):
        receipt=self.receipt()
        with self.assertRaisesRegex(ValueError,"Outside frozen"):
            handoff.rehearse_original_capture(
                receipt,observed_now_ms=BOUNDARY+2000,
                active_symbols=(),previously_seen_candidate_ids=()
            )
        with patch.object(handoff,"_ist_open",return_value=True):
            with self.assertRaisesRegex(ValueError,"Stale"):
                handoff.rehearse_original_capture(
                    receipt,observed_now_ms=BOUNDARY+30_001,
                    active_symbols=(),previously_seen_candidate_ids=()
                )
            receipt["kline_bodies"]["BTCUSDT"]["15m"]["original_body_sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"source body mismatch"):
                handoff.rehearse_original_capture(
                    receipt,observed_now_ms=BOUNDARY+2000,
                    active_symbols=(),previously_seen_candidate_ids=()
                )

    def test_invalid_active_and_previous_candidate_snapshots_rejected(self):
        receipt=self.receipt()
        with self.assertRaisesRegex(ValueError,"active symbols"):
            handoff.rehearse_original_capture(
                receipt,observed_now_ms=BOUNDARY+2000,
                active_symbols=("BTCUSDT","BTCUSDT"),
                previously_seen_candidate_ids=()
            )
        with self.assertRaisesRegex(ValueError,"candidate-ID"):
            handoff.rehearse_original_capture(
                receipt,observed_now_ms=BOUNDARY+2000,
                active_symbols=(),
                previously_seen_candidate_ids=("not-a-digest",)
            )

    def test_rehearsal_has_no_network_calls(self):
        receipt=self.receipt()
        from services.t7sonic import early_live_smoke as smoke
        with patch.object(smoke,"_get") as network:
            with patch.object(handoff,"_ist_open",return_value=True):
                handoff.rehearse_original_capture(
                    receipt,observed_now_ms=BOUNDARY+2_000,
                    active_symbols=(),previously_seen_candidate_ids=(),
                )
            network.assert_not_called()
