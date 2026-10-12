"""Manual live-capture runner tests. All HTTP source reads are mocked."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.research.t7sonic_forward_protocol import (
    START_MS, END_MS, STEP_MS,
)
from services.t7sonic import manual_live_capture_cli as cli


def complete_fake_report(boundary):
    return {
        "status":"INTERNAL_ONLY_PUBLIC_REST_CYCLE_UNATTESTED",
        "decision_boundary_ms":boundary,
        "markets_evaluated":6,
        "candidate_count":0,
        "source_http_responses":31,
        "telegram_enqueued":False,
        "client_publication_authorized":False,
        "real_money_orders_authorized":False,
        "quotes_fresh_at_return_local_clock_claim":True,
        "complete_cycle_returned_before_deadline_local_clock_claim":True,
    }


class ManualLiveCaptureTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(prefix="v7sonic-real-paper-tests-")
        self.directory=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_preflight_has_zero_http_calls_and_freeze_dates(self):
        with patch.object(cli,"optional_public_paper_capture") as get:
            res=cli.offline_preflight(now_ms=START_MS-20_000)
            self.assertEqual(res["status"],"OFFLINE_PREFLIGHT_NO_MARKET_REQUESTS")
            self.assertEqual(res["next_boundary_ms"],START_MS)
            self.assertTrue(res["next_boundary_eligible"])
            self.assertEqual(res["external_requests_made"],0)
            self.assertEqual(len(res["frozen_six_markets"]),6)
            before=cli.offline_preflight(now_ms=START_MS-STEP_MS-1)
            self.assertFalse(before["next_boundary_eligible"])
            after=cli.offline_preflight(now_ms=END_MS)
            self.assertFalse(after["next_boundary_eligible"])
            get.assert_not_called()

    def test_all_three_opt_ins_required_before_any_network(self):
        with patch.object(cli,"optional_public_paper_capture") as get:
            with patch.object(cli.time,"sleep") as nap:
                for overrides in (
                    {},
                    {"capture_approved":True},
                    {"capture_approved":True,"public_network_approved":True},
                    {"capture_approved":True,"paper_only_acknowledged":True},
                    {"capture_approved":True,"public_network_approved":True,
                     "paper_only_acknowledged":False},
                ):
                    with self.subTest(overrides=overrides),self.assertRaises(PermissionError):
                        cli.capture_once(output_dir=str(self.directory),**overrides)
                get.assert_not_called()
                nap.assert_not_called()

    def test_next_boundary_while_before_start_refused_without_sleep(self):
        with patch.object(cli.time,"time_ns",
                          return_value=(START_MS-STEP_MS-1000)*1_000_000):
            with patch.object(cli.time,"sleep") as nap:
                with patch.object(cli,"optional_public_paper_capture") as http:
                    with self.assertRaisesRegex(ValueError,"outside frozen"):
                        cli.capture_once(
                            output_dir=str(self.directory),
                            capture_approved=True,
                            public_network_approved=True,
                            paper_only_acknowledged=True,
                        )
                    nap.assert_not_called()
                    http.assert_not_called()

    def test_success_captures_exactly_one_boundary_and_persists_atomic_report(self):
        when=START_MS+1_000
        boundary=START_MS+STEP_MS
        with patch.object(cli.time,"time_ns",side_effect=[
            when*1_000_000,(boundary+1000)*1_000_000
        ]):
            with patch.object(cli.time,"sleep") as nap:
                with patch.object(cli,"optional_public_paper_capture",
                                  return_value=complete_fake_report(boundary)) as get:
                    result=cli.capture_once(
                        output_dir=str(self.directory),
                        capture_approved=True,
                        public_network_approved=True,
                        paper_only_acknowledged=True,
                    )
        nap.assert_called_once()
        self.assertAlmostEqual(nap.call_args.args[0],299)
        get.assert_called_once_with(boundary,network_approved=True)
        self.assertEqual(result["status"],
                         "LOCAL_PRIVATE_PAPER_CAPTURE_RECORDED_NOT_PUBLISHED")
        self.assertEqual(result["decision_boundary_ms"],boundary)
        self.assertEqual(result["telegram_messages_sent"],0)
        self.assertFalse(result["client_publication_authorized"])
        reportfile=Path(result["report_path"])
        self.assertTrue(reportfile.is_file())
        self.assertEqual(reportfile.stat().st_mode & 0o077,0)
        self.assertEqual(
            json.loads(reportfile.read_text()),complete_fake_report(boundary)
        )
        self.assertEqual(len(list(self.directory.glob(".v7sonic-tmp-*"))),0)

    def test_second_capture_cannot_overwrite_existing_boundary(self):
        boundary=START_MS+STEP_MS
        cli._write_atomic_report(
            self.directory,boundary,complete_fake_report(boundary)
        )
        with self.assertRaises(FileExistsError):
            cli._write_atomic_report(
                self.directory,boundary,complete_fake_report(boundary)
            )
        self.assertEqual(len(list(self.directory.glob("v7sonic-public-paper-*.json"))),1)

    def test_wrong_status_incomplete_or_published_report_refused(self):
        boundary=START_MS
        cases=[
            ("status","ACTIONABLE"),
            ("decision_boundary_ms",boundary+STEP_MS),
            ("markets_evaluated",5),
            ("source_http_responses",30),
            ("telegram_enqueued",True),
            ("client_publication_authorized",True),
            ("real_money_orders_authorized",True),
            ("quotes_fresh_at_return_local_clock_claim",False),
            ("complete_cycle_returned_before_deadline_local_clock_claim",False),
        ]
        for key,value in cases:
            report=complete_fake_report(boundary)
            report[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                cli._write_atomic_report(self.directory,boundary,report)
        self.assertEqual(list(self.directory.glob("*.json")),[])

    def test_incorrect_output_directory_permissions_and_symlink_denied(self):
        public=Path(self.tmp.name)/"public"
        public.mkdir(mode=0o755)
        public.chmod(0o755)
        with self.assertRaises(PermissionError):
            cli._private_output_directory(str(public))
        link=Path(self.tmp.name)/"alias"
        link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(PermissionError):
            cli._private_output_directory(str(link))
        with self.assertRaises(PermissionError):
            cli._private_output_directory("relative")
        self.assertEqual(cli._private_output_directory(str(self.directory)),
                         self.directory)

    def test_late_wakeup_refuses_network_and_failed_capture_writes_nothing(self):
        boundary=START_MS+STEP_MS
        with patch.object(cli.time,"time_ns",side_effect=[
            (START_MS+10_000)*1_000_000,
            (boundary+4001)*1_000_000,
        ]):
            with patch.object(cli.time,"sleep"):
                with patch.object(cli,"optional_public_paper_capture") as fetch:
                    with self.assertRaisesRegex(ValueError,"advanced"):
                        cli.capture_once(
                            output_dir=str(self.directory),
                            capture_approved=True,
                            public_network_approved=True,
                            paper_only_acknowledged=True,
                        )
                    fetch.assert_not_called()
        with patch.object(cli.time,"time_ns",side_effect=[
            (START_MS+10_000)*1_000_000,
            (boundary+1_000)*1_000_000,
        ]):
            with patch.object(cli.time,"sleep"):
                with patch.object(cli,"optional_public_paper_capture",
                                  side_effect=ValueError("public HTTP timeout")):
                    with self.assertRaisesRegex(ValueError,"timeout"):
                        cli.capture_once(
                            output_dir=str(self.directory),
                            capture_approved=True,
                            public_network_approved=True,
                            paper_only_acknowledged=True,
                        )
        self.assertEqual(list(self.directory.iterdir()),[])


if __name__=="__main__":
    import unittest
    unittest.main()
