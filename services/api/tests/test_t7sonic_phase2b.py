"""T7Sonic Phase 2B verified source acquisition + causal one-day WATCH replay."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from app.research.t7sonic_history import HISTORICAL_FRAMES, _source_location
from app.research.t7sonic_replay import (
    _as_of, bounded_boundaries, load_source_windows, replay_day
)
from app.research.t7sonic_replay_cli import replay_plan
from test_t7sonic_history import (
    _month_zip, _write_source, AT, SYMBOL
)

REPO_ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location(
    "t7sonic_separate_archive_fetch",
    REPO_ROOT / "services/t7sonic/archive_fetch.py",
)
fetch=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


class ReplayAndAcquisitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix="t7sonic-phase2b-")
        cls.root=Path(cls.temp.name)
        cls.zips={frame:_month_zip(frame) for frame in HISTORICAL_FRAMES}
        for frame,body in cls.zips.items():
            _write_source(cls.root,frame,body)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_one_day_slices_completed_data_and_deduplicates_activations(self):
        # 12 x 5m cutoffs (one hour), no requirement to find an actual
        # tradable setup, since only synthetic price history is present.
        result=replay_day(self.root,(SYMBOL,),"2026-04-20",maximum=12)
        self.assertEqual(result["engine"],"T7Sonic")
        self.assertEqual(result["completed_five_minute_decision_boundaries"],12)
        self.assertEqual(result["symbol_boundary_observations"],12)
        self.assertEqual(result["actionable_signals"],0)
        self.assertFalse(result["outcomes_labeled"])
        self.assertFalse(result["trade_profitability_assessed"])
        self.assertLessEqual(
            result["new_watch_activation_episodes"],
            result["watch_observations_repeated_same_setups"],
        )
        self.assertEqual(len(result["candidate_stream_sha256"]),64)
        self.assertEqual(len(result["first_five_decision_samples"]),5)
        self.assertEqual(result,replay_day(self.root,(SYMBOL,),"2026-04-20",maximum=12))

    def test_future_candle_mutation_cannot_change_past_decision(self):
        times=bounded_boundaries("2026-04-20",maximum=12)
        raw,source_proof=load_source_windows(self.root,SYMBOL,times)
        old=_as_of(raw,SYMBOL,times[0])
        copy=deepcopy(raw)
        last=copy["1m"][-1]
        self.assertGreaterEqual(last.open_ms,times[0])
        copy["1m"][-1]=replace(last,volume=last.volume+1000)
        self.assertEqual(_as_of(copy,SYMBOL,times[0]),old)

    def test_missing_1m_pinned_source_fails_closed(self):
        path,_=_source_location(self.root,SYMBOL,"1m","2026-04")
        original=path.read_bytes()
        try:
            path.unlink()
            inventory=replay_plan(self.root,(SYMBOL,),"2026-04-20",maximum=12)
            self.assertFalse(inventory["ready_for_full_source_verification"])
            self.assertTrue(any(x["frame"]=="1m" for x in inventory[
                "missing_monthly_pairs"]))
            with self.assertRaises(FileNotFoundError):
                replay_day(self.root,(SYMBOL,),"2026-04-20",maximum=12)
        finally:
            path.write_bytes(original)

    def test_replay_fails_outside_inspected_development(self):
        for day in ("2026-06-01","2026-08-01","2026-03-15","2026-05-31"):
            with self.assertRaises(ValueError):
                bounded_boundaries(day)
        for n in (0,289,True):
            with self.assertRaises(ValueError):
                bounded_boundaries("2026-04-20",maximum=n)

    def test_preflight_is_presence_only_not_a_checksum_claim(self):
        plan=replay_plan(self.root,(SYMBOL,),"2026-04-20",maximum=12)
        self.assertTrue(plan["ready_for_full_source_verification"])
        self.assertFalse(plan["market_data_download_performed"])
        self.assertEqual(plan["status"],"PRESENCE_ONLY_NOT_SOURCE_CHECKSUM_VALIDATION")
        self.assertEqual(len(plan["required_monthly_pairs"]),4)

    def test_acquisition_plan_is_bounded_and_does_not_download(self):
        result=fetch.plan(self.root,SYMBOL,"2026-04")
        self.assertEqual(result["action"],"PLANNED_ONLY_NO_DOWNLOAD")
        self.assertEqual(result["timeframe"],"1m")
        self.assertEqual(result["expected_rows"],43200)
        self.assertEqual(result["spec_sha256"],fetch.FROZEN_SHA)
        for s,m in ((SYMBOL,"2026-08"),("BADUSDT","2026-04")):
            with self.assertRaises(ValueError):
                fetch.plan(self.root,s,m)

    def test_existing_pinned_minute_archive_verifies_locally(self):
        out=fetch.verify_pinned(self.root,SYMBOL,"2026-04")
        self.assertFalse(out["network_used"])
        self.assertEqual(out["rows"],43200)
        self.assertEqual(out["status"],"COMPLETE_VERIFIED_EXISTING")

    def test_single_fetch_requires_explicit_approval_and_publisher_hash(self):
        with tempfile.TemporaryDirectory(prefix="t7sonic-fetch-") as other:
            root=Path(other)
            with self.assertRaisesRegex(ValueError,"confirm-single-fetch"):
                fetch.fetch_one(root,SYMBOL,"2026-04",approved=False)
            archive=self.zips["1m"]
            published=sha256(archive).hexdigest()
            requests=[]
            def local_fetch(req,timeout):
                url=req.full_url
                requests.append(url)
                data=(published+"  BTCUSDT-1m-2026-04.zip\n").encode() \
                    if url.endswith(".CHECKSUM") else archive
                return io.BytesIO(data)
            with patch.object(fetch,"urlopen",side_effect=local_fetch), \
                 patch.object(fetch.shutil,"disk_usage",
                              return_value=SimpleNamespace(free=4*1024**3)):
                result=fetch.fetch_one(root,SYMBOL,"2026-04",approved=True)
            self.assertEqual(len(requests),2)
            self.assertTrue(result["publisher_checksum_authenticated"])
            self.assertEqual(result["status"],"ONE_MONTH_ACQUIRED_VERIFIED")
            self.assertEqual(result["rows"],43200)
            self.assertEqual(fetch.verify_pinned(root,SYMBOL,"2026-04")[
                "archive_sha256"],published)
            with self.assertRaisesRegex(ValueError,"already present"):
                fetch.fetch_one(root,SYMBOL,"2026-04",approved=True)

    def test_checksum_mismatch_download_does_not_create_source_pair(self):
        with tempfile.TemporaryDirectory(prefix="t7sonic-reject-") as other:
            root=Path(other)
            def wrong_hash(req,timeout):
                return io.BytesIO(
                    (("0"*64+"\n").encode()
                     if req.full_url.endswith(".CHECKSUM")
                     else self.zips["1m"])
                )
            with patch.object(fetch,"urlopen",side_effect=wrong_hash), \
                 patch.object(fetch.shutil,"disk_usage",
                              return_value=SimpleNamespace(free=4*1024**3)):
                with self.assertRaisesRegex(ValueError,"publisher"):
                    fetch.fetch_one(root,SYMBOL,"2026-04",approved=True)
            state=fetch.plan(root,SYMBOL,"2026-04")
            self.assertFalse(state["present_pair"])
            self.assertFalse(state["partial_pair"])

    def test_mutated_zip_and_manifest_fail_even_when_files_exist(self):
        with tempfile.TemporaryDirectory(prefix="t7sonic-tamper-") as other:
            root=Path(other)
            source,manifest=_write_source(root,"1m",self.zips["1m"])
            saved=source.read_bytes()
            try:
                source.write_bytes(saved+b"tamper")
                with self.assertRaisesRegex(ValueError,"SHA256"):
                    fetch.verify_pinned(root,SYMBOL,"2026-04")
            finally:
                source.write_bytes(saved)
            ledger=json.loads(manifest.read_text())
            ledger["spec_sha256"]="f"*64
            manifest.write_text(json.dumps(ledger))
            with self.assertRaisesRegex(ValueError,"spec_sha256"):
                fetch.verify_pinned(root,SYMBOL,"2026-04")


if __name__=="__main__":
    unittest.main()
