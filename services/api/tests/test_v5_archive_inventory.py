"""Offline archive inventory: do not mistake pinned metadata for verified prices."""
from __future__ import annotations

import json
import sys

import pytest

from app.research import v5_archive_inventory as inv
from app.research.v5_archives import archive_location, archive_plan, load_spec


def _scope(tmp_path, *, months=("2026-04",), deep=False, symbols=("BTCUSDT",)):
    spec, digest = load_spec()
    return inv.inventory(
        tmp_path, spec, digest,
        symbols=list(symbols), timeframes=["1h"],
        months=list(months), deep_verify=deep,
        include_cells=True,
    )


def _pin(tmp_path, *, month="2026-04", source_sha="a" * 64):
    spec, digest = load_spec()
    plan = archive_plan(spec, "BTCUSDT", "1h", month)
    archive, sidecar = archive_location(tmp_path, plan)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"not-valid-price-data")
    record = {
        **plan, "source_sha256": source_sha,
        "spec_sha256": digest, "verified_rows": plan["expected_rows"],
    }
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    return archive, sidecar, record


def test_frozen_full_universe_has_1080_expected_archive_cells(tmp_path):
    spec, sha = load_spec()
    months = inv.months_for_spec(spec)
    assert months == [f"2026-{i:02d}" for i in range(1, 10)]
    result = inv.inventory(
        tmp_path, spec, sha,
        symbols=spec["symbols"], timeframes=spec["timeframes"], months=months,
    )
    assert result["status"] == "INCOMPLETE"
    assert result["expected_archive_cells"] == 30 * 4 * 9 == 1080
    assert result["counts"]["MISSING"] == 1080
    assert len(result["actionable_examples"]) == inv.MAX_EXAMPLES
    assert all(not row["coverage_complete"] for row in result["by_symbol"].values())
    assert list(tmp_path.iterdir()) == []  # inventory never creates files


def test_missing_and_orphan_evidence_is_fail_closed(tmp_path):
    assert _scope(tmp_path)["cells"][0]["status"] == "MISSING"
    spec, _ = load_spec()
    plan = archive_plan(spec, "BTCUSDT", "1h", "2026-04")
    archive, sidecar = archive_location(tmp_path, plan)
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"orphan")
    report = _scope(tmp_path)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["cells"][0]["reason"] == "ORPHAN_ZIP"
    archive.unlink()
    sidecar.write_text("{}", encoding="utf-8")
    assert _scope(tmp_path)["cells"][0]["reason"] == "ORPHAN_MANIFEST"


def test_pinned_manifest_is_not_verified_price_data(tmp_path):
    _, _, record = _pin(tmp_path)
    report = _scope(tmp_path)
    assert report["counts"]["PRESENT_UNVERIFIED"] == 1
    assert report["counts"]["VERIFIED"] == 0
    assert report["status"] == "INCOMPLETE"
    assert not report["by_symbol"]["BTCUSDT"]["coverage_complete"]
    assert report["cells"][0]["source_sha256"] == record["source_sha256"]


def test_wrong_spec_or_price_lineage_requires_review(tmp_path):
    _, sidecar, record = _pin(tmp_path)
    record["spec_sha256"] = "b" * 64
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    assert _scope(tmp_path)["cells"][0]["status"] == "REVIEW_REQUIRED"
    record["spec_sha256"] = load_spec()[1]
    record["verified_rows"] -= 1
    sidecar.write_text(json.dumps(record), encoding="utf-8")
    assert "candle count" in _scope(tmp_path)["cells"][0]["reason"]
    sidecar.write_text("corrupt {", encoding="utf-8")
    assert _scope(tmp_path)["cells"][0]["status"] == "REVIEW_REQUIRED"


def test_deep_verify_uses_full_archive_validator_and_rejects_corruption(tmp_path):
    _pin(tmp_path)
    # Mocking demonstrates gate wiring; this is not a real market-data test.
    original = inv.verify_existing
    calls = []
    def trusted_checker(root, plan, sha):
        calls.append((plan["symbol"], plan["month"]))
        return {"verified_rows": plan["expected_rows"]}
    try:
        inv.verify_existing = trusted_checker
        assert _scope(tmp_path, deep=True)["status"] == "VERIFIED_COMPLETE"
        assert calls == [("BTCUSDT", "2026-04")]
    finally:
        inv.verify_existing = original
    # Actual full validator rejects deliberately corrupt bytes and the
    # inventory reports REVIEW_REQUIRED rather than falsely claiming complete.
    result = _scope(tmp_path, deep=True)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["counts"]["VERIFIED"] == 0
    assert result["cells"][0]["status"] == "REVIEW_REQUIRED"


def test_deep_verify_is_bounded_and_nonlisted_symbols_rejected(tmp_path):
    spec, sha = load_spec()
    with pytest.raises(ValueError, match="one symbol"):
        inv.inventory(
            tmp_path, spec, sha,
            symbols=["BTCUSDT", "ETHUSDT"], timeframes=["1h"],
            months=["2026-04"], deep_verify=True,
        )
    with pytest.raises(ValueError, match="three months"):
        inv.inventory(
            tmp_path, spec, sha,
            symbols=["BTCUSDT"], timeframes=["1h"],
            months=["2026-01", "2026-02", "2026-03", "2026-04"],
            deep_verify=True,
        )
    with pytest.raises(ValueError, match="unapproved"):
        inv.inventory(
            tmp_path, spec, sha,
            symbols=["NOTLISTEDUSDT"], timeframes=["1h"],
            months=["2026-04"],
        )
    with pytest.raises(ValueError, match="frozen"):
        inv.months_for_spec(spec, "2026-08", "2026-10")


def test_cli_read_only_and_complete_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_inventory", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--timeframe", "4h",
        "--start-month", "2026-04", "--end-month", "2026-04",
    ])
    inv.main()
    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["MISSING"] == 1
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_inventory", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--timeframe", "4h",
        "--start-month", "2026-04", "--end-month", "2026-04",
        "--require-complete",
    ])
    with pytest.raises(SystemExit) as exc:
        inv.main()
    assert exc.value.code == 3
