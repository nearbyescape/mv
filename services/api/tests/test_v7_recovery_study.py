"""V7 recovery negative/fault tests. Synthetic only; zero external network."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D
from io import BytesIO
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from hashlib import sha256

from app.research.t7sonic_perception import Bar
from app.research.v7_recovery_archives import (
    STEP_MS, verified_month, monthly_paths, expected_month_start,
)
from app.research.v7_recovery_acquire import acquire
from app.research.v7_recovery_engine import (
    POLICY, MAX_OVERLAPPING_PAPER_IDEAS, POLICY_SHA256, PriceBar,
    generate_decisions, portfolio_simulation, simulated_exit, _hourly,
)
from app.research.v7_recovery_study import _summary


START = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()*1000)


def synthetic(n=600):
    rows = []
    previous = D("100")
    for i in range(n):
        step = D("0.04") + D(str(math.sin(i/7))) * D("0.02")
        close = previous + step
        rows.append(Bar(
            START+i*STEP_MS, previous,
            max(previous, close)+D(".24"),
            min(previous, close)-D(".24"),
            close, D("100"),
        ))
        previous = close
    return rows


class RecoveryEngineTests(unittest.TestCase):
    def test_new_policy_separate_and_never_publishes(self):
        rows=synthetic()
        events, reasons=generate_decisions(rows, symbol="BTCUSDT")
        self.assertEqual(POLICY, "V7_RECOVERY_HOURLY_TREND_15M_REENTRY_PAPER_V1")
        self.assertEqual(len(POLICY_SHA256), 64)
        self.assertEqual(sum(reasons.values()), len(rows)-221)
        self.assertGreater(len(events), 0, "Synthetic aligned trend must generate research references")
        for e in events:
            self.assertEqual(e["policy"], POLICY)
            self.assertFalse(e["client_publication_authorized"])
            self.assertFalse(e["exchange_fills_verified"])
            self.assertGreater(e["modeled_target_net_R"], 1.24999)
            self.assertGreater(e["decision_boundary_ms"], START)

    def test_closed_bar_causality_and_future_mutation(self):
        rows=synthetic(520)
        a,_=generate_decisions(rows[:400], symbol="BTCUSDT")
        extra=list(rows)
        last=extra[450]
        extra[450]=Bar(last.open_ms,last.opening,last.high+D("50"),
                       last.low,last.close,last.volume)
        b,_=generate_decisions(extra, symbol="BTCUSDT")
        early=[x for x in b if x["entry_bar_index"] < 400]
        self.assertEqual(a, early)

    def test_missing_bar_rejected(self):
        rows=synthetic()
        del rows[250]
        with self.assertRaisesRegex(ValueError, "contiguous"):
            generate_decisions(rows, symbol="BTCUSDT")

    def test_requires_complete_utc_hourly_frame(self):
        rows=synthetic(601)
        with self.assertRaisesRegex(ValueError, "hourly boundary"):
            _hourly([PriceBar(x.open_ms, float(x.opening), float(x.high),
                              float(x.low), float(x.close), float(x.volume))
                     for x in rows])

    def test_ambiguous_bar_is_stop_first_with_cost(self):
        bars=[PriceBar(START,100,107,94,101,10)]*40
        t={"entry_bar_index":0,"entry":100.0,"stop":95.0,
           "target":106.0,"direction":1,"risk_price":5.0,
           "decision_boundary_ms":START,"symbol":"BTCUSDT",
           "client_publication_authorized":False}
        result=simulated_exit(t,bars)
        self.assertEqual(result["outcome"],"AMBIGUOUS_STOP_FIRST")
        self.assertLess(result["net_R"], -1)
        self.assertFalse(result["actual_fill_verified"])
        self.assertEqual(result["telegram_messages_sent"],0)

    def test_short_gap_through_stop_worse_than_stop(self):
        t={"entry_bar_index":0,"entry":100.0,"stop":105.0,
           "target":90.0,"direction":-1,"risk_price":5.0,
           "decision_boundary_ms":START,"symbol":"BTCUSDT"}
        b=[PriceBar(START,109,111,95,106,100)]*40
        result=simulated_exit(t,b)
        self.assertEqual(result["exit"],109)
        self.assertLess(result["net_R"],-1.5)

    def test_portfolio_symbol_and_slot_limits(self):
        series={symbol:synthetic() for symbol in (
            "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT"
        )}
        result=portfolio_simulation(series)
        self.assertEqual(result["reference_max_concurrent_slots"],
                         MAX_OVERLAPPING_PAPER_IDEAS)
        self.assertFalse(result["client_publication_authorized"])
        self.assertEqual(result["orders_submitted"],0)
        self.assertLessEqual(result["selected_paper_references"],
                             result["proposals_before_portfolio_constraints"])

    def test_day_cluster_summary_can_be_empty_no_false_positive(self):
        result=_summary([],["2026-04-01", "2026-04-02"])
        self.assertEqual(result["hypothetical_closed_ideas"],0)
        self.assertIsNone(result["mean_costed_R_per_closed_reference"])
        self.assertEqual(result["day_cluster_bootstrap_mean_R_95pct"],[0,0])

    def test_download_defaults_to_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch(
            "app.research.v7_recovery_acquire._http_get",
            side_effect=AssertionError("Network forbidden")
        ):
            result=acquire(Path(d),("BTCUSDT",),("2026-04",),enabled=False)
        self.assertEqual(result["status"],"NO_NETWORK_DATA_ACQUISITION_DISABLED")


class MonthlySourceTests(unittest.TestCase):
    def _archive(self, root: Path, *, truncated=False):
        symbol, month="BTCUSDT","2026-04"
        first,end=expected_month_start(month)
        total=(end-first)//STEP_MS
        archive, sidecar=monthly_paths(root,symbol,month)
        archive.parent.mkdir()
        stream=BytesIO()
        with ZipFile(stream,"w",ZIP_DEFLATED) as z:
            rows=[]
            for i in range(total-int(truncated)):
                ts=first+i*STEP_MS
                rows.append(
                    f"{ts},100,101,99,100.2,50,{ts+STEP_MS-1},0,10,5,0,0"
                )
            z.writestr(archive.name[:-4]+".csv", "\n".join(rows)+"\n")
        raw=stream.getvalue()
        archive.write_bytes(raw)
        sidecar.write_text(sha256(raw).hexdigest()+"  "+archive.name+"\n")
        return archive,sidecar,total

    def test_full_month_provenance_and_calendar(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            _,_,total=self._archive(root)
            rows,proof=verified_month(root,"BTCUSDT","2026-04")
            self.assertEqual(len(rows),total)
            self.assertEqual(proof["verified_rows"],total)
            self.assertFalse(proof["publisher_checksum_is_independent_attestation"])

    def test_incomplete_month_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            self._archive(root,truncated=True)
            with self.assertRaisesRegex(ValueError,"Incomplete source month"):
                verified_month(root,"BTCUSDT","2026-04")

    def test_corrupted_checksum_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve()
            _,sidecar,_=self._archive(root)
            sidecar.write_text("0"*64+"  BTCUSDT-15m-2026-04.zip\n")
            with self.assertRaisesRegex(ValueError,"checksum mismatch"):
                verified_month(root,"BTCUSDT","2026-04")


if __name__ == "__main__":
    unittest.main()
