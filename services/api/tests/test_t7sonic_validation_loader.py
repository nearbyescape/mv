"""Validation source bridge: synthetic-only tests, no real holdout inspection."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from app.research.t7sonic_history import (
    FROZEN_SOURCE_SPEC_SHA256, HISTORICAL_FRAMES, SOURCE_INTERVALS,
)
from app.research.t7sonic_validation_loader import (
    APPROVAL_STATE, PLAN_SHA, STRATEGY_SHA, presence_only,
    validation_boundaries, verified_source_window,
)

SYMBOL = "BTCUSDT"
MONTH = "2026-06"
START_MS = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()*1000)
END_MS = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp()*1000)


def _synthetic_month(root: Path, frame: str, month: str = MONTH) -> None:
    """Full fake monthly Binance-shaped OHLCV with exact month-to-month continuity."""
    year, mm = (int(part) for part in month.split("-"))
    first = datetime(year, mm, 1, tzinfo=timezone.utc)
    following = datetime(year + (mm == 12), mm % 12 + 1, 1, tzinfo=timezone.utc)
    first_ms = int(first.timestamp()*1000)
    end_ms = int(following.timestamp()*1000)
    step = SOURCE_INTERVALS[frame]
    width = step // 60_000
    count = (end_ms - first_ms) // step
    filename = f"{SYMBOL}-{frame}-{month}.zip"
    folder = root / "archives" / SYMBOL / frame
    folder.mkdir(parents=True, exist_ok=True)
    rows = io.StringIO(newline="")
    global_offset = (first_ms - START_MS)//60_000
    for k in range(count):
        idx = global_offset + k * width
        begin = D("100") + D(idx) * D(".0005")
        finish = D("100") + D(idx + width - 1) * D(".0005")
        start_ms = first_ms + k * step
        vals = (
            start_ms, str(begin), str(finish + D(".1")),
            str(begin - D(".1")), str(finish + D(".005")),
            str(D(width)), start_ms + step - 1, "0", "1", "0", "0", "0",
        )
        rows.write(",".join(map(str, vals)) + "\n")
    binary = io.BytesIO()
    with ZipFile(binary, "w", compression=ZIP_DEFLATED) as z:
        z.writestr(filename[:-4] + ".csv", rows.getvalue())
    contents = binary.getvalue()
    (folder / filename).write_bytes(contents)
    url = (
        "https://data.binance.vision/data/futures/um/monthly/klines/"
        f"{SYMBOL}/{frame}/{filename}"
    )
    (folder / (filename + ".manifest.json")).write_text(json.dumps({
        "spec_sha256": FROZEN_SOURCE_SPEC_SHA256,
        "symbol": SYMBOL, "timeframe": frame, "month": month,
        "filename": filename, "start_ms": first_ms,
        "end_exclusive_ms": end_ms, "expected_rows": count,
        "verified_rows": count, "url": url,
        "checksum_url": url + ".CHECKSUM",
        "source_sha256": sha256(contents).hexdigest(),
    }), encoding="utf-8")

def _synthetic_approval():
    return {
        "plan_sha256": PLAN_SHA,
        "state": APPROVAL_STATE,
        "strategy_sha": STRATEGY_SHA,
        "independent_exposure_reviewed": True,
        "reserved_final_test_window": True,
        "auditor": "SYNTHETIC-TEST-NOT-REAL-AUTHORIZATION",
        "evidence_reference": "SYNTHETIC-TEST-ONLY",
    }


class ValidationLoaderTests(unittest.TestCase):
    def test_only_predeclared_utc_days_are_admitted(self):
        self.assertEqual(len(validation_boundaries("2026-06-12")), 288)
        self.assertEqual(len(validation_boundaries("2026-08-25")), 288)
        for invalid in ("2026-04-20", "2026-06-11", "2026-08-26",
                        "2026-12-01", "2026-06-13T01:00", "2026-06-99"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validation_boundaries(invalid)
        for bad in (0, 289, -1, 1.0, True):
            with self.subTest(boundaries=bad), self.assertRaises(ValueError):
                validation_boundaries("2026-06-12", maximum=bad)

    def test_presence_preflight_does_not_open_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = presence_only(root, SYMBOL, "2026-06-12")
            self.assertEqual(len(p["expected_month_pairs"]), 4)
            self.assertEqual(len(p["missing_month_pairs"]), 4)
            self.assertEqual(
                {x["month"] for x in p["expected_month_pairs"]},
                {"2026-06"},
            )
            self.assertFalse(p["market_data_opened"])
            self.assertFalse(p["integrity_verified"])
            with self.assertRaisesRegex(ValueError, "excluded"):
                presence_only(root, "FAKEUSDT", "2026-06-12")

    def test_adjacent_month_presence_requires_prior_month_warmup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for day, expected in (
                ("2026-07-01", {"2026-06", "2026-07"}),
                ("2026-08-01", {"2026-07", "2026-08"}),
                ("2026-07-15", {"2026-07"}),
            ):
                report = presence_only(root, SYMBOL, day)
                self.assertEqual(
                    {x["month"] for x in report["expected_month_pairs"]},
                    expected,
                )
                self.assertEqual(len(report["expected_month_pairs"]),
                                 len(expected) * len(HISTORICAL_FRAMES))
                self.assertEqual(report["expected_month_pairs"],
                                 report["missing_month_pairs"])
                self.assertFalse(report["market_data_opened"])

    def test_july_first_synthetic_cross_month_integrity_and_causality(self):
        # Full synthetic June+July source, never an actual exchange archive.
        with tempfile.TemporaryDirectory(prefix="t7sonic-month-seam-") as tmp:
            root = Path(tmp)
            for month in ("2026-06", "2026-07"):
                for frame in HISTORICAL_FRAMES:
                    _synthetic_month(root, frame, month)
            planned = presence_only(root, SYMBOL, "2026-07-01", maximum=3)
            self.assertFalse(planned["market_data_opened"])
            self.assertEqual(planned["missing_month_pairs"], [])
            # Three boundaries after midnight need June for higher timeframe
            # warmup and July for completed one-minute/fifteen-minute bars.
            self.assertEqual(len(planned["expected_month_pairs"]), 6)
            windows, proof = verified_source_window(
                root, SYMBOL, "2026-07-01",
                _synthetic_approval(), maximum=3,
            )
            self.assertFalse(proof["training_or_labeling_done"])
            self.assertEqual(
                {p["month"] for p in proof["source_proofs"]["1m"]},
                {"2026-06", "2026-07"}
            )
            self.assertEqual(
                {p["month"] for p in proof["source_proofs"]["4h"]},
                {"2026-06"}
            )
            for key, when_key in (
                ("first_snapshot", "first_boundary_ms"),
                ("last_snapshot", "last_boundary_ms")
            ):
                snapshot = windows[key]
                when = windows[when_key]
                self.assertEqual(snapshot["as_of_ms"], when)
                self.assertLess(snapshot["bars"]["4h"][-1]["open_ms"], when)
                for frame, bars in snapshot["bars"].items():
                    step = SOURCE_INTERVALS.get(frame, 300_000)
                    self.assertTrue(all(
                        bar["open_ms"] + step <= when for bar in bars
                    ))

    def test_any_unapproved_source_access_is_forbidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(PermissionError):
                verified_source_window(root, SYMBOL, "2026-06-12", {})
            approval = _synthetic_approval()
            for field, value in (
                ("plan_sha256", "a"*64),
                ("state", "UNRESOLVED"),
                ("strategy_sha", "b"*40),
                ("independent_exposure_reviewed", False),
                ("reserved_final_test_window", False),
                ("auditor", ""),
                ("evidence_reference", ""),
            ):
                broken = dict(approval, **{field: value})
                with self.subTest(field=field), self.assertRaises(PermissionError):
                    verified_source_window(root, SYMBOL, "2026-06-12", broken)

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="t7sonic-validation-synthetic-")
        cls.root = Path(cls.temp.name)
        for frame in HISTORICAL_FRAMES:
            _synthetic_month(cls.root, frame)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_authorized_synthetic_full_month_source_integrity_and_asof(self):
        p = presence_only(self.root, SYMBOL, "2026-06-12", maximum=3)
        self.assertEqual(p["missing_month_pairs"], [])
        out, proof = verified_source_window(
            self.root, SYMBOL, "2026-06-12",
            _synthetic_approval(), maximum=3,
        )
        self.assertTrue(proof["publisher_checksum_requires_separate_audit"])
        self.assertFalse(proof["training_or_labeling_done"])
        self.assertFalse(proof["signal_published"])
        self.assertFalse(proof["order_submitted"])
        self.assertEqual(set(proof["source_proofs"]), set(HISTORICAL_FRAMES))
        for snap, when in (
            (out["first_snapshot"], out["first_boundary_ms"]),
            (out["last_snapshot"], out["last_boundary_ms"]),
        ):
            self.assertEqual(set(snap["bars"]), {"1m", "5m", "15m", "1h", "4h"})
            self.assertEqual(snap["as_of_ms"], when)
            for frame, bars in snap["bars"].items():
                self.assertEqual(len(bars), 64)
                self.assertLessEqual(
                    bars[-1]["open_ms"] + SOURCE_INTERVALS.get(frame, 300_000),
                    when,
                )

    def test_tampered_synthetic_archive_rejected(self):
        p = self.root / "archives" / SYMBOL / "1m" / f"{SYMBOL}-1m-{MONTH}.zip"
        old = p.read_bytes()
        try:
            p.write_bytes(old + b"bad")
            with self.assertRaisesRegex(ValueError, "checksum"):
                verified_source_window(
                    self.root, SYMBOL, "2026-06-12",
                    _synthetic_approval(), maximum=3,
                )
        finally:
            p.write_bytes(old)


if __name__ == "__main__":
    unittest.main()
