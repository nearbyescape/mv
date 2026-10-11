"""T7Sonic pinned monthly-archive ingestion: full real-format synthetic ZIP tests.

Synthetic fixtures have calendar-complete 2026-04 monthly 1m/15m/1h/4h
files, each a full Binance 12-column CSV under V5-compatible ZIP/sidecar.
All "publisher" identifiers are local fixtures: NO real source claims.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from app.research.t7sonic_history import (
    FROZEN_SOURCE_SPEC_SHA256, HISTORICAL_FRAMES,
    SOURCE_INTERVALS, _calendar_months, _necessary_first_ms,
    _source_location, _derive_5m, verified_historical_snapshot,
    historical_research_case,
)
from app.research.t7sonic_history_cli import _date_ms, plan_history


AT = _date_ms("2026-04-20T12:00:00Z")
MONTH_START = _date_ms("2026-04-01T00:00:00Z")
MONTH_END = int(datetime(2026,5,1,tzinfo=timezone.utc).timestamp()*1000)
SYMBOL = "BTCUSDT"


def _bar_values(index, width):
    start = D("100") + D(index)*D(".0005")
    end = D("100") + D(index + width-1)*D(".0005")
    return (start, end + D(".1"), start - D(".1"), end+D(".005"), D(width))


def _month_zip(frame, corrupt=None):
    """Build exactly one complete 2026-April with consistent minute aggregates."""
    step=SOURCE_INTERVALS[frame]
    group=step//60_000
    count=(MONTH_END-MONTH_START)//step
    name=f"{SYMBOL}-{frame}-2026-04.csv"
    output=io.StringIO(newline="")
    for i in range(count):
        start_ms=MONTH_START+i*step
        o,h,l,c,v=_bar_values(i*group,group)
        if corrupt == "modified_one_hour" and frame=="1h" and i==465:
            c += D("0.01")
        if corrupt == "missing_last" and i==count-1:
            break
        row=[str(start_ms),str(o),str(h),str(l),str(c),
             str(v),str(start_ms+step-1),"0","1","0","0","0"]
        output.write(",".join(row)+"\n")
    bytesio=io.BytesIO()
    with zipfile.ZipFile(bytesio,"w",compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(name, output.getvalue())
    return bytesio.getvalue()


def _write_source(root: Path, frame: str, z: bytes):
    source, sidecar = _source_location(root,SYMBOL,frame,"2026-04")
    source.parent.mkdir(parents=True,exist_ok=True)
    source.write_bytes(z)
    start,end=MONTH_START,MONTH_END
    filename=source.name
    url=(f"https://data.binance.vision/data/futures/um/monthly/klines/"
         f"{SYMBOL}/{frame}/{filename}")
    rec={
        "symbol":SYMBOL,"timeframe":frame,"month":"2026-04",
        "filename":filename,
        "start_ms":start,"end_exclusive_ms":end,
        "expected_rows":(end-start)//SOURCE_INTERVALS[frame],
        "verified_rows":(end-start)//SOURCE_INTERVALS[frame],
        "spec_sha256":FROZEN_SOURCE_SPEC_SHA256,
        "source_sha256":sha256(z).hexdigest(),
        "url":url,"checksum_url":url+".CHECKSUM",
    }
    sidecar.write_text(json.dumps(rec,sort_keys=True),encoding="utf-8")
    return source,sidecar


class HistoricalAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="t7sonic-calendar-")
        cls.root=Path(cls.temp.name)
        cls.files={}
        for frame in HISTORICAL_FRAMES:
            z=_month_zip(frame)
            cls.files[frame]=_write_source(cls.root,frame,z)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_full_calendar_verified_and_5m_derived_from_trusted_1m(self):
        snapshot,proof=verified_historical_snapshot(self.root,SYMBOL,AT)
        self.assertEqual(snapshot["as_of_ms"],AT)
        self.assertEqual(set(snapshot["bars"]),{"1m","5m","15m","1h","4h"})
        for frame in snapshot["bars"]:
            self.assertEqual(len(snapshot["bars"][frame]),64)
        self.assertEqual(len(proof["source_months_verified"]),4)
        self.assertEqual(proof["source_months_verified"]["1m"][0][
            "verified_calendar_rows"],43200)
        self.assertEqual(proof["five_minute_derivation"],
                         "EXACT_FIVE_CONSECUTIVE_PINNED_ONE_MINUTE_BARS")
        self.assertEqual(
            proof["resolution_reconciliation"]["native_bars_reconciled_to_1m"]["4h"],1
        )
        self.assertEqual(snapshot["bars"]["5m"][-1]["open_ms"], AT-300_000)
        first_five = snapshot["bars"]["5m"][0]
        self.assertEqual(D(first_five["volume"]),D(5))

    def test_research_watch_only_and_preserved_source_provenance(self):
        output=historical_research_case(self.root,(SYMBOL,),AT)
        self.assertEqual(output["engine"],"T7Sonic")
        self.assertTrue(output["development_only"])
        self.assertEqual(output["market_count"],1)
        self.assertEqual(output["actionable_signal_count"],0)
        self.assertFalse(output["publication_authorized"])
        self.assertFalse(output["orders_authorized"])
        self.assertEqual(output["run_scope"],"EXPLICIT_SUBSET_NOT_FULL_UNIVERSE")
        for report in output["market_reports"]:
            for watch in report["watch_hypotheses"]:
                self.assertFalse(watch["publishable_signal"])
                self.assertFalse(watch["executable_order"])
                self.assertIsNone(watch["win_probability"])

    def test_presence_plan_is_not_integrity_validation(self):
        summary=plan_history(self.root,(SYMBOL,),AT)
        self.assertEqual(summary["missing_pinned_month_pairs"],[])
        self.assertTrue(summary["ready_for_complete_checksum_validation"])
        self.assertTrue(summary["source_integrity_not_tested"])
        self.assertEqual(summary["required_source_months_by_market_frame"][
            SYMBOL]["1m"],["2026-04"])

    def test_missing_minute_archive_blocks_replay(self):
        source,manifest=self.files["1m"]
        original=source.read_bytes()
        try:
            source.unlink()
            plan=plan_history(self.root,(SYMBOL,),AT)
            self.assertEqual(plan["missing_pinned_month_pairs"][0]["frame"],"1m")
            with self.assertRaises(FileNotFoundError):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            source.write_bytes(original)

    def test_checksum_tampering_blocks_replay(self):
        source,_=self.files["1m"]
        original=source.read_bytes()
        try:
            source.write_bytes(original+b"tampered")
            with self.assertRaisesRegex(ValueError,"checksum"):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            source.write_bytes(original)

    def test_modified_manifest_spec_sha_blocks_replay(self):
        _,sidecar=self.files["4h"]
        original=sidecar.read_text()
        try:
            r=json.loads(original)
            r["spec_sha256"]="a"*64
            sidecar.write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,"spec_sha256"):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            sidecar.write_text(original)

    def test_complete_zip_repacked_with_missing_last_row_is_rejected(self):
        src,manifest=self.files["1h"]
        original_zip=src.read_bytes()
        original_manifest=manifest.read_text()
        try:
            new_data=_month_zip("1h","missing_last")
            src.write_bytes(new_data)
            rec=json.loads(original_manifest)
            rec["source_sha256"]=sha256(new_data).hexdigest()
            manifest.write_text(json.dumps(rec))
            with self.assertRaisesRegex(ValueError,"Incomplete calendar"):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            src.write_bytes(original_zip)
            manifest.write_text(original_manifest)

    def test_native_resolution_disagreement_rejected_even_if_sha_updated(self):
        src,manifest=self.files["1h"]
        original_zip=src.read_bytes()
        original_manifest=manifest.read_text()
        try:
            new_data=_month_zip("1h","modified_one_hour")
            src.write_bytes(new_data)
            rec=json.loads(original_manifest)
            rec["source_sha256"]=sha256(new_data).hexdigest()
            manifest.write_text(json.dumps(rec))
            with self.assertRaisesRegex(ValueError,"contradicts"):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            src.write_bytes(original_zip)
            manifest.write_text(original_manifest)

    def test_asof_guard_never_reads_validation_or_holdout(self):
        for iso in ("2026-06-01T00:00:00Z","2026-08-20T12:00:00Z",
                    "2026-03-20T12:00:00Z"):
            with self.assertRaises(ValueError):
                _date_ms(iso)
        with self.assertRaisesRegex(ValueError,"Apr–May"):
            verified_historical_snapshot(
                self.root,SYMBOL,int(datetime(2026,6,2,tzinfo=timezone.utc).timestamp()*1000))
        with self.assertRaisesRegex(ValueError,"five-minute"):
            verified_historical_snapshot(self.root,SYMBOL,AT+60_000)

    def test_not_possible_to_smuggle_unknown_or_duplicate_market(self):
        with self.assertRaises(ValueError):
            historical_research_case(self.root,(SYMBOL,SYMBOL),AT)
        with self.assertRaises(ValueError):
            historical_research_case(self.root,("FAKEUSDT",),AT)
        with self.assertRaises(ValueError):
            historical_research_case(self.root,tuple([SYMBOL]*7),AT)

    def test_symlink_rejected_even_if_zip_bytes_are_valid(self):
        src, _=self.files["15m"]
        original=src.read_bytes()
        target=self.root/"source-backup.tmp"
        try:
            target.write_bytes(original)
            src.unlink()
            src.symlink_to(target)
            with self.assertRaisesRegex(ValueError,"Symlink"):
                verified_historical_snapshot(self.root,SYMBOL,AT)
        finally:
            src.unlink()
            src.write_bytes(original)
            target.unlink()

    def test_month_boundary_partition_and_windows(self):
        start,end=_necessary_first_ms("4h",AT)
        self.assertEqual(_calendar_months(start,end),("2026-04",))
        first_april=_date_ms("2026-04-01T00:00:00Z")
        prior,end=_necessary_first_ms("4h",first_april)
        self.assertEqual(_calendar_months(prior,end),("2026-03",))
        self.assertEqual(end,first_april)


if __name__ == "__main__":
    unittest.main()
