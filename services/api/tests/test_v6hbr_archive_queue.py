"""Data backlog must require operator fetch approval and bounded scope."""
from pathlib import Path

import pytest

from app.research.v5_archives import archive_location
from app.research.v5_archive_batch import batch_plan
from app.research.v6hbr_archive_queue import (
    MAX_NEW_MIB, MIN_FREE_MIB, acquire_planned_series, next_missing_series
)

SPEC = {
    "schema": 1,
    "symbols": ["BTCUSDT", "ETHUSDT"] + [f"T{i:02d}USDT" for i in range(28)],
    "timeframes": ["1m", "15m", "1h", "4h"],
    "history_start": "2026-01-01",
    "cutoff_exclusive": "2026-10-01",
}


def add_pair(root, market, frame, month):
    plan = batch_plan(SPEC, market, frame, month, month)[0]
    archive, manifest = archive_location(root, plan)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"present-pair-not-publisher-verified")
    manifest.write_text("{}", encoding="utf8")
    return archive, manifest


def test_first_unfinished_series_chosen_in_frozen_order(tmp_path):
    for frame in ("15m", "1h", "4h"):
        for month in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05"):
            add_pair(tmp_path, "BTCUSDT", frame, month)
    plan = next_missing_series(tmp_path, SPEC)
    assert plan["selected_symbol"] == "ETHUSDT"
    assert plan["selected_timeframe"] == "15m"
    assert plan["missing_months"] == [
        "2026-01", "2026-02", "2026-03", "2026-04", "2026-05"
    ]
    assert plan["max_new_mib"] == MAX_NEW_MIB == 64
    assert plan["min_free_mib"] == MIN_FREE_MIB == 2048
    assert plan["plan_only"] is True


def test_partial_series_fetch_needs_explicit_permission(tmp_path):
    add_pair(tmp_path, "ETHUSDT", "15m", "2026-01")
    plan = next_missing_series(tmp_path, SPEC, symbol="ETHUSDT")
    assert plan["missing_months"] == [
        "2026-02", "2026-03", "2026-04", "2026-05"
    ]
    assert plan["present_pair_months_to_verify_again"] == ["2026-01"]
    with pytest.raises(ValueError, match="confirm-fetch"):
        acquire_planned_series(tmp_path, SPEC, "f"*64, plan,
                               confirm_fetch=False)


def test_orphan_zip_manifest_never_overwritten(tmp_path):
    archive, sidecar = add_pair(tmp_path, "ETHUSDT", "15m", "2026-02")
    sidecar.unlink()
    with pytest.raises(ValueError, match="Partial archive/manifest"):
        next_missing_series(tmp_path, SPEC, symbol="ETHUSDT")


def test_symlinked_archive_does_not_count_as_valid_pair(tmp_path):
    archive, sidecar = add_pair(tmp_path, "ETHUSDT", "15m", "2026-01")
    archive.unlink()
    target = tmp_path / "frozen-source.zip"
    target.write_bytes(b"unverified")
    archive.symlink_to(target)
    with pytest.raises(ValueError, match="symlinked"):
        next_missing_series(tmp_path, SPEC, symbol="ETHUSDT")


def test_nonfrozen_or_bad_contract_rejected(tmp_path):
    with pytest.raises(ValueError, match="frozen archive contract"):
        next_missing_series(tmp_path, SPEC, symbol="NOTFROZEN")
    with pytest.raises(ValueError, match="30-symbol"):
        next_missing_series(tmp_path, {**SPEC,"symbols":["BTCUSDT"]})


def test_no_missing_pairs_distinct_from_verification(tmp_path):
    for frame in ("15m", "1h", "4h"):
        for month in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05"):
            add_pair(tmp_path, "BTCUSDT", frame, month)
    result = next_missing_series(tmp_path, SPEC, symbol="BTCUSDT")
    assert result["status"] == "NO_MISSING_SOURCE_PAIRS_IN_SELECTED_SCOPE"
    assert result["present_pair_months_examined"] == 15
    assert "full SHA" in result["limitations"][0]


def test_confirmed_fetch_passes_to_existing_strict_5_month_downloader(tmp_path,monkeypatch):
    calls = []
    def fake_fetch(root, plans, sha, **kwargs):
        calls.append((root, plans, sha, kwargs))
        return {"status": "COMPLETE", "archives_verified": len(plans)}
    monkeypatch.setattr("app.research.v6hbr_archive_queue.fetch_batch", fake_fetch)
    plan = next_missing_series(tmp_path, SPEC, symbol="ETHUSDT")
    result = acquire_planned_series(tmp_path, SPEC, "f"*64, plan,
                                    confirm_fetch=True)
    assert result["status"] == "ONE_SERIES_ACQUIRED_AND_VERIFIED"
    assert len(calls) == 1
    assert len(calls[0][1]) == 5
    assert {p["symbol"] for p in calls[0][1]} == {"ETHUSDT"}
    assert {p["timeframe"] for p in calls[0][1]} == {"15m"}
    assert calls[0][3]["max_new_bytes"] == 64*1024*1024
    assert calls[0][3]["min_free_bytes"] == 2048*1024*1024
