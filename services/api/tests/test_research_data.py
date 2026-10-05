import csv
from decimal import Decimal as D
import hashlib
import io
import json
from pathlib import Path
import zipfile

from fastapi.testclient import TestClient
import pytest
from mv_strategy.signals import canonical_hash
from app.main import app
from app.research.dataset import archive_bars, parse_funding, verified_path, load_manifest, stream_bars
from app.research import reports
from app.research import dataset

AUTH = {"Authorization": "Bearer mv-local-preview-only"}
START = 1704067200000


def archive(path, rows):
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerows(rows)
    with zipfile.ZipFile(path, "w") as result:
        result.writestr("BTCUSDT-1m.csv", text.getvalue())


def candle(time=START):
    return [time, "100.00", "101.0", "99.00", "100.10", "1.000", time + 59_999, "0", "1", "0", "0", "0"]


def test_real_archive_header_and_exact_strings_preserved(tmp_path):
    path = tmp_path / "fixture.zip"
    archive(path, [["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker", "quote", "ignore"], candle()])
    bars = list(archive_bars(path, "1m"))
    assert str(bars[0].open) == "100.00" and str(bars[0].volume) == "1.000"


@pytest.mark.parametrize("change", ["bad_ohlc", "nonfinite", "microseconds", "wrong_close", "truncated"])
def test_malformed_archive_cannot_become_research_data(tmp_path, change):
    row = candle()
    if change == "bad_ohlc": row[3] = "102"
    elif change == "nonfinite": row[4] = "NaN"
    elif change == "microseconds": row[0] *= 1000
    elif change == "wrong_close": row[6] -= 1
    else: row.pop()
    path = tmp_path / "fixture.zip"
    archive(path, [row])
    with pytest.raises(ValueError):
        list(archive_bars(path, "1m"))


