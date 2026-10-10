"""Bounded multi-month V5 acquisition: isolated offline/publisher-failure tests."""
from __future__ import annotations

import json
import sys

import httpx
import pytest

from app.research import v5_archive_batch as batch
from app.research.v5_archives import archive_location, load_spec


def _plans(first="2026-04", last="2026-06"):
    spec, sha = load_spec()
    return batch.batch_plan(spec, "BTCUSDT", "1h", first, last), sha


def test_bounded_calendar_month_enumeration():
    assert batch.months_inclusive("2026-04", "2026-06") == [
        "2026-04", "2026-05", "2026-06"
    ]
    assert batch.months_inclusive("2026-09", "2026-09") == ["2026-09"]
    with pytest.raises(ValueError):
        batch.months_inclusive("2026-06", "2026-04")
    with pytest.raises(ValueError):
        batch.months_inclusive("2026-1", "2026-02")
    with pytest.raises(ValueError, match="six-month"):
        batch.months_inclusive("2026-01", "2026-07")


def test_unlisted_symbols_and_outside_period_fail_before_download():
    spec, _ = load_spec()
    with pytest.raises(ValueError):
        batch.batch_plan(spec, "HBARUSDT", "1h", "2026-04", "2026-06")
    with pytest.raises(ValueError):
        batch.batch_plan(spec, "BTCUSDT", "1h", "2026-09", "2026-10")


def test_plan_is_offline_and_does_not_create_directory(tmp_path, monkeypatch, capsys):
    root = tmp_path / "unused-research"
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_batch", "plan", "--root", str(root),
        "--symbol", "BTCUSDT", "--timeframe", "1h",
        "--start-month", "2026-04", "--end-month", "2026-06",
    ])
    batch.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "PLANNED_ONLY"
    assert [p["month"] for p in payload["archives"]] == [
        "2026-04", "2026-05", "2026-06",
    ]
    assert not root.exists()


def test_fetch_refuses_without_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_batch", "fetch", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--timeframe", "1h",
        "--start-month", "2026-04", "--end-month", "2026-05",
    ])
    with pytest.raises(SystemExit) as exc:
        batch.main()
    assert exc.value.code == 2


def test_verify_missing_archive_fails_without_writes(tmp_path):
    plans, sha = _plans()
    with pytest.raises(FileNotFoundError):
        batch.verify_batch(tmp_path, plans, sha)
    assert list(tmp_path.iterdir()) == []


def test_serial_acquisition_resumes_existing_archives_and_writes_ledger(tmp_path, monkeypatch):
    plans, sha = _plans()
    calls = []
    pauses = []

    def fake_acquire(root, plan, fingerprint, *, max_archive_bytes):
        calls.append((plan["month"], max_archive_bytes))
        archive, sidecar = archive_location(root, plan)
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            archive.write_bytes(b"placeholder for mocked archive")
        return {
            "source_sha256": "a" * 64,
            "verified_rows": plan["expected_rows"],
            "compressed_bytes": 1000,
        }

    monkeypatch.setattr(batch, "acquire_one", fake_acquire)
    monkeypatch.setattr(batch.time, "sleep", lambda n: pauses.append(n))
    first = batch.fetch_batch(
        tmp_path, plans, sha,
        max_new_bytes=4 * batch.MIB,
        min_free_bytes=batch.MIB,
        delay_seconds=0.5,
    )
    assert first["archives_verified"] == 3
    assert first["new_compressed_bytes"] == 3000
    assert [p["status"] for p in first["results"]] == ["ACQUIRED_AND_VERIFIED"] * 3
    assert pauses == [0.5, 0.5]
    restarted = batch.fetch_batch(
        tmp_path, plans, sha,
        max_new_bytes=4 * batch.MIB,
        min_free_bytes=batch.MIB,
        delay_seconds=0.5,
    )
    assert restarted["new_compressed_bytes"] == 0
    assert [p["status"] for p in restarted["results"]] == ["VERIFIED_EXISTING"] * 3
    ledger = (tmp_path / "batch-ledgers" / "BTCUSDT-1h-2026-04-to-2026-06.jsonl")
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert [e["status"] for e in events] == (
        ["ACQUIRED_AND_VERIFIED"] * 3 + ["VERIFIED_EXISTING"] * 3
    )
    assert len(calls) == 6


def test_missing_publisher_archive_logged_then_halts(tmp_path, monkeypatch):
    plans, sha = _plans()
    request = httpx.Request("GET", plans[0]["checksum_url"])
    response = httpx.Response(404, request=request)

    def absent(*_a, **_kw):
        raise httpx.HTTPStatusError(
            "Not Found", request=request, response=response
        )

    monkeypatch.setattr(batch, "acquire_one", absent)
    with pytest.raises(httpx.HTTPStatusError):
        batch.fetch_batch(
            tmp_path, plans, sha,
            max_new_bytes=4 * batch.MIB,
            min_free_bytes=batch.MIB,
            delay_seconds=0.5,
        )
    ledger = tmp_path / "batch-ledgers" / "BTCUSDT-1h-2026-04-to-2026-06.jsonl"
    entries = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(entries) == 1
    assert entries[0]["status"] == "SOURCE_HTTP_404_REQUIRES_REVIEW"
    assert entries[0]["month"] == "2026-04"
    assert not list((tmp_path / "archives").rglob("*.zip")) if (tmp_path / "archives").exists() else True


def test_batch_budget_halts_before_starting_second_new_archive(tmp_path, monkeypatch):
    plans, sha = _plans("2026-04", "2026-05")
    calls = []

    def expensive(root, plan, fingerprint, *, max_archive_bytes):
        calls.append(plan["month"])
        archive, sidecar = archive_location(root, plan)
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(b"research fixture")
        return {
            "source_sha256": "b" * 64,
            "verified_rows": plan["expected_rows"],
            "compressed_bytes": 1 * batch.MIB,
        }

    monkeypatch.setattr(batch, "acquire_one", expensive)
    monkeypatch.setattr(batch.time, "sleep", lambda *_: None)
    with pytest.raises(ValueError, match="budget exhausted"):
        batch.fetch_batch(
            tmp_path, plans, sha,
            max_new_bytes=1 * batch.MIB,
            min_free_bytes=batch.MIB,
            delay_seconds=0.5,
        )
    assert calls == ["2026-04"]
    ledger = tmp_path / "batch-ledgers" / "BTCUSDT-1h-2026-04-to-2026-05.jsonl"
    events = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert events[0]["status"] == "ACQUIRED_AND_VERIFIED"
    assert events[1]["status"] == "ACQUISITION_OR_VERIFICATION_FAILURE"


def test_invalid_limits_fail_before_network(tmp_path):
    plans, sha = _plans()
    with pytest.raises(ValueError):
        batch.fetch_batch(
            tmp_path, plans, sha, max_new_bytes=0,
            min_free_bytes=batch.MIB, delay_seconds=0.5,
        )
    with pytest.raises(ValueError):
        batch.fetch_batch(
            tmp_path, plans, sha, max_new_bytes=257 * batch.MIB,
            min_free_bytes=batch.MIB, delay_seconds=0.5,
        )
    with pytest.raises(ValueError):
        batch.fetch_batch(
            tmp_path, plans, sha, max_new_bytes=batch.MIB,
            min_free_bytes=batch.MIB, delay_seconds=0,
        )
