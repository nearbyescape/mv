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

    def _mock_complete_network_cycle(self, *, before_ms, after_ms, event_ms,
                                     candidate_expires_ms=None):
        # The worker thread pool is real; each HTTP source is a mock stub.
        # This verifies the outer runtime time gate, not source authenticity.
        proof = {
            "quote_proofs": {
                symbol: {"exchange_event_ms_unattested": event_ms}
                for symbol in MARKETS
            },
            "indicative_candidates": [
                {"expires_at_ms": (
                    BOUNDARY+30_000 if candidate_expires_ms is None
                    else candidate_expires_ms)}
            ],
            "client_publication_authorized": False,
            "telegram_enqueued": False,
        }
        with patch("services.t7sonic.forward_one_shot.optional_https_get",
                   return_value=object()) as klines:
            with patch("services.t7sonic.forward_one_shot.optional_public_http_get",
                       return_value=object()) as public:
                with patch("services.t7sonic.forward_one_shot.checked_live_cycle",
                           return_value=proof) as verify:
                    with patch("services.t7sonic.forward_one_shot.time.time_ns",
                               side_effect=[
                                   (BOUNDARY+1_000)*1_000_000,
                                   before_ms*1_000_000,
                                   after_ms*1_000_000,
                               ]):
                        result = optional_public_paper_capture(
                            BOUNDARY, network_approved=True
                        )
        self.assertEqual(klines.call_count, 24)
        self.assertEqual(public.call_count, 7)
        verify.assert_called_once()
        return result

    def test_books_are_collected_only_after_all_historical_sources(self):
        # An early top-of-book snapshot can expire during the long kline
        # intake. The live one-shot path must fetch books LAST.
        from threading import Lock
        mutex = Lock()
        state = {"klines_done": 0, "info_done": False, "books": []}

        def get_kline(*args, **kwargs):
            with mutex:
                state["klines_done"] += 1
            return object()

        def get_public(kind, **kwargs):
            with mutex:
                if kind == "exchangeInfo":
                    state["info_done"] = True
                elif kind == "bookTicker":
                    state["books"].append((
                        state["klines_done"], state["info_done"]
                    ))
                else:
                    raise AssertionError("Unapproved public endpoint")
            return object()

        mocked_report = {
            "quote_proofs": {
                symbol: {
                    "exchange_event_ms_unattested": BOUNDARY+2_500,
                } for symbol in MARKETS
            },
            "indicative_candidates": [],
            "client_publication_authorized": False,
            "telegram_enqueued": False,
        }
        with patch("services.t7sonic.forward_one_shot.optional_https_get",
                   side_effect=get_kline) as hist:
            with patch("services.t7sonic.forward_one_shot.optional_public_http_get",
                       side_effect=get_public) as public:
                with patch("services.t7sonic.forward_one_shot.checked_live_cycle",
                           return_value=mocked_report) as inspection:
                    with patch("services.t7sonic.forward_one_shot.time.time_ns",
                               side_effect=[
                                   (BOUNDARY+1_000)*1_000_000,
                                   (BOUNDARY+2_800)*1_000_000,
                                   (BOUNDARY+3_000)*1_000_000,
                               ]):
                        report = optional_public_paper_capture(
                            BOUNDARY, network_approved=True,
                        )
        self.assertEqual(hist.call_count, 24)
        self.assertEqual(public.call_count, 7)
        self.assertEqual(len(state["books"]), 6)
        self.assertEqual(state["books"], [(24, True)]*6)
        inspection.assert_called_once()
        self.assertTrue(report[
            "quotes_fresh_at_return_local_clock_claim"
        ])
        self.assertFalse(report["telegram_enqueued"])

    def test_candidate_after_parse_remains_fresh_and_before_deadline(self):
        result=self._mock_complete_network_cycle(
            before_ms=BOUNDARY+2000,
            after_ms=BOUNDARY+3000,
            event_ms=BOUNDARY+500,
        )
        self.assertTrue(result[
            "complete_cycle_returned_before_deadline_local_clock_claim"
        ])
        self.assertTrue(result[
            "quotes_fresh_at_return_local_clock_claim"
        ])
        self.assertFalse(result["telegram_enqueued"])
        self.assertFalse(result["client_publication_authorized"])

    def test_long_parse_cannot_return_already_expired_candidate(self):
        with self.assertRaisesRegex(ValueError,"computation exceeded deadline"):
            self._mock_complete_network_cycle(
                before_ms=BOUNDARY+2000,
                after_ms=BOUNDARY+30_001,
                event_ms=BOUNDARY+1000,
            )

    def test_long_parse_makes_book_quote_stale_even_when_before_deadline(self):
        with self.assertRaisesRegex(ValueError,"Quote aged beyond five seconds"):
            self._mock_complete_network_cycle(
                before_ms=BOUNDARY+2000,
                after_ms=BOUNDARY+7000,
                event_ms=BOUNDARY+500,
            )

    def test_expired_candidate_is_vetoed_even_when_book_still_fresh(self):
        with self.assertRaisesRegex(ValueError,"already expired"):
            self._mock_complete_network_cycle(
                before_ms=BOUNDARY+2000,
                after_ms=BOUNDARY+3000,
                event_ms=BOUNDARY+1000,
                candidate_expires_ms=BOUNDARY+3000,
            )

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
