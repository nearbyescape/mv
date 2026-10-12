"""Offline-only 1m/native discrepancy forensic tests. No Binance requests."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime,timezone
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from app.research.t7sonic_forward_protocol import START_MS
from app.research.t7sonic_validation_plan import MARKETS
from services.t7sonic import forensic_cross_resolution as forensic
from test_t7sonic_forward_release_bridge import source_bundle, BOUNDARY


def example_sources():
    sources,_=source_bundle()
    return {
        symbol:{frame:sources[symbol][frame][1]
                for frame in forensic.FRAMES}
        for symbol in MARKETS
    }


def change_last(source, symbol="BTCUSDT", frame="15m",
                field=5, delta="0.00000001"):
    result=deepcopy(source)
    parsed=json.loads(result[symbol][frame])
    parsed[-1][field]=str(D(parsed[-1][field])+D(delta))
    result[symbol][frame]=json.dumps(parsed).encode()
    return result


class CrossResolutionForensicTests(TestCase):
    def test_complete_clean_full_six_market_matches(self):
        report=forensic.forensic_compare(BOUNDARY,example_sources())
        self.assertTrue(report["exact_reconciliation_passed"])
        self.assertEqual(report["price_field_discrepancies"],0)
        self.assertEqual(report["volume_field_discrepancies"],0)
        self.assertEqual(set(report["markets"]),set(MARKETS))
        self.assertEqual(
            report["markets"]["BTCUSDT"]["15m"]["native_bars_compared"],31
        )
        self.assertFalse(report["client_publication_authorized"])

    def test_exact_volume_rounding_discrepancy_exposed_not_suppressed(self):
        report=forensic.forensic_compare(
            BOUNDARY,change_last(example_sources(),field=5)
        )
        self.assertFalse(report["exact_reconciliation_passed"])
        self.assertEqual(report["price_field_discrepancies"],0)
        self.assertEqual(report["volume_field_discrepancies"],1)
        data=report["markets"]["BTCUSDT"]["15m"]
        self.assertEqual(data["bars_with_volume_disagreement"],1)
        self.assertEqual(data["bars_with_price_disagreement"],0)
        changed=data["first_three_examples"][0]["different_fields"]
        self.assertEqual(set(changed),{"volume"})
        self.assertEqual(changed["volume"]["derived_minus_native"],
                         "-0.00000001")
        self.assertFalse(report["cross_timeframe_tolerance_applied"])

    def test_real_price_high_difference_exposed_as_price_discrepancy(self):
        report=forensic.forensic_compare(
            BOUNDARY,change_last(example_sources(),field=2,delta="0.01")
        )
        self.assertEqual(report["price_field_discrepancies"],1)
        changes=report["markets"]["BTCUSDT"]["15m"]["first_three_examples"][0][
            "different_fields"
        ]
        self.assertIn("high",changes)
        self.assertNotIn("volume",changes)

    def test_incomplete_source_rejected_without_report(self):
        samples=example_sources()
        samples["BNBUSDT"].pop("4h")
        with self.assertRaises(ValueError):
            forensic.forensic_compare(BOUNDARY,samples)

    def test_frozen_oct15_window_not_eligible_for_historical_requery(self):
        date="2026-10-12T12:45:00Z"
        original=int(datetime(2026,10,12,12,45,tzinfo=timezone.utc).timestamp()*1000)
        self.assertEqual(
            forensic._past_boundary(date,original+3600_000),original
        )
        for date,now in (
            ("2026-10-15T00:00:00Z",START_MS+60_000),
            ("2026-10-15T00:05:00Z",START_MS+3600_000),
            ("2026-10-12T12:45:00+00:00",START_MS-20_000),
            ("2026-10-12T12:46:00Z",START_MS-20_000),
        ):
            with self.subTest(date=date),self.assertRaises(ValueError):
                forensic._past_boundary(date,now)

    def test_private_evidence_atomic_no_overwrite(self):
        with TemporaryDirectory(prefix="v7sonic-forensic-test-") as tmp:
            path=Path(tmp)
            self.assertEqual(forensic._owner_private_folder(tmp),path)
            created=forensic._write_once(path,"forensic.json",b"{}\n")
            self.assertTrue(Path(created).is_file())
            self.assertEqual(Path(created).stat().st_mode & 0o077,0)
            with self.assertRaises(FileExistsError):
                forensic._write_once(path,"forensic.json",b"{}\n")

    def test_fetch_not_activated_by_pure_analysis_or_offline_preflight(self):
        with patch.object(forensic,"_get") as network:
            self.assertTrue(
                forensic.forensic_compare(BOUNDARY,example_sources())[
                    "exact_reconciliation_passed"
                ]
            )
            network.assert_not_called()


if __name__=="__main__":
    import unittest
    unittest.main()
