"""No-network V7 private five-minute scheduler tests: no Telegram or orders."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app import v7sonic_release as release
from services.t7sonic import release_scheduler as scheduler
from test_t7sonic_forward_release_bridge import BOUNDARY


class PrivatePaperSchedulerTests(TestCase):
    def capture(self, path, **kwargs):
        self.requests.append((path, kwargs))
        return {
            "status": "PRIVATE_PAPER_CYCLE_DURABLY_STORED_NO_SEND",
            "decision_boundary_ms": BOUNDARY,
            "market_count": 6,
            "client_publication_authorized": False,
            "telegram_messages_sent": 0,
            "orders_submitted": 0,
        }

    def setUp(self):
        self.requests = []

    def test_one_exact_future_boundary_runs_once_without_publication(self):
        with TemporaryDirectory(prefix="v7-schedule-") as tmp:
            with patch.object(release, "_ist_open", return_value=True):
                with patch.object(scheduler,"_check_capacity"):
                    result = scheduler.run_private_paper_loop(
                        tmp, public_network_approved=True,
                        paper_only_acknowledged=True,
                        clock_ms=lambda: BOUNDARY - 900,
                        sleep=lambda _: None,
                        capture=self.capture,
                        max_cycles=1,
                    )
            self.assertEqual(result["completed_cycles"],1)
            self.assertEqual(result["durably_stored_cycles"],1)
            self.assertEqual(len(self.requests),1)
            self.assertEqual(self.requests[0][1],{
                "public_network_approved":True,
                "paper_only_acknowledged":True,
            })
            self.assertFalse(result["client_publication_authorized"])
            self.assertEqual(result["telegram_messages_sent"],0)
            self.assertFalse(list(Path(tmp).glob("v7sonic-private-gap-*.json")))

    def test_bad_private_runner_receipt_fails_closed_and_persists_gap(self):
        def bad_receipt(path, **kwargs):
            return {**self.capture(path, **kwargs), "telegram_messages_sent":1}
        with TemporaryDirectory(prefix="v7-schedule-bad-") as tmp:
            with patch.object(release,"_ist_open",return_value=True):
                with patch.object(scheduler,"_check_capacity"):
                    with self.assertRaisesRegex(ValueError,"unexpected publication"):
                        scheduler.run_private_paper_loop(
                            tmp, public_network_approved=True,
                            paper_only_acknowledged=True,
                            clock_ms=lambda:BOUNDARY-1_000,
                            sleep=lambda _:None,capture=bad_receipt,max_cycles=1
                        )
            receipts=list(Path(tmp).glob("v7sonic-private-gap-*.json"))
            self.assertEqual(len(receipts),1)
            failure=json.loads(receipts[0].read_text())
            self.assertEqual(failure["decision_boundary_ms"],BOUNDARY)
            self.assertEqual(failure["status"],"V7_PRIVATE_CAPTURE_FAILED_NO_SIGNAL_OR_SEND")
            self.assertEqual(failure["telegram_messages_sent"],0)

    def test_off_session_checks_without_http_or_signal(self):
        stopped=[0]
        def interrupted():
            stopped[0]+=1
            return stopped[0]>2
        with TemporaryDirectory(prefix="v7-schedule-off-") as tmp:
            with patch.object(release,"_ist_open",return_value=False):
                result=scheduler.run_private_paper_loop(
                    tmp,public_network_approved=True,
                    paper_only_acknowledged=True,
                    clock_ms=lambda:BOUNDARY-1_000,
                    sleep=lambda _:None,capture=self.capture,
                    stop_requested=interrupted,
                )
            self.assertEqual(result["completed_cycles"],0)
            self.assertEqual(self.requests,[])
            self.assertEqual(list(Path(tmp).iterdir()),[])

    def test_operator_pause_suppresses_pending_boundary(self):
        stop=[0]
        def requested():
            stop[0]+=1
            return stop[0]>2
        with TemporaryDirectory(prefix="v7-schedule-pause-") as tmp:
            marker = Path(tmp, scheduler.PAUSE_NAME)
            marker.write_text("paused\n")
            marker.chmod(0o600)
            with patch.object(release,"_ist_open",return_value=True):
                result=scheduler.run_private_paper_loop(
                    tmp,public_network_approved=True,
                    paper_only_acknowledged=True,
                    clock_ms=lambda:BOUNDARY-1_000,
                    sleep=lambda _:None,capture=self.capture,
                    stop_requested=requested,
                )
            self.assertEqual(result["completed_cycles"],0)
            self.assertEqual(self.requests,[])

    def test_no_approval_or_clock_regression(self):
        with TemporaryDirectory(prefix="v7-schedule-approval-") as tmp:
            with self.assertRaises(PermissionError):
                scheduler.run_private_paper_loop(tmp)
            times=iter([BOUNDARY-100,BOUNDARY-9_000])
            with self.assertRaisesRegex(RuntimeError,"Clock moved backwards"):
                scheduler.run_private_paper_loop(
                    tmp,public_network_approved=True,
                    paper_only_acknowledged=True,
                    clock_ms=lambda:next(times),
                    sleep=lambda _:None,capture=self.capture,
                )
            self.assertEqual(self.requests,[])

    def test_low_disk_fails_before_http_and_preflight_is_offline(self):
        with TemporaryDirectory(prefix="v7-schedule-disk-") as tmp:
            with patch.object(release,"_ist_open",return_value=True):
                with patch.object(scheduler,"_check_capacity",
                                  side_effect=OSError("disk reserve")):
                    with self.assertRaisesRegex(OSError,"disk reserve"):
                        scheduler.run_private_paper_loop(
                            tmp,public_network_approved=True,
                            paper_only_acknowledged=True,
                            clock_ms=lambda:BOUNDARY-1_000,
                            capture=self.capture,
                        )
            self.assertEqual(self.requests,[])
            self.assertEqual(
                scheduler.preflight(BOUNDARY-1_000)["status"],
                "V7_PRIVATE_SCHEDULER_PREFLIGHT_NO_NETWORK",
            )


if __name__ == "__main__":
    import unittest
    unittest.main()
