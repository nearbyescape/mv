"""Minute-vs-quarter-hour OHLCV source checks with small pinned fixtures.

Short fixture intervals intentionally exercise exactly the same streaming
archive verification contracts as real full-month Binance archives.
"""
from __future__ import annotations

from hashlib import sha256
import json
import sys
import zipfile

import pytest

from app.research import v5_archive_audit as audit
from app.research.v5_archives import archive_location, archive_plan, load_spec


def _sources(root, *, minutes=60, mismatch_all=False, mismatch_at=None):
    assert minutes > 0 and minutes % 15 == 0
    spec, fingerprint = load_spec()
    plans = {}
    for frame, count in (("1m", minutes), ("15m", minutes // 15)):
        source = archive_plan(spec, "BTCUSDT", frame, "2026-04")
        # A small *single-month portion* avoids generating 43,200 fixture
        # minute bars while preserving strict timestamp and row verification.
        source["expected_rows"] = count
        source["end_exclusive_ms"] = source["start_ms"] + minutes * 60_000
        path, sidecar = archive_location(root, source)
        path.parent.mkdir(parents=True, exist_ok=True)
        step = audit.FRAME_MS[frame]
        rows = []
        for i in range(count):
            opened = source["start_ms"] + i * step
            disagree = frame == "15m" and (
                mismatch_all or (mismatch_at is not None and i == mismatch_at)
            )
            high = "102" if disagree else "101"
            volume = "30" if frame == "15m" else "2"
            rows.append(",".join((
                str(opened), "100", high, "99", "100", volume,
                str(opened + step - 1), "0", "0", "0", "0", "0"
            )))
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zipfile_out:
            zipfile_out.writestr(source["filename"][:-4] + ".csv", "\n".join(rows) + "\n")
        sidecar.write_text(json.dumps({
            **source,
            "source_sha256": sha256(path.read_bytes()).hexdigest(),
            "spec_sha256": fingerprint,
            "verified_rows": source["expected_rows"],
        }), encoding="utf-8")
        plans[frame] = source
    return [plans["1m"]], [plans["15m"]], fingerprint


def test_minute_15m_aggregation_exact_match_with_source_hashes(tmp_path):
    minute, fifteen, fingerprint = _sources(tmp_path)
    result = audit.audit_minute_pair(tmp_path, minute, fifteen, fingerprint)
    assert result["disposition"] == "PASS"
    assert result["minute"]["rows"] == 60
    assert result["fifteen_minute"]["rows"] == 4
    assert result["comparison"]["native_15m_rows"] == 4
    assert result["comparison"]["mismatched_native_15m_rows"] == 0
    assert result["comparison"]["field_mismatch_counts"] == {}
    assert len(result["minute"]["canonical_series_sha256"]) == 64
    assert result == audit.audit_minute_pair(tmp_path, minute, fifteen, fingerprint)


def test_detect_and_report_native_15m_price_disagreement(tmp_path):
    minute, fifteen, fingerprint = _sources(tmp_path, mismatch_at=2)
    result = audit.audit_minute_pair(tmp_path, minute, fifteen, fingerprint)
    comparison = result["comparison"]
    assert result["disposition"] == "REVIEW_REQUIRED"
    assert comparison["status"] == "SOURCE_DISAGREEMENT_REVIEW_REQUIRED"
    assert comparison["mismatched_native_15m_rows"] == 1
    assert comparison["field_mismatch_counts"] == {"high": 1}
    assert comparison["samples"][0]["fields"]["high"] == {
        "from_1m": "101", "native_15m": "102"
    }


def test_discrepancy_samples_never_exceed_cap(tmp_path):
    minute, fifteen, fingerprint = _sources(tmp_path, minutes=150, mismatch_all=True)
    comparison = audit.audit_minutes_vs_fifteen(tmp_path, minute, fifteen, fingerprint)
    assert comparison["mismatched_native_15m_rows"] == 10
    assert comparison["field_mismatch_counts"] == {"high": 10}
    assert len(comparison["samples"]) == audit.MAX_SAMPLES == 8


def test_missing_source_or_modified_zip_fails_before_comparison(tmp_path):
    minute, fifteen, fingerprint = _sources(tmp_path)
    archive, sidecar = archive_location(tmp_path, minute[0])
    sidecar.unlink()
    with pytest.raises(FileNotFoundError):
        audit.audit_minute_pair(tmp_path, minute, fifteen, fingerprint)
    _, _, fingerprint = _sources(tmp_path)
    archive.write_bytes(b"modified archive")
    with pytest.raises(ValueError, match="changed since acquisition"):
        audit.audit_minute_pair(tmp_path, minute, fifteen, fingerprint)


def test_mismatched_timeframe_scope_rejected(tmp_path):
    minute, fifteen, fingerprint = _sources(tmp_path)
    with pytest.raises(ValueError, match="matching scope"):
        audit.audit_minutes_vs_fifteen(tmp_path, fifteen, minute, fingerprint)
    with pytest.raises(ValueError, match="matching scope"):
        audit.audit_minutes_vs_fifteen(tmp_path, [], fifteen, fingerprint)


def test_offline_cli_returns_three_on_minute_source_discrepancy(
    tmp_path, monkeypatch, capsys
):
    minute, fifteen, fingerprint = _sources(tmp_path, mismatch_at=1)
    def fake_batch(spec, symbol, timeframe, first, last):
        return minute if timeframe == "1m" else fifteen
    monkeypatch.setattr(audit, "batch_plan", fake_batch)
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_audit", "reconcile-1m-15m", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--start-month", "2026-04",
        "--end-month", "2026-04",
    ])
    with pytest.raises(SystemExit) as exited:
        audit.main()
    assert exited.value.code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["comparison"]["mismatched_native_15m_rows"] == 1
