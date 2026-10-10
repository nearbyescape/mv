"""Presence inventory is a preflight only; never misstate coverage as integrity."""
from pathlib import Path

import pytest

from app.research.v6hbr_directional_preflight import (
    EXPECTED, FRAMES, MONTHS, archive_inventory
)
from app.research.v5_archives import archive_plan, archive_location


def spec():
    return {
        "symbols": ["BTCUSDT"] + [f"T{i:02d}USDT" for i in range(29)],
        "timeframes": ["1m", "15m", "1h", "4h"],
        "history_start": "2026-01-01",
        "cutoff_exclusive": "2026-10-01",
    }


def pair(root, data, symbol, frame="15m", month="2026-01"):
    plan = archive_plan(data, symbol, frame, month)
    archive, manifest = archive_location(root, plan)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"synthetic-not-valid-archive")
    manifest.write_text("{}", encoding="utf-8")
    return archive, manifest


def test_empty_archive_root_never_claims_all_30(tmp_path):
    result = archive_inventory(tmp_path, spec())
    assert result["required_archive_manifest_pairs"] == EXPECTED == 450
    assert result["present_archive_manifest_pairs"] == 0
    assert result["missing_archive_manifest_pairs"] == EXPECTED
    assert result["fully_present_symbol_count"] == 0
    assert result["full_30_symbol_source_coverage"] is False
    assert len(result["missing_examples_first_40"]) == 40


def test_one_symbol_has_only_15_source_pairs_not_thirty(tmp_path):
    data = spec()
    for frame in FRAMES:
        for month in MONTHS:
            pair(tmp_path, data, "BTCUSDT", frame, month)
    result = archive_inventory(tmp_path, data)
    assert result["present_archive_manifest_pairs"] == 15
    assert result["fully_present_symbol_count"] == 1
    assert result["by_symbol"]["BTCUSDT"]["ready_for_integrity_audit"]
    assert not result["by_symbol"]["T00USDT"]["ready_for_integrity_audit"]


def test_presence_does_not_claim_sha_validity_even_when_every_file_exists(tmp_path):
    data = spec()
    for symbol in data["symbols"]:
        for frame in FRAMES:
            for month in MONTHS:
                pair(tmp_path, data, symbol, frame, month)
    result = archive_inventory(tmp_path, data)
    assert result["present_archive_manifest_pairs"] == 450
    assert result["full_30_symbol_source_coverage"]
    assert "NEEDS_SHA_CONTINUITY_AUDIT" in result["status"]
    assert "not SHA validation" in result["note"]
    # All synthetic file contents are deliberately bad: their presence alone
    # must never be mistaken for a passing publisher checksum or OHLC audit.


def test_missing_manifest_or_symlinked_zip_is_not_counted(tmp_path):
    data = spec()
    file, manifest = pair(tmp_path, data, "BTCUSDT")
    manifest.unlink()
    result = archive_inventory(tmp_path, data)
    assert result["present_archive_manifest_pairs"] == 0
    manifest.write_text("{}", encoding="utf-8")
    file.unlink()
    original = tmp_path / "external.zip"
    original.write_bytes(b"payload")
    file.symlink_to(original)
    assert archive_inventory(tmp_path, data)["present_archive_manifest_pairs"] == 0


def test_wrong_universe_and_nonexistent_root_rejected(tmp_path):
    data = spec()
    with pytest.raises(ValueError, match="30-symbol"):
        archive_inventory(tmp_path, {"symbols": data["symbols"][:29]})
    with pytest.raises(ValueError, match="absolute"):
        archive_inventory(Path("/nonexistent-v6hbr-archive-dir"), data)
