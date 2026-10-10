"""Deterministic MV live-indicator audit: 500-bar warmup and month seams."""
from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
import sys
import zipfile

import pytest
from mv_strategy.indicators import Bar, INTERVAL_MS, IndicatorState

from app.research import v5_indicator_audit as indicator
from app.research.v5_archive_batch import batch_plan
from app.research.v5_archives import archive_location, load_spec


def _bars(timeframe, count=520, *, first_open=0, last_close_override=None):
    step = INTERVAL_MS[timeframe]
    for index in range(count):
        opening = first_open + index * step
        end = Decimal(100) + Decimal(index) / Decimal(1000)
        if last_close_override is not None and index == count - 1:
            end = Decimal(last_close_override)
        yield Bar(opening, opening + step - 1, end, end + 2, end - 2, end, Decimal(7))


@pytest.mark.parametrize("frame", ("15m", "1h", "4h"))
def test_500_bar_readiness_and_exact_close_timing(frame):
    step = INTERVAL_MS[frame]
    boundary = {0, 270 * step, 400 * step}
    report = indicator.reconstruct_stream(_bars(frame), frame, month_boundary_ms=boundary)
    assert report["status"] == "DETERMINISTIC_INDICATORS_VERIFIED"
    assert report["history_origin_ms"] == 0
    assert report["total_bars"] == 520
    assert report["counts"] == {
        "no_sma200": 199,
        "has_sma200_below_v5_warmup": 300,
        "v5_warm": 21,
    }
    assert report["warmup"]["sma200_first_close_ms"] == 200 * step
    assert report["warmup"]["v5_500_first_close_ms"] == 500 * step
    assert report["first_v5_500_snapshot"]["close_boundary"] == 500 * step
    assert report["first_v5_500_snapshot"]["bars"] == 500
    assert report["last_snapshot"]["close_boundary"] == 520 * step
    assert len(report["month_seam_checkpoints"]) == 3
    assert report["month_seam_checkpoints"][0]["count"] == 270
    assert report["month_seam_checkpoints"][1]["count"] == 400
    assert report["month_seam_checkpoints"][2]["count"] == 520


def test_reproducible_checkpoint_hashes_and_snapshot_evidence():
    frames = {0, 270 * INTERVAL_MS["1h"], 400 * INTERVAL_MS["1h"]}
    first = indicator.reconstruct_stream(_bars("1h"), "1h", month_boundary_ms=frames)
    second = indicator.reconstruct_stream(_bars("1h"), "1h", month_boundary_ms=frames)
    assert first == second
    assert all(
        len(row["state_sha256"]) == 64
        for row in first["month_seam_checkpoints"]
    )


def test_future_candle_cannot_change_prior_as_of_snapshot_or_checkpoint():
    step = INTERVAL_MS["1h"]
    borders = {0, 270 * step, 400 * step}
    baseline = indicator.reconstruct_stream(_bars("1h"), "1h", month_boundary_ms=borders)
    changed = indicator.reconstruct_stream(
        _bars("1h", last_close_override="500"), "1h",
        month_boundary_ms=borders,
    )
    assert baseline["first_v5_500_snapshot"] == changed["first_v5_500_snapshot"]
    assert baseline["first_sma200_snapshot"] == changed["first_sma200_snapshot"]
    assert (
        baseline["month_seam_checkpoints"][:2] == changed["month_seam_checkpoints"][:2]
    )
    assert baseline["last_snapshot"] != changed["last_snapshot"]
    assert (
        baseline["sma200_ready_snapshots_sha256"]
        != changed["sma200_ready_snapshots_sha256"]
    )


def test_less_than_five_hundred_bars_cannot_claim_strategy_ready():
    with pytest.raises(ValueError, match="500-candle warmup"):
        indicator.reconstruct_stream(
            _bars("4h", count=499), "4h",
            month_boundary_ms={0},
        )


def test_rejects_noncontiguous_history():
    step = INTERVAL_MS["1h"]
    incomplete = list(_bars("1h"))
    incomplete[280] = Bar(
        incomplete[280].open_time + step,
        incomplete[280].close_time + step,
        *(
            incomplete[280].open,
            incomplete[280].high,
            incomplete[280].low,
            incomplete[280].close,
            incomplete[280].volume,
        ),
    )
    with pytest.raises(ValueError, match="Non-contiguous"):
        indicator.reconstruct_stream(incomplete, "1h", month_boundary_ms={0, 270 * step})


def test_first_500_monthly_4h_candles_are_too_late_for_earlier_sessions(tmp_path):
    """Integration: pinned April–June 4h archive requires late-June warmup."""
    spec, fingerprint = load_spec()
    plans = batch_plan(spec, "BTCUSDT", "4h", "2026-04", "2026-06")
    for plan in plans:
        zip_path, sidecar = archive_location(tmp_path, plan)
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        step = INTERVAL_MS["4h"]
        records = []
        for idx in range(plan["expected_rows"]):
            opened = plan["start_ms"] + idx * step
            records.append(",".join([
                str(opened), "100", "102", "98", "100", "7",
                str(opened + step - 1), "0", "0", "0", "0", "0",
            ]))
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(plan["filename"][:-4] + ".csv", "\n".join(records) + "\n")
        sidecar.write_text(json.dumps({
            **plan, "spec_sha256": fingerprint,
            "source_sha256": sha256(zip_path.read_bytes()).hexdigest(),
            "verified_rows": plan["expected_rows"],
        }), encoding="utf-8")
    result = indicator.reconstruct_one(tmp_path, fingerprint, plans)
    assert result["source"]["rows"] == 546
    assert result["indicators"]["counts"]["v5_warm"] == 47
    assert result["indicators"]["warmup"]["v5_500_first_close_ms"] == (
        plans[0]["start_ms"] + 500 * INTERVAL_MS["4h"]
    )
    assert result["indicators"]["month_seam_checkpoints"][0]["count"] == 180
    assert result["indicators"]["month_seam_checkpoints"][1]["count"] == 366


def test_source_indicator_never_accepts_minute_execution_frame():
    with pytest.raises(ValueError, match="indicator-bearing"):
        indicator.reconstruct_stream([], "1m", month_boundary_ms={0})
