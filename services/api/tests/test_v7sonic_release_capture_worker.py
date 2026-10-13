"""V7Sonic one-shot public source acquisition + durable PRIVATE paper ledger tests.

ALL real public HTTPS reads are substituted with deterministic fixture bytes.
No production database, Telegram send, API credentials, or exchange orders.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

from app import v7sonic_release as handoff
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic import release_capture_worker as runner
from services.t7sonic.forward_paper_ledger import PrivatePaperLedger
from test_t7sonic_early_live_smoke import data
from test_t7sonic_forward_release_bridge import BOUNDARY


class ReleaseRunnerTests(TestCase):
    def setUp(self):
        self.candles, self.books, self.info, _ = data()
        self.request_urls = []
        self.begin = BOUNDARY

    def getter(self, url, maximum):
        self.request_urls.append(url)
        parsed = urlparse(url)
        args = parse_qs(parsed.query)
        if parsed.path.endswith("/klines"):
            return (self.candles[args["symbol"][0]][args["interval"][0]],
                    BOUNDARY+1000, 10.0)
        if parsed.path.endswith("/exchangeInfo"):
            return self.info, BOUNDARY+1000, 10.0
        if parsed.path.endswith("/bookTicker"):
            return self.books[args["symbol"][0]], BOUNDARY+1000, 10.0
        raise AssertionError("Unexpected HTTP endpoint")

    @staticmethod
    def fake_clock():
        values = iter([
            BOUNDARY-1000, BOUNDARY-1000, BOUNDARY+100,
            BOUNDARY+1000, BOUNDARY+1800, BOUNDARY+2200,
        ])
        return lambda: next(values)

    def run_case(self, directory, *, clock_ms=None):
        return runner.capture_one_private_cycle(
            str(directory),
            public_network_approved=True,
            paper_only_acknowledged=True,
            clock_ms=clock_ms or self.fake_clock(),
            sleeper=lambda _seconds: None,
            getter=self.getter,
        )

    def test_complete_live_shaped_batch_is_durable_not_a_client_signal(self):
        with TemporaryDirectory(prefix="v7-private-runner-") as tmp:
            with patch.object(handoff, "_ist_open", return_value=True):
                result = self.run_case(tmp)
            self.assertEqual(len(self.request_urls),31)
            self.assertEqual(result["market_count"],6)
            self.assertEqual(result["attempt_count"],1)
            self.assertEqual(result["telegram_messages_sent"],0)
            self.assertFalse(result["client_publication_authorized"])
            self.assertFalse(result["production_database_written"])
            receipt = json.loads(Path(result["receipt_path"]).read_text())
            self.assertEqual(receipt["status"],
                             "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND")
            self.assertEqual(len(receipt["source_attempts"]),1)
            self.assertFalse(receipt["position_state_authenticated"])
            self.assertEqual(len(
                list(Path(tmp).glob("v7sonic-original-http-*.json"))),1)
            with PrivatePaperLedger(
                Path(tmp)/"v7sonic-paper-release.sqlite3",
                local_write_approved=True
            ) as ledger:
                audit=ledger.audit(BOUNDARY)
                self.assertTrue(audit["six_decisions_verified"])
                self.assertEqual(audit["batch_sha256"],result["paper_batch_sha256"])

    def test_existing_claim_rejects_repeat_before_network(self):
        with TemporaryDirectory(prefix="v7-private-dedupe-") as tmp:
            with patch.object(handoff, "_ist_open", return_value=True):
                self.run_case(tmp)
                self.request_urls.clear()
                with self.assertRaises(FileExistsError):
                    self.run_case(tmp)
            self.assertEqual(self.request_urls,[])

    def test_missing_user_approvals_and_off_session_are_strict(self):
        with TemporaryDirectory(prefix="v7-private-permission-") as tmp:
            with self.assertRaises(PermissionError):
                runner.capture_one_private_cycle(str(tmp))
            with patch.object(handoff, "_ist_open", return_value=False):
                with self.assertRaisesRegex(ValueError, "outside IST"):
                    self.run_case(tmp)
            self.assertEqual(self.request_urls,[])
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_just_closed_15m_boundary_settles_before_any_rest_get(self):
        """The 16:00 UTC incident involved 15m/1h/4h simultaneous closes.

        Delaying the FIRST whole-source batch does not relax any candle
        reconciliation, freshness cutoff or acquisition-failure semantics.
        """
        close_edge = (BOUNDARY // 900_000 + 1) * 900_000
        calls = []
        clock_values = iter([close_edge - 900, close_edge - 900,
                             close_edge + 100])
        def fake_sleep(seconds):
            calls.append(("sleep", round(seconds, 3)))
        def failed_acquisition(boundary, *, getter):
            calls.append(("GET", boundary))
            raise TimeoutError("diagnostic-retry-timeout")
        with TemporaryDirectory(prefix="v7-close-edge-") as tmp:
            with (
                patch.object(handoff, "_ist_open", return_value=True),
                patch.object(runner, "_capture_all_31",
                             side_effect=failed_acquisition),
            ):
                with self.assertRaisesRegex(TimeoutError, "diagnostic-retry"):
                    runner.capture_one_private_cycle(
                        tmp, public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=lambda: next(clock_values),
                        sleeper=fake_sleep,
                        getter=self.getter,
                    )
            self.assertEqual(
                calls,
                [("sleep", 0.9), ("sleep", 2.4), ("GET", close_edge)],
            )
            self.assertEqual(len(list(Path(tmp).glob(
                "v7sonic-private-acquisition-gap-*.json"
            ))), 1)
            self.assertEqual(list(Path(tmp).glob(
                "v7sonic-private-paper-cycle-*.json"
            )), [])

    def test_non_15m_boundary_does_not_add_settling_lag(self):
        ordinary = BOUNDARY
        self.assertNotEqual(ordinary % 900_000, 0)
        calls = []
        clock_values = iter([ordinary - 900, ordinary - 900,
                             ordinary + 100])
        def fake_sleep(seconds):
            calls.append(("sleep", round(seconds, 3)))
        def failed_acquisition(boundary, *, getter):
            calls.append(("GET", boundary))
            raise TimeoutError("paper-market-source-failed")
        with TemporaryDirectory(prefix="v7-no-close-edge-") as tmp:
            with (
                patch.object(handoff, "_ist_open", return_value=True),
                patch.object(runner, "_capture_all_31",
                             side_effect=failed_acquisition),
            ):
                with self.assertRaisesRegex(TimeoutError, "paper-market"):
                    runner.capture_one_private_cycle(
                        tmp, public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=lambda: next(clock_values),
                        sleeper=fake_sleep,
                        getter=self.getter,
                    )
            self.assertEqual(calls, [("sleep", 0.9), ("GET", ordinary)])

    def test_source_inconsistency_retries_all_31_and_retains_both(self):
        original=self.candles["BTCUSDT"]["15m"]
        rows=json.loads(original)
        from decimal import Decimal
        rows[-1][5]=str(Decimal(rows[-1][5])+Decimal("0.001"))
        altered=json.dumps(rows).encode()
        bad_used=[False]
        def getter(url,maximum):
            p=urlparse(url)
            a=parse_qs(p.query)
            if (p.path.endswith("/klines") and
                a.get("symbol")==["BTCUSDT"] and
                a.get("interval")==["15m"] and
                not bad_used[0]):
                bad_used[0]=True
                self.request_urls.append(url)
                return altered,BOUNDARY+1000,10.0
            return self.getter(url,maximum)
        clock_iter=iter([
            BOUNDARY-1000,BOUNDARY-1000,BOUNDARY+100,
            BOUNDARY+1000,BOUNDARY+1700,BOUNDARY+2000,
            BOUNDARY+2800,BOUNDARY+3400,BOUNDARY+4100,
        ])
        with TemporaryDirectory(prefix="v7-private-retry-") as tmp:
            with patch.object(handoff,"_ist_open",return_value=True):
                result=runner.capture_one_private_cycle(
                    tmp, public_network_approved=True,
                    paper_only_acknowledged=True,
                    clock_ms=lambda:next(clock_iter),
                    sleeper=lambda _seconds:None,
                    getter=getter,
                )
            self.assertEqual(result["attempt_count"],2)
            self.assertEqual(len(self.request_urls),62)
            self.assertEqual(len(list(
                Path(tmp).glob("v7sonic-original-http-*.json")
            )),2)
            self.assertEqual(len(list(
                Path(tmp).glob("v7sonic-private-rejected-*.json")
            )),1)
            self.assertFalse(result["client_publication_authorized"])

    def test_public_rest_timeout_records_failing_symbol_and_timeframe(self):
        """A network gap's immutable receipt identifies its failed public GET."""
        def failing_getter(url, maximum):
            from urllib.parse import parse_qs, urlparse
            parsed = urlparse(url)
            q = parse_qs(parsed.query)
            if q.get("symbol") == ["SOLUSDT"] and q.get("interval") == ["1h"]:
                raise TimeoutError("synthetic-read-timed-out")
            return self.getter(url, maximum)
        with TemporaryDirectory(prefix="v7-timed-endpoint-") as tmp:
            with patch.object(handoff, "_ist_open", return_value=True):
                with self.assertRaisesRegex(
                    TimeoutError, "PUBLIC_BINANCE_HTTP_TIMEOUT\\[SOLUSDT/1h\\]"
                ):
                    runner.capture_one_private_cycle(
                        tmp, public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=self.fake_clock(),
                        sleeper=lambda _:None,
                        getter=failing_getter,
                    )
            gaps = list(Path(tmp).glob(
                "v7sonic-private-acquisition-gap-*.json"
            ))
            self.assertEqual(len(gaps), 1)
            failure = json.loads(gaps[0].read_text())
            self.assertEqual(failure["exception_class"], "TimeoutError")
            self.assertIn(
                "PUBLIC_BINANCE_HTTP_TIMEOUT[SOLUSDT/1h]",
                failure["error_code"],
            )
            self.assertEqual(list(Path(tmp).glob(
                "v7sonic-private-paper-cycle-*.json"
            )), [])

    def test_incomplete_public_http_batch_retains_gap_without_false_no_setup(self):
        def denied(url, maximum):
            raise TimeoutError("simulated-public-source-timeout")
        with TemporaryDirectory(prefix="v7-private-acquire-gap-") as tmp:
            with patch.object(handoff, "_ist_open", return_value=True):
                with self.assertRaisesRegex(TimeoutError, "simulated"):
                    runner.capture_one_private_cycle(
                        tmp,
                        public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=self.fake_clock(),
                        sleeper=lambda _seconds: None,
                        getter=denied,
                    )
            files = list(Path(tmp).glob(
                "v7sonic-private-acquisition-gap-*.json"
            ))
            self.assertEqual(len(files), 1)
            failure=json.loads(files[0].read_text())
            self.assertEqual(
                failure["status"],
                "PRIVATE_PAPER_ACQUISITION_FAILED_NO_SETUP_NOT_INFERRED",
            )
            self.assertFalse(failure["original_http_responses_complete"])
            self.assertFalse(failure["client_publication_authorized"])
            self.assertEqual(failure["telegram_messages_sent"], 0)
            self.assertEqual(failure["orders_submitted"], 0)
            self.assertEqual(
                len(list(Path(tmp).glob("v7sonic-private-claim-*.json"))), 1
            )
            self.assertEqual(
                list(Path(tmp).glob("v7sonic-private-paper-cycle-*.json")), []
            )
            self.assertFalse(
                (Path(tmp) / "v7sonic-paper-release.sqlite3").exists()
            )

    def test_source_corruption_never_creates_false_no_setup(self):
        rows=json.loads(self.candles["BTCUSDT"]["15m"])
        from decimal import Decimal
        rows[-1][5]=str(Decimal(rows[-1][5])+Decimal("1"))
        self.candles["BTCUSDT"]["15m"]=json.dumps(rows).encode()
        tick=[0]
        def clock():
            tick[0]+=1
            return BOUNDARY-1000 if tick[0] <= 2 else BOUNDARY+(tick[0]-2)*300
        with TemporaryDirectory(prefix="v7-private-failure-") as tmp:
            with patch.object(handoff,"_ist_open",return_value=True):
                with self.assertRaisesRegex(ValueError,"reconciliation failed"):
                    runner.capture_one_private_cycle(
                        tmp, public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=clock,
                        sleeper=lambda _seconds:None,
                        getter=self.getter,
                    )
            self.assertEqual(len(self.request_urls),93)
            self.assertEqual(len(list(Path(tmp).glob(
                "v7sonic-original-http-*.json"
            ))),3)
            self.assertEqual(len(list(Path(tmp).glob(
                "v7sonic-private-rejected-*.json"
            ))),3)
            self.assertEqual(list(Path(tmp).glob(
                "v7sonic-private-paper-cycle-*.json"
            )),[])
            self.assertFalse((Path(tmp)/"v7sonic-paper-release.sqlite3").exists())


if __name__=="__main__":
    import unittest
    unittest.main()
