"""V5 archive pilot: checksum, month continuity, scope, and fail-closed tests."""
from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import zipfile

import pytest

from app.research.v5_archives import (
    _checksum_text,
    acquire_one,
    archive_location,
    archive_plan,
    digest,
    load_spec,
    valid_research_root,
    validate_archive,
    verify_existing,
)


def _plan():
    spec, spec_hash = load_spec()
    return archive_plan(spec, "BTCUSDT", "1h", "2026-04"), spec_hash


def _zip_month(path: Path, plan: dict, *, short_by=0, gap_at=None):
    step = 3_600_000
    values = []
    for index in range(plan["expected_rows"] - short_by):
        opening = plan["start_ms"] + index * step
        if gap_at is not None and index >= gap_at:
            opening += step
        values.append(",".join([
            str(opening), "100", "101", "99", "100", "7",
            str(opening + step - 1), "0", "0", "0", "0", "0",
        ]))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTCUSDT-1h-2026-04.csv", "\n".join(values) + "\n")


def test_spec_is_exact_current_30_coin_universe():
    spec, fingerprint = load_spec()
    assert len(spec["symbols"]) == 30
    assert "HBARUSDT" not in spec["symbols"]
    assert {"BTCUSDT", "ETHUSDT", "ASTERUSDT"} <= set(spec["symbols"])
    assert list(spec["timeframes"]) == ["1m", "15m", "1h", "4h"]
    assert len(fingerprint) == 64


def test_plan_rejects_any_unregistered_symbol_timeframe_and_month():
    spec, _ = load_spec()
    plan = archive_plan(spec, "BTCUSDT", "1h", "2026-04")
    assert plan["expected_rows"] == 30 * 24
    assert plan["end_exclusive_ms"] - plan["start_ms"] == 30 * 24 * 3_600_000
    with pytest.raises(ValueError):
        archive_plan(spec, "HBARUSDT", "1h", "2026-04")
    with pytest.raises(ValueError):
        archive_plan(spec, "BTCUSDT", "1s", "2026-04")
    with pytest.raises(ValueError):
        archive_plan(spec, "BTCUSDT", "1h", "2025-12")
    with pytest.raises(ValueError):
        archive_plan(spec, "BTCUSDT", "1h", "2026-10")
    with pytest.raises(ValueError):
        archive_plan(spec, "BTCUSDT", "1h", "2026-4")


def test_month_boundary_for_leap_year_and_last_eligible_month():
    spec, _ = load_spec()
    sep = archive_plan(spec, "ETHUSDT", "15m", "2026-09")
    assert sep["expected_rows"] == 30 * 24 * 4
    jan = archive_plan(spec, "BTCUSDT", "1m", "2026-01")
    assert jan["expected_rows"] == 31 * 24 * 60


def test_completely_contiguous_archive_verifies_against_published_sha(tmp_path):
    plan, _ = _plan()
    archive = tmp_path / plan["filename"]
    _zip_month(archive, plan)
    assert validate_archive(archive, plan, digest(archive)) == 720


def test_incomplete_month_is_not_silently_accepted(tmp_path):
    plan, _ = _plan()
    archive = tmp_path / plan["filename"]
    _zip_month(archive, plan, short_by=1)
    with pytest.raises(ValueError, match="Incomplete month"):
        validate_archive(archive, plan, digest(archive))


def test_gap_and_duplicate_time_fail_closed(tmp_path):
    plan, _ = _plan()
    archive = tmp_path / plan["filename"]
    _zip_month(archive, plan, gap_at=10)
    with pytest.raises(ValueError, match="Missing, reordered or duplicated"):
        validate_archive(archive, plan, digest(archive))


def test_wrong_checksum_rejected_before_candle_inspection(tmp_path):
    plan, _ = _plan()
    archive = tmp_path / plan["filename"]
    _zip_month(archive, plan)
    with pytest.raises(ValueError, match="SHA-256"):
        validate_archive(archive, plan, "a" * 64)


def test_pinned_manifest_revalidates_and_rejects_changed_spec(tmp_path):
    plan, spec_hash = _plan()
    archive, sidecar = archive_location(tmp_path, plan)
    archive.parent.mkdir(parents=True)
    _zip_month(archive, plan)
    evidence = {
        **plan,
        "spec_sha256": spec_hash,
        "source_sha256": digest(archive),
        "verified_rows": 720,
    }
    sidecar.write_text(json.dumps(evidence), encoding="utf-8")
    assert verify_existing(tmp_path, plan, spec_hash)["verified_rows"] == 720
    with pytest.raises(ValueError, match="different research specification"):
        verify_existing(tmp_path, plan, "b" * 64)
    evidence["verified_rows"] = 719
    sidecar.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(ValueError, match="row-count evidence"):
        verify_existing(tmp_path, plan, spec_hash)


def test_checksum_text_and_root_path_validation():
    assert _checksum_text("A" * 64 + "  BTCUSDT.zip\n") == "a" * 64
    with pytest.raises(ValueError):
        _checksum_text("garbage")
    with pytest.raises(ValueError):
        valid_research_root("/")
    with pytest.raises(ValueError):
        valid_research_root("relative/path")
    with pytest.raises(ValueError):
        valid_research_root(str(Path(__file__).resolve().parents[3]))


def test_zip_with_extra_csv_members_is_rejected(tmp_path):
    plan, _ = _plan()
    archive = tmp_path / plan["filename"]
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("a.csv", "1\n")
        zipped.writestr("b.csv", "1\n")
    with pytest.raises(ValueError, match="exactly one CSV"):
        validate_archive(archive, plan, digest(archive))


def test_download_is_one_archive_idempotent_and_publisher_correction_fails(tmp_path, monkeypatch):
    from app.research import v5_archives as impl
    plan, spec_hash = _plan()
    prepared = tmp_path / "origin.zip"
    _zip_month(prepared, plan)
    zip_bytes = prepared.read_bytes()
    published = sha256(zip_bytes).hexdigest()
    history = []

    class FakeResponse:
        def __init__(self, content):
            self.content = content
            self.text = content.decode("utf-8", errors="replace")

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size):
            yield self.content

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class FakeClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def get(self, url):
            history.append(("get", url))
            return FakeResponse((published + "  archive.zip\n").encode())

        def stream(self, method, url):
            history.append(("stream", url))
            return FakeResponse(zip_bytes)

    monkeypatch.setattr(impl.httpx, "Client", FakeClient)
    root = tmp_path / "research"
    # Byte cap is enforced while streaming and never publishes partial ZIPs.
    with pytest.raises(ValueError, match="safety limit"):
        acquire_one(root, plan, spec_hash, max_archive_bytes=16)
    stored, sidecar = archive_location(root, plan)
    assert not stored.exists() and not sidecar.exists()
    first = acquire_one(root, plan, spec_hash)
    assert first["verified_rows"] == 720
    assert first["source_sha256"] == published
    assert [kind for kind, _ in history] == ["get", "stream", "get", "stream"]
    again = acquire_one(root, plan, spec_hash)
    assert again == first
    assert [kind for kind, _ in history] == ["get", "stream", "get", "stream", "get"]

    # Simulate publisher publishing a corrected zip; old pinned bytes retained.
    correction = "0" * 64

    def changed_get(self, url):
        return FakeResponse((correction + "  archive.zip\n").encode())

    monkeypatch.setattr(FakeClient, "get", changed_get)
    with pytest.raises(ValueError, match="Publisher checksum changed"):
        acquire_one(root, plan, spec_hash)
    stored, _ = archive_location(root, plan)
    assert digest(stored) == published
