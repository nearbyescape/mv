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

    def test_historical_1330_requery_retains_all_exact_original_bytes(self):
        """A post-hoc 4h/1h/15m study is NEVER a live 13:30 receipt."""
        import base64
        import hashlib
        from urllib.parse import parse_qs, urlparse
        # Shift the synthetic Oct-15 aligned fixture exactly 24h earlier.
        # This tests the historical-only collector without pretending to
        # synthesize a true 13:30 market capture.
        historical_boundary = BOUNDARY - 86_400_000
        originals = example_sources()
        for symbol in MARKETS:
            for frame in forensic.FRAMES:
                rows = json.loads(originals[symbol][frame])
                for row in rows:
                    row[0] -= 86_400_000
                    row[6] -= 86_400_000
                originals[symbol][frame] = json.dumps(rows).encode()
        fetched = []
        def offline_get(url, size):
            parsed = urlparse(url)
            args = parse_qs(parsed.query)
            symbol, frame = args["symbol"][0], args["interval"][0]
            fetched.append((symbol, frame))
            return originals[symbol][frame], BOUNDARY+5_000, 2.5

        with TemporaryDirectory(prefix="v7-historical-1330-proof-") as tmp:
            with patch.object(forensic, "_get", side_effect=offline_get):
                result = forensic.retrieve_and_compare(
                    historical_boundary, output_dir=tmp,
                )
            self.assertEqual(len(fetched), 24)
            packet = json.loads(Path(result["raw_source_file"]).read_bytes())
            self.assertEqual(packet["schema"],2)
            self.assertEqual(packet["source_response_count"],24)
            self.assertFalse(packet["original_close_time_source_reproduced"])
            self.assertFalse(packet["research_only_not_forward_certification"] is False)
            self.assertFalse(packet["client_publication_authorized"])
            self.assertEqual(packet["orders_submitted"],0)
            for symbol in MARKETS:
                for frame in forensic.FRAMES:
                    body = packet["original_http_bodies"][symbol][frame]
                    original = base64.b64decode(body["body_base64"], validate=True)
                    self.assertEqual(original, originals[symbol][frame])
                    self.assertEqual(
                        hashlib.sha256(original).hexdigest(),
                        body["original_body_sha256"],
                    )
            self.assertEqual(
                hashlib.sha256(Path(result["raw_source_file"]).read_bytes()).hexdigest(),
                result["raw_source_sha256"],
            )
            self.assertEqual(result["telegram_messages_sent"],0)
            with self.assertRaises(FileExistsError):
                with patch.object(forensic, "_get", side_effect=offline_get):
                    forensic.retrieve_and_compare(
                        historical_boundary, output_dir=tmp,
                    )

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
