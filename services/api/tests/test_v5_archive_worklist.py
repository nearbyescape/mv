"""V5 bounded archive worklist: no download, no inferred listing and no silent repair."""
from __future__ import annotations

from hashlib import sha256
import json
import sys

import pytest

from app.research import v5_archive_worklist as worklist
from app.research.v5_archives import archive_location, archive_plan, load_spec


def _plan(tmp_path, *, symbols=("BTCUSDT", "ETHUSDT"), stage="foundation",
          phase="pilot", max_jobs=3, max_months_per_job=6):
    spec, fingerprint = load_spec()
    return worklist.make_worklist(
        tmp_path, spec, fingerprint,
        symbols=list(symbols), stage=stage, phase=phase,
        max_jobs=max_jobs, max_months_per_job=max_months_per_job,
    )


def _pin(tmp_path, *, symbol="BTCUSDT", frame="1h", month="2026-06",
         mutate=None):
    spec, fingerprint = load_spec()
    plan = archive_plan(spec, symbol, frame, month)
    archive, sidecar = archive_location(tmp_path, plan)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"fake offline archive marker: not verified")
    row = {
        **plan,
        "spec_sha256": fingerprint,
        "source_sha256": sha256(archive.read_bytes()).hexdigest(),
        "verified_rows": plan["expected_rows"],
    }
    if mutate:
        mutate(row)
    sidecar.write_text(json.dumps(row), encoding="utf-8")
    return archive, sidecar


def test_default_queue_is_bounded_and_symbol_major(tmp_path):
    result = _plan(tmp_path)
    assert result["status"] == "INCOMPLETE"
    assert result["expected_archive_cells"] == 2 * 2 * 6
    assert result["counts"]["MISSING"] == 24
    assert [(j["symbol"], j["timeframe"], j["months"]) for j in result["proposed_jobs"]] == [
        ("BTCUSDT", "1h", [f"2026-{i:02d}" for i in range(1, 7)]),
        ("BTCUSDT", "4h", [f"2026-{i:02d}" for i in range(1, 7)]),
        ("ETHUSDT", "1h", [f"2026-{i:02d}" for i in range(1, 7)]),
    ]
    assert all(j["status"] == "REQUIRES_EXPLICIT_OPERATOR_REVIEW"
               for j in result["proposed_jobs"])
    assert all("--confirm-fetch" in j["fetch_command"]
               for j in result["proposed_jobs"])
    assert all("--max-new-mib 64" in j["fetch_command"]
               for j in result["proposed_jobs"])
    assert not list(tmp_path.iterdir())  # never creates an archive or ledger


def test_planner_never_labels_present_manifest_as_verified(tmp_path):
    _pin(tmp_path, symbol="BTCUSDT", frame="1h", month="2026-01")
    report = _plan(tmp_path, symbols=("BTCUSDT",), max_jobs=2)
    assert report["counts"]["PRESENT_UNVERIFIED"] == 1
    assert report["counts"]["VERIFIED"] == 0
    assert report["proposed_jobs"][0]["months"] == [
        f"2026-{i:02d}" for i in range(2, 7)
    ]
    assert report["proposed_jobs"][1]["timeframe"] == "4h"


def test_missing_gaps_are_not_downloaded_as_full_month_ranges(tmp_path):
    _pin(tmp_path, frame="1h", month="2026-06")
    result = _plan(tmp_path, symbols=("BTCUSDT",), phase="validation")
    assert result["months"] == ["2026-06", "2026-07"]
    assert result["proposed_jobs"][0]["timeframe"] == "1h"
    assert result["proposed_jobs"][0]["months"] == ["2026-07"]
    assert result["proposed_jobs"][1]["timeframe"] == "4h"
    assert result["proposed_jobs"][1]["months"] == ["2026-06", "2026-07"]


def test_404_ledger_requires_review_and_does_not_infer_prelisting(tmp_path):
    spec, fingerprint = load_spec()
    folder = tmp_path / "batch-ledgers"
    folder.mkdir()
    entry = {
        "status": "SOURCE_HTTP_404_REQUIRES_REVIEW",
        "spec_sha256": fingerprint,
        "symbol": "ETHUSDT", "timeframe": "1h", "month": "2026-01",
    }
    (folder / "ETHUSDT-1h-2026-01-to-2026-06.jsonl").write_text(
        json.dumps(entry) + "\n", encoding="utf-8"
    )
    report = _plan(tmp_path)
    assert report["status"] == "REVIEW_REQUIRED"
    assert report["blocking_issue_count"] == 1
    assert report["proposed_jobs"] == []
    assert report["counts"]["REVIEW_REQUIRED"] == 1
    assert report["blocking_issues"][0]["reason"] == "PREVIOUS_PUBLISHER_404_NOT_INCEPTION_PROOF"


def test_wrong_spec_manifest_blocks_worklist_instead_of_overwriting(tmp_path):
    _pin(tmp_path, mutate=lambda record: record.update(spec_sha256="0" * 64))
    result = _plan(tmp_path)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["counts"]["REVIEW_REQUIRED"] == 1
    assert result["proposed_jobs"] == []
    assert "spec" in result["blocking_issues"][0]["reason"].lower()


def test_corrupt_jsonl_ledger_fails_closed(tmp_path):
    folder = tmp_path / "batch-ledgers"
    folder.mkdir()
    (folder / "bad.jsonl").write_text("{not valid json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Malformed audit ledger"):
        _plan(tmp_path)


def test_stage_and_holdout_scope_are_explicit_and_only_inventory(tmp_path):
    report = _plan(tmp_path, symbols=("BTCUSDT",), stage="trigger", phase="holdout")
    assert report["months"] == ["2026-08", "2026-09"]
    assert report["timeframes"] == ["15m"]
    assert report["expected_archive_cells"] == 2
    assert report["proposed_jobs"][0]["months"] == ["2026-08", "2026-09"]
    assert "evaluate" in report["warning"]


def test_single_job_size_is_capped_even_for_full_scope(tmp_path):
    result = _plan(
        tmp_path, symbols=("BTCUSDT",), stage="execution", phase="full",
        max_jobs=3, max_months_per_job=3,
    )
    assert len(result["proposed_jobs"]) == 3
    assert [j["months"] for j in result["proposed_jobs"]] == [
        ["2026-01", "2026-02", "2026-03"],
        ["2026-04", "2026-05", "2026-06"],
        ["2026-07", "2026-08", "2026-09"],
    ]


def test_invalid_scope_limits_and_unlisted_markets_fail(tmp_path):
    spec, fingerprint = load_spec()
    params = {
        "symbols": ["BTCUSDT"], "stage": "foundation", "phase": "pilot",
    }
    for overrides in (
        {"max_jobs": 0},
        {"max_jobs": 4},
        {"max_months_per_job": 7},
        {"max_new_mib": 257},
        {"symbols": ["BTCUSDT", "BTCUSDT"]},
        {"symbols": ["NOTREALUSDT"]},
        {"phase": "unknown"},
    ):
        with pytest.raises(ValueError):
            worklist.make_worklist(tmp_path, spec, fingerprint, **(params | overrides))
    with pytest.raises(FileNotFoundError):
        worklist.make_worklist(tmp_path / "absent", spec, fingerprint, **params)


def test_cli_is_read_only_and_json_is_machine_parseable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_worklist", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--stage", "foundation", "--phase", "pilot",
        "--max-jobs", "1",
    ])
    worklist.main()
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "INCOMPLETE"
    assert len(data["proposed_jobs"]) == 1
    assert data["proposed_jobs"][0]["timeframe"] == "1h"
    assert list(tmp_path.iterdir()) == []
