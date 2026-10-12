"""Offline one-shot public observer integration; no live Binance HTTP."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

from app.research.t7sonic_forward_protocol import START_MS, STEP_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic.forward_https import TransportEnvelope, expected_url
from services.t7sonic.forward_public_http import (
    PublicHttpResponse, approved_public_url,
)
from services.t7sonic.forward_one_shot import (
    checked_live_cycle, optional_public_paper_capture,
)
from test_t7sonic_forward_release_bridge import source_bundle, BOUNDARY
from test_t7sonic_forward_live_quote import contract_data, book_data


def fixtures():
    raw, _ = source_bundle()
    sources = {}
    books = {}
    for symbol in MARKETS:
        sources[symbol] = {}
        for frame in ("1m","15m","1h","4h"):
            plan, data, status, receipt = raw[symbol][frame]
            url = expected_url(plan)
            sources[symbol][frame] = TransportEnvelope(
                status=status, final_url=url,
                content_type="application/json", raw_body=data,
                received_ms=receipt, provenance="INJECTED_TEST_RESPONSE",
            )
        url,_ = approved_public_url("bookTicker",symbol)
        books[symbol] = PublicHttpResponse(
            request_url=url,final_url=url,status=200,
            content_type="application/json",
            body=book_data(symbol=symbol,event_ms=BOUNDARY+500),
            received_ms_local_claim=BOUNDARY+1_000,
        )
    url,_ = approved_public_url("exchangeInfo")
    info = PublicHttpResponse(
        request_url=url,final_url=url,status=200,
        content_type="application/json",body=contract_data(),
        received_ms_local_claim=BOUNDARY+1_000,
    )
    return sources, books, info


class OneShotPublicCycleTests(TestCase):
    def test_complete_31_public_envelopes_generate_only_paper_preview(self):
        sources, books, info = fixtures()
        report = checked_live_cycle(BOUNDARY, sources, books, info)
        self.assertEqual(report["markets_evaluated"],6)
        self.assertEqual(report["source_http_responses"],31)
        self.assertEqual(report["raw_source_response_count"],24)
        self.assertEqual(report["top_of_book_responses_validated"],6)
        self.assertTrue(report["full_six_market_source_geometry_validated"])
        self.assertFalse(report["external_independent_receipt_verified"])
        self.assertFalse(report["client_publication_authorized"])
        self.assertFalse(report["real_money_orders_authorized"])
        self.assertFalse(report["telegram_enqueued"])
        self.assertFalse(report["raw_responses_replicated_off_vps"])
        self.assertEqual(report, checked_live_cycle(BOUNDARY, *fixtures()))

    def test_mismatched_missing_market_or_book_fails_entire_decision(self):
        s,b,i=fixtures()
        s.pop("BTCUSDT")
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)
        s,b,i=fixtures()
        b.pop("DOGEUSDT")
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)
        s,b,i=fixtures()
        s["ETHUSDT"].pop("4h")
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)

    def test_overdue_quote_source_metadata_and_redirect_rejected(self):
        s,b,i=fixtures()
        b["BTCUSDT"]=replace(b["BTCUSDT"],
                             received_ms_local_claim=BOUNDARY+30_001)
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)
        s,b,i=fixtures()
        s["SOLUSDT"]["1m"]=replace(
            s["SOLUSDT"]["1m"],received_ms=BOUNDARY+30_001
        )
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)
        s,b,i=fixtures()
        i=replace(i,final_url="https://malicious.invalid")
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)
        s,b,i=fixtures()
        i=replace(i,received_ms_local_claim=BOUNDARY+30_001)
        with self.assertRaises(ValueError):
            checked_live_cycle(BOUNDARY,s,b,i)

    def test_default_network_denial_before_any_http(self):
        with patch("services.t7sonic.forward_one_shot.ThreadPoolExecutor") as pool:
            with self.assertRaises(PermissionError):
                optional_public_paper_capture(BOUNDARY)
            pool.assert_not_called()

    def test_early_and_old_boundary_refused_without_http(self):
        with patch("services.t7sonic.forward_one_shot.ThreadPoolExecutor") as pool:
            with patch("services.t7sonic.forward_one_shot.time.time_ns",
                       return_value=(BOUNDARY-1)*1_000_000):
                with self.assertRaises(ValueError):
                    optional_public_paper_capture(
                        BOUNDARY,network_approved=True
                    )
            with patch("services.t7sonic.forward_one_shot.time.time_ns",
                       return_value=(BOUNDARY+5001)*1_000_000):
                with self.assertRaises(ValueError):
                    optional_public_paper_capture(
                        BOUNDARY,network_approved=True
                    )
            with self.assertRaises(ValueError):
                optional_public_paper_capture(
                    START_MS-STEP_MS,network_approved=True)
            pool.assert_not_called()
