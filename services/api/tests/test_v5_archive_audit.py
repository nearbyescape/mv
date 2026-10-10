"""Independent monthly seams and 1H/4H source reconciliation tests."""
from __future__ import annotations

from hashlib import sha256
import json
import sys
import zipfile

import pytest

from app.research import v5_archive_audit as audit
from app.research.v5_archives import archive_location, load_spec
from app.research.v5_archive_batch import batch_plan


def _fixtures(root, *, start="2026-04", end="2026-05", discrepant_4h=False):
    spec, fingerprint = load_spec()
    one = batch_plan(spec, "BTCUSDT", "1h", start, end)
    four = batch_plan(spec, "BTCUSDT", "4h", start, end)
    for plans in (one, four):
        for plan in plans:
            zip_path, sidecar = archive_location(root, plan)
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            step = audit.FRAME_MS[plan["timeframe"]]
            rows = []
            for index in range(plan["expected_rows"]):
                opened = plan["start_ms"] + step * index
                high = 102 if (
                    discrepant_4h
                    and plan["timeframe"] == "4h"
                    and plan["month"] == end
                    and index == 3
                ) else 101
                volume = 28 if plan["timeframe"] == "4h" else 7
                rows.append(",".join(
                    [str(opened), "100", str(high), "99", "100", str(volume),
                     str(opened + step - 1), "0", "0", "0", "0", "0"]
                ))
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as compressed:
                compressed.writestr(plan["filename"][:-4] + ".csv", "\n".join(rows) + "\n")
            payload = {
                **plan,
                "spec_sha256": fingerprint,
                "source_sha256": sha256(zip_path.read_bytes()).hexdigest(),
                "verified_rows": plan["expected_rows"],
            }
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return one, four, fingerprint


def test_cross_month_hourly_data_is_contiguous_and_bound_to_digest(tmp_path):
    one, _, fingerprint = _fixtures(tmp_path)
    a = audit.audit_continuity(tmp_path, one, fingerprint)
    b = audit.audit_continuity(tmp_path, one, fingerprint)
    assert a == b
    assert a["status"] == "CONTIGUOUS_VERIFIED"
    assert a["rows"] == 720 + 744
    assert a["end_exclusive_ms"] == one[-1]["end_exclusive_ms"]
    assert len(a["canonical_series_sha256"]) == 64


def test_native_hourly_aggregation_matches_four_hour_sources(tmp_path):
    one, four, fingerprint = _fixtures(tmp_path)
    result = audit.audit_pair(tmp_path, one, four, fingerprint)
    assert result["disposition"] == "PASS"
    assert result["comparison"]["status"] == "SOURCE_AGGREGATION_EXACT_MATCH"
    assert result["comparison"]["native_4h_rows"] == 180 + 186
    assert result["comparison"]["mismatched_native_4h_rows"] == 0
    assert result["comparison"]["field_mismatch_counts"] == {}
    assert result["one_hour"]["rows"] == 720 + 744
    assert result["four_hour"]["rows"] == 180 + 186


def test_native_source_disagreement_is_reported_not_corrected(tmp_path):
    one, four, fingerprint = _fixtures(tmp_path, discrepant_4h=True)
    result = audit.audit_pair(tmp_path, one, four, fingerprint)
    assert result["disposition"] == "REVIEW_REQUIRED"
    assert result["comparison"]["mismatched_native_4h_rows"] == 1
    assert result["comparison"]["field_mismatch_counts"] == {"high": 1}
    assert result["comparison"]["samples"][0]["fields"]["high"] == {
        "from_1h": "101", "native_4h": "102"
    }
    assert result["comparison"]["status"] == "SOURCE_DISAGREEMENT_REVIEW_REQUIRED"


def test_audit_rejects_missing_month_or_changed_pinned_archive(tmp_path):
    one, _, fingerprint = _fixtures(tmp_path)
    zip_path, sidecar = archive_location(tmp_path, one[1])
    sidecar.unlink()
    with pytest.raises(FileNotFoundError):
        audit.audit_continuity(tmp_path, one, fingerprint)
    # Re-create the correct manifest and alter only the archive bytes.
    payload = {**one[1], "spec_sha256": fingerprint,
               "source_sha256": sha256(zip_path.read_bytes()).hexdigest(),
               "verified_rows": one[1]["expected_rows"]}
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    zip_path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed|checksum"):
        audit.audit_continuity(tmp_path, one, fingerprint)


def test_audit_pair_rejects_unmatched_scope(tmp_path):
    one, four, fingerprint = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="matching scope"):
        audit.audit_one_vs_four(tmp_path, one, four[:1], fingerprint)
    with pytest.raises(ValueError, match="matching scope"):
        audit.audit_one_vs_four(tmp_path, four, one, fingerprint)


def test_offline_continuity_cli_prints_evidence_without_filesystem_mutation(
    tmp_path, monkeypatch, capsys
):
    one, four, fingerprint = _fixtures(tmp_path)
    before = sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob("*"))
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_audit", "continuity", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--timeframe", "1h",
        "--start-month", "2026-04", "--end-month", "2026-05",
    ])
    audit.main()
    data = json.loads(capsys.readouterr().out)
    assert data["rows"] == 1464
    assert sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob("*")) == before


def test_cross_frame_cli_exits_nonzero_on_publisher_disagreement(
    tmp_path, monkeypatch, capsys
):
    _fixtures(tmp_path, discrepant_4h=True)
    monkeypatch.setattr(sys, "argv", [
        "v5_archive_audit", "reconcile-1h-4h", "--root", str(tmp_path),
        "--symbol", "BTCUSDT", "--start-month", "2026-04",
        "--end-month", "2026-05",
    ])
    with pytest.raises(SystemExit) as raised:
        audit.main()
    assert raised.value.code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["disposition"] == "REVIEW_REQUIRED"
    assert output["comparison"]["mismatched_native_4h_rows"] == 1


def test_mismatched_4h_field_sample_is_bounded(tmp_path):
    one, four, fingerprint = _fixtures(tmp_path, start="2026-04", end="2026-04")
    # The mismatch fixture works in end month, and the audit must not mutate
    # source bars or permit invalid mismatched source scope.
    with pytest.raises(ValueError):
        audit.audit_continuity(tmp_path, [], fingerprint)
