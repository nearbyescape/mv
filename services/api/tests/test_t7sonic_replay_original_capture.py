"""Regression tests for preserving original sources on rejected live cycles.

All network functions are mocked. Never contacts Binance/Telegram.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlparse,parse_qs

from services.t7sonic import early_live_smoke as smoke
from services.t7sonic import replay_original_capture as replay
from app.research.t7sonic_forward_protocol import START_MS,STEP_MS
from app.research.t7sonic_validation_plan import MARKETS
from test_t7sonic_early_live_smoke import data


class OriginalLiveEvidenceTests(TestCase):
    def fixture(self):
        candles,books,info,times=data()
        return candles,books,info,times

    def test_transient_15m_mismatch_retries_whole_batch_and_preserves_evidence(self):
        candles,books,info,_=self.fixture()
        boundary=START_MS+STEP_MS
        old=json.loads(candles["BTCUSDT"]["15m"])
        from decimal import Decimal
        old[-1][5]=str(Decimal(old[-1][5])+Decimal("0.00000001"))
        inconsistent=json.dumps(old).encode()
        calls=[]
        btc_fifteen_calls=0

        def mocked_get(url,maximum):
            nonlocal btc_fifteen_calls
            calls.append(url)
            parsed=urlparse(url)
            args=parse_qs(parsed.query)
            if parsed.path.endswith("/klines"):
                symbol,frame=args["symbol"][0],args["interval"][0]
                if symbol=="BTCUSDT" and frame=="15m":
                    btc_fifteen_calls+=1
                    body=inconsistent if btc_fifteen_calls==1 else candles[symbol][frame]
                else:
                    body=candles[symbol][frame]
                return body,boundary+1_000,10.0
            if parsed.path.endswith("/exchangeInfo"):
                return info,boundary+1_000,10.0
            if parsed.path.endswith("/bookTicker"):
                return books[args["symbol"][0]],boundary+1_000,10.0
            raise AssertionError("Unexpected endpoint")

        with TemporaryDirectory(prefix="v7sonic-candle-finalization-") as tmp:
            with patch.object(smoke,"START_MS",boundary+STEP_MS):
                with patch.object(smoke,"_get",side_effect=mocked_get):
                    with patch.object(smoke.time,"sleep"):
                        with patch.object(smoke.time,"time_ns",side_effect=[
                            (boundary-1_000)*1_000_000,
                            (boundary+100)*1_000_000,
                            (boundary+2_000)*1_000_000,
                            (boundary+3_500)*1_000_000,
                            (boundary+3_800)*1_000_000,
                        ]):
                            result=smoke.capture_one(tmp)
            self.assertEqual(len(calls),62)
            self.assertEqual(btc_fifteen_calls,2)
            self.assertEqual(result["capture_attempt_count"],2)
            self.assertEqual(result["original_raw_responses_retained"],62)
            self.assertEqual(result["public_gets"],62)
            files=list(Path(tmp).glob("v7sonic-original-http-*.json"))
            rejects=list(Path(tmp).glob("v7sonic-rejected-*.json"))
            self.assertEqual(len(files),2)
            self.assertEqual(len(rejects),1)
            self.assertTrue(Path(result["report_path"]).exists())

            for idx,expected_pass in ((0,False),(1,True)):
                source=result["attempt_evidence"][idx]
                proof=replay.replay_original(
                    replay._read_private_file(source["original_raw_evidence_path"])
                )
                self.assertEqual(proof["original_http_responses_hash_checked"],31)
                self.assertEqual(proof["exact_reconciliation_passed"],expected_pass)
                self.assertEqual(proof["telegram_messages_sent"],0)
                self.assertEqual(proof["orders_submitted"],0)
            rejected=json.loads(rejects[0].read_text())
            self.assertTrue(rejected["fresh_full_batch_retry_planned"])
            self.assertTrue(rejected["raw_sources_preserved"])
            self.assertFalse(rejected["client_publication_authorized"])

    def test_persistent_15m_mismatch_exhausts_retry_without_paper_report(self):
        candles,books,info,_=self.fixture()
        boundary=START_MS+STEP_MS
        bad=json.loads(candles["DOGEUSDT"]["15m"])
        from decimal import Decimal
        bad[-1][5]=str(Decimal(bad[-1][5])+Decimal("1"))
        candles["DOGEUSDT"]["15m"]=json.dumps(bad).encode()
        calls=[]

        def mocked_get(url,maximum):
            calls.append(url)
            parsed=urlparse(url)
            args=parse_qs(parsed.query)
            if parsed.path.endswith("/klines"):
                return candles[args["symbol"][0]][args["interval"][0]],boundary+1_000,10.0
            if parsed.path.endswith("/exchangeInfo"):
                return info,boundary+1_000,10.0
            if parsed.path.endswith("/bookTicker"):
                return books[args["symbol"][0]],boundary+1_000,10.0
            raise AssertionError("Unexpected endpoint")

        with TemporaryDirectory(prefix="v7sonic-persistent-mismatch-") as tmp:
            with patch.object(smoke,"START_MS",boundary+STEP_MS):
                with patch.object(smoke,"_get",side_effect=mocked_get):
                    with patch.object(smoke.time,"sleep"):
                        with patch.object(smoke.time,"time_ns",side_effect=[
                            (boundary-1_000)*1_000_000,
                            (boundary+100)*1_000_000,
                            (boundary+2_000)*1_000_000,
                            (boundary+4_000)*1_000_000,
                            (boundary+6_000)*1_000_000,
                        ]):
                            with self.assertRaisesRegex(ValueError,
                                    "Native timeframe contradicts"):
                                smoke.capture_one(tmp)
            self.assertEqual(len(calls),93)
            self.assertEqual(len(list(
                Path(tmp).glob("v7sonic-original-http-*.json")
            )),3)
            self.assertEqual(len(list(
                Path(tmp).glob("v7sonic-rejected-*.json")
            )),3)
            self.assertEqual(list(
                Path(tmp).glob("v7sonic-early-smoke-*.json")
            ),[])
            self.assertFalse(any(
                replay.replay_original(replay._read_private_file(str(p)))[
                    "exact_reconciliation_passed"
                ] for p in Path(tmp).glob("v7sonic-original-http-*.json")
            ))

    def test_exact_31_original_response_bytes_survive_reopen_and_replay(self):
        candles,books,info,times=self.fixture()
        with TemporaryDirectory(prefix="v7sonic-original-http-test-") as tmp:
            filename,digest=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2_000)
            self.assertTrue(Path(filename).is_file())
            report=replay.replay_original(
                replay._read_private_file(filename)
            )
            self.assertEqual(report["original_http_responses_hash_checked"],31)
            self.assertEqual(report["price_field_discrepancies"],0)
            self.assertEqual(report["volume_field_discrepancies"],0)
            self.assertTrue(report["exact_reconciliation_passed"])
            self.assertFalse(report["client_publication_authorized"])
            self.assertTrue(len(digest)==64)
            with self.assertRaises(FileExistsError):
                smoke._save_original_responses(
                    Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                    START_MS+STEP_MS+2_000)

    def test_an_actual_15m_volume_disagreement_is_reproducible_from_original(self):
        candles,books,info,times=self.fixture()
        source=json.loads(candles["BTCUSDT"]["15m"])
        from decimal import Decimal
        source[-1][5]=str(Decimal(source[-1][5])+Decimal("0.00000001"))
        candles["BTCUSDT"]["15m"]=json.dumps(source).encode()
        with TemporaryDirectory(prefix="v7sonic-mismatch-evidence-") as tmp:
            filename,_=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2_000)
            result=replay.replay_original(replay._read_private_file(filename))
            self.assertEqual(result["price_field_discrepancies"],0)
            self.assertEqual(result["volume_field_discrepancies"],1)
            self.assertFalse(result["exact_reconciliation_passed"])
            self.assertFalse(result["client_publication_authorized"])

    def test_full_original_seven_field_binance_books_feed_paper_decisions(self):
        candles,books,info,times=self.fixture()
        # Reproduces the seven-field format actually captured by VPS.
        for symbol in MARKETS:
            original=json.loads(books[symbol])
            original["lastUpdateId"]=11797344941317
            books[symbol]=json.dumps(original,separators=(",",":")).encode()
        with TemporaryDirectory(prefix="v7sonic-real-book-replay-") as tmp:
            filename,_=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2_000
            )
            with patch.object(smoke,"_get") as get:
                observed=replay.replay_full_original_paper_analysis(
                    replay._read_private_file(filename)
                )
                get.assert_not_called()
        self.assertEqual(observed["original_http_sha256_verified_count"],31)
        self.assertTrue(observed["exact_candle_reconciliation_passed"])
        self.assertEqual(observed["paper_market_count"],6)
        self.assertEqual(len(observed["paper_decisions"]),6)
        self.assertEqual(set(observed["per_market_quote_ages_ms"]),set(MARKETS))
        self.assertFalse(observed["client_publication_authorized"])
        self.assertEqual(observed["telegram_messages_sent"],0)
        self.assertEqual(observed["orders_submitted"],0)
        self.assertTrue(observed["historical_offline_replay_only"])

    def test_seven_field_original_stale_time_is_not_accepted_in_paper_replay(self):
        candles,books,info,times=self.fixture()
        for symbol in MARKETS:
            original=json.loads(books[symbol])
            original["lastUpdateId"]=11797344941317
            if symbol=="BTCUSDT":
                original["time"]=START_MS-1
            books[symbol]=json.dumps(original,separators=(",",":")).encode()
        with TemporaryDirectory(prefix="v7sonic-stale-real-book-") as tmp:
            filename,_=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2_000
            )
            with self.assertRaisesRegex(ValueError,"timestamp stale"):
                replay.replay_full_original_paper_analysis(
                    replay._read_private_file(filename)
                )

    def test_any_tampered_original_body_hash_causes_replay_rejection(self):
        candles,books,info,times=self.fixture()
        with TemporaryDirectory(prefix="v7sonic-corrupt-original-") as tmp:
            filename,_=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2_000)
            original=replay._read_private_file(filename)
            updated=deepcopy(original)
            updated["kline_bodies"]["BTCUSDT"]["1m"]["original_body_sha256"]="0"*64
            with self.assertRaisesRegex(ValueError,"source body mismatch"):
                replay.replay_original(updated)
            updated=deepcopy(original)
            updated["quote_bodies"].pop("BTCUSDT")
            with self.assertRaises(ValueError):
                replay.replay_original(updated)
            updated=deepcopy(original)
            updated["client_publication_authorized"]=True
            with self.assertRaises(ValueError):
                replay.replay_original(updated)

    def test_failed_live_analysis_keeps_original_31_bodies_and_failure_record(self):
        candles,books,info,times=self.fixture()
        now=START_MS-2*STEP_MS+1000
        boundary=START_MS-STEP_MS
        observed=boundary+1000
        completed=boundary+2000
        calls=[]

        def mocked_get(url,maximum):
            calls.append(url)
            path=urlparse(url).path
            params=parse_qs(urlparse(url).query)
            if path.endswith("/klines"):
                symbol=params["symbol"][0]
                frame=params["interval"][0]
                return candles[symbol][frame],observed,10.0
            if path.endswith("/exchangeInfo"):
                return info,observed,10.0
            if path.endswith("/bookTicker"):
                symbol=params["symbol"][0]
                return books[symbol],observed,10.0
            raise AssertionError("Unexpected HTTP endpoint")

        # Test source fixtures are for a later frozen boundary than this
        # early capture. Strict analyzer MUST reject, not modify or publish.
        with TemporaryDirectory(prefix="v7sonic-rejected-live-test-") as tmp:
            with patch.object(smoke,"_get",side_effect=mocked_get):
                with patch.object(smoke.time,"sleep"):
                    with patch.object(smoke.time,"time_ns",side_effect=[
                        now*1_000_000,observed*1_000_000,
                        completed*1_000_000
                    ]):
                        with self.assertRaises(ValueError):
                            smoke.capture_one(tmp)
            self.assertEqual(len(calls),31)
            rawfiles=list(Path(tmp).glob("v7sonic-original-http-*.json"))
            rejectfiles=list(Path(tmp).glob("v7sonic-rejected-*.json"))
            self.assertEqual(len(rawfiles),1)
            self.assertEqual(len(rejectfiles),1)
            self.assertEqual(
                replay._read_private_file(str(rawfiles[0]))[
                    "original_public_rest_responses_retained"],31
            )
            rejection=json.loads(rejectfiles[0].read_text())
            self.assertTrue(rejection["raw_sources_preserved"])
            self.assertFalse(rejection["client_publication_authorized"])
            self.assertFalse(rejection["telegram_enqueued"])
            self.assertEqual(list(Path(tmp).glob("v7sonic-early-smoke-*.json")),[])

    def test_offline_replay_has_no_network_or_telegram_side_effects(self):
        candles,books,info,times=self.fixture()
        with TemporaryDirectory(prefix="v7sonic-replay-no-net-") as tmp:
            filename,_=smoke._save_original_responses(
                Path(tmp),START_MS+STEP_MS,candles,books,info,times,
                START_MS+STEP_MS+2000)
            with patch.object(smoke,"_get") as http:
                report=replay.replay_original(replay._read_private_file(filename))
                http.assert_not_called()
                self.assertEqual(report["telegram_messages_sent"],0)
                self.assertEqual(report["orders_submitted"],0)


if __name__=="__main__":
    import unittest
    unittest.main()