def test_pinned_archive_corruption_path_traversal_and_stream_gaps_fail(tmp_path):
    path = tmp_path / "fixture.zip"
    archive(path, [candle(), candle(START + 120_000)])
    item = {"symbol": "BTCUSDT", "timeframe": "1m", "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "start": START, "end_exclusive": START + 180_000}
    with pytest.raises(ValueError, match="Gap"):
        list(stream_bars(tmp_path, {"archives": [item]}, "BTCUSDT", "1m"))
    with pytest.raises(ValueError): verified_path(tmp_path, {**item, "sha256": "0" * 64})
    with pytest.raises(ValueError): verified_path(tmp_path, {**item, "file": "../outside.zip"})


def funding(time, rate=".001", mark="100"):
    return {"symbol": "BTCUSDT", "fundingTime": time, "fundingRate": rate, "markPrice": mark}


@pytest.mark.parametrize("change", ["first_missing", "middle_missing", "last_missing", "duplicate", "float", "mark_missing", "wrong_symbol"])
def test_missing_or_invalid_funding_blocks_instead_of_zero_cost(change):
    rows = [funding(START + n * 28_800_000) for n in range(4)]
    if change == "first_missing": rows.pop(0)
    elif change == "middle_missing": rows.pop(1)
    elif change == "last_missing": rows.pop()
    elif change == "duplicate": rows.insert(1, rows[0])
    elif change == "float": rows[0]["fundingRate"] = .001
    elif change == "mark_missing": rows[0]["markPrice"] = ""
    else: rows[0]["symbol"] = "ETHUSDT"
    with pytest.raises((ValueError, ArithmeticError)):
        parse_funding(rows, "BTCUSDT", START, START + 4 * 28_800_000)


def test_shorter_actual_funding_intervals_and_negative_rates_preserved():
    rows = [funding(START + n * 14_400_000, "-.0001", "123.456") for n in range(8)]
    assert len(parse_funding(rows, "BTCUSDT", START, START + 4 * 28_800_000)) == 8


def saved_report(tmp_path):
    identity = "a" * 64
    directory = tmp_path / identity
    directory.mkdir()
    (directory / "trades.csv").write_text("symbol,net_pnl\nBTCUSDT,-1.00\n")
    report = {"id": identity, "files": {"trades.csv": hashlib.sha256((directory / "trades.csv").read_bytes()).hexdigest()}, "groups": []}
    report["report_hash"] = canonical_hash(report)
    (directory / "report.json").write_text(json.dumps(report))
    (tmp_path / "latest.json").write_text(json.dumps({"id": identity, "report_hash": report["report_hash"]}))
    return directory, report


def test_protected_readonly_report_empty_state_download_and_integrity(monkeypatch, tmp_path):
    monkeypatch.setattr(reports, "REPORT_ROOT", tmp_path)
    client = TestClient(app)
    assert client.get("/v1/research").status_code == 401
    assert client.get("/v1/research", headers=AUTH).json() == {"available": False, "report": None}
    directory, report = saved_report(tmp_path)
    assert client.get("/v1/research", headers=AUTH).json()["report"] == report
    response = client.get("/v1/research/export?file=trades.csv", headers=AUTH)
    assert response.status_code == 200 and "-1.00" in response.text
    assert client.get("/v1/research/export?file=../secrets", headers=AUTH).status_code == 422
    assert client.post("/v1/research", headers=AUTH).status_code == 405
    (directory / "trades.csv").write_text("tampered")
    assert client.get("/v1/research/export?file=trades.csv", headers=AUTH).status_code == 422
    (directory / "report.json").write_text(json.dumps({**report, "groups": ["tampered"]}))
    assert client.get("/v1/research", headers=AUTH).status_code == 503


def test_invalid_latest_pointer_cannot_read_outside_report_root(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps({"id": "../private"}))
    with pytest.raises(ValueError): reports.read_report(tmp_path)


def test_canonical_minute_audit_preserves_native_archives_and_pins_every_override(tmp_path, monkeypatch):
    spec = {"symbols": ["BTCUSDT"], "history_start": "2024-01-01", "cutoff_exclusive": "2024-01-02", "source_policy": "completed UTC raw-minute aggregation"}
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec))
    monkeypatch.setattr(dataset, "SPEC_PATH", spec_path)
    entries = []
    for timeframe, step in (("1m", 60_000), ("1h", 3_600_000), ("4h", 14_400_000)):
        rows = []
        for index in range(86_400_000 // step):
            time = START + index * step
            volume = str(step // 60_000)
            close = "100.10"
            if timeframe == "1h" and index == 0: volume = "59"
            if timeframe == "4h" and index == 0: close = "100.00"
            rows.append([time, "100.00", "101.0", "99.00", close, volume, time + step - 1, "0", "1", "0", "0", "0"])
        path = tmp_path / f"{timeframe}.zip"
        archive(path, rows)
        entries.append({"symbol": "BTCUSDT", "timeframe": timeframe, "file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "start": START, "end_exclusive": START + 86_400_000})
    manifest = {"symbols": ["BTCUSDT"], "start": START, "end_exclusive": START + 86_400_000, "archives": entries, "funding": {}, "limitations": [], "spec_hash": "native"}
    manifest["dataset_hash"] = canonical_hash(manifest)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    audited = dataset.canonicalize(tmp_path)
    assert audited["canonical_overrides"]["discrepancies"] == 2
    assert audited["minute_source_audit"]["rows"] == 1440
    assert list(stream_bars(tmp_path, audited, "BTCUSDT", "1h"))[0].volume == D(60)
    assert list(archive_bars(tmp_path / "1h.zip", "1h"))[0].volume == D(59)
    assert list(stream_bars(tmp_path, audited, "BTCUSDT", "4h"))[0].close == D("100.10")
    assert dataset.canonicalize(tmp_path)["dataset_hash"] == audited["dataset_hash"]
    (tmp_path / "canonical-overrides.json").write_text("[]")
    with pytest.raises(ValueError): dataset.load_manifest(tmp_path)
