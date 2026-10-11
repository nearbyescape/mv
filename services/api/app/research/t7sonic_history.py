"""T7Sonic V5-format historical source adapter — strictly offline, read only.

Consumes already-acquired V5 month ZIP + sidecar pairs, but deliberately
does not import the V6HBR branch or use networked downloader / MV database.
Checks immutable prior research spec SHA, pathname, ZIP sha, complete calendar
row count, continuous timestamps, OHLCV and close-time geometry. The sidecar
is an acquisition record, NOT independent proof of Binance provenance.
5m is *derived exclusively from contiguous verified 1m*; never synthesized
from 15m/1h/4h or copied from a future candle.

Only April/May development is permitted. No performance labels, forecasts,
model fitting, signal publishing or production mutation.
"""
from __future__ import annotations

import calendar
import csv
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile

from .t7sonic_perception import (
    Bar, INTERVAL_MS, REQUIRED_FRAMES, perceive_symbol,
)
from .t7sonic_experts import research_market

# Exact SHA256 of packages/contracts/v5-history-v1.json from the frozen
# archival research contract. This is a pinned sidecar identifier and is
# independently checked against the original frozen text at acquisition.
FROZEN_SOURCE_SPEC_SHA256 = (
    "48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64"
)
HISTORICAL_FRAMES = ("1m", "15m", "1h", "4h")
SOURCE_INTERVALS = {f: INTERVAL_MS[f] for f in HISTORICAL_FRAMES}
DEVELOPMENT_START = int(datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
DEVELOPMENT_END = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
# Exactly 64 completed periods for every model-facing frame. 320 verified
# 1m candles are needed for 64 completed 5m periods.
OBSERVATION_BARS = 64
MAX_ZIP_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_CSV = 96 * 1024 * 1024
MAX_INPUT_SYMBOLS = 6  # preliminary development-only subset
FROZEN_MARKETS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    "UNIUSDT", "NEARUSDT", "SUIUSDT", "ADAUSDT", "LINKUSDT", "WLDUSDT",
    "TAOUSDT", "ARBUSDT", "AAVEUSDT", "AVAXUSDT", "FILUSDT", "DOTUSDT",
    "BCHUSDT", "LTCUSDT", "INJUSDT", "APTUSDT", "XLMUSDT", "TRXUSDT",
    "TIAUSDT", "HYPEUSDT", "ETCUSDT", "OPUSDT", "SEIUSDT", "ASTERUSDT",
)
MONTH_PATTERN = re.compile(r"2026-(?:0[1-9]|1[0-2])\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def _month(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")


def _month_bounds(name: str) -> tuple[int, int]:
    if not MONTH_PATTERN.fullmatch(name):
        raise ValueError("Invalid frozen 2026 archive month")
    yr, mo = map(int, name.split("-"))
    first = datetime(yr, mo, 1, tzinfo=timezone.utc)
    following = datetime(yr + (mo == 12), mo % 12 + 1, 1, tzinfo=timezone.utc)
    return int(first.timestamp()*1000), int(following.timestamp()*1000)


def _calendar_months(start_ms: int, end_exclusive_ms: int) -> tuple[str, ...]:
    """Months intersecting [start, end); never include the future month."""
    if end_exclusive_ms <= start_ms:
        raise ValueError("Empty historical range")
    result = []
    cursor = _month(start_ms)
    last = _month(end_exclusive_ms-1)
    while True:
        result.append(cursor)
        if cursor == last:
            break
        year, mon = map(int, cursor.split("-"))
        cursor = f"{year + (mon == 12):04d}-{mon % 12 + 1:02d}"
        if len(result) > 2:
            raise ValueError("Unexpected >2 source months for a single context")
    return tuple(result)


def _source_location(root: Path, symbol: str, frame: str, month: str):
    filename = f"{symbol}-{frame}-{month}.zip"
    folder = root / "archives" / symbol / frame
    return folder / filename, folder / (filename + ".manifest.json")


def _validate_path_inside_root(root: Path, path: Path) -> None:
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Explicit real absolute research root required")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Research archive escapes trusted root")
    node = path
    while node != root:
        if node.is_symlink():
            raise ValueError("Symlinked research source forbidden")
        node = node.parent
    if not path.is_file():
        raise FileNotFoundError(f"Required pinned archive or sidecar missing: {path.name}")


def _sha_file(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(1024*1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_month(root: Path, symbol: str, frame: str, month: str,
                  start_needed: int, end_exclusive: int,
                  keep_count: int) -> tuple[list[Bar], dict]:
    """Full-month verification before exposing its bounded as-of window."""
    if symbol not in FROZEN_MARKETS or frame not in HISTORICAL_FRAMES:
        raise ValueError("Source market/timeframe absent from frozen universe")
    source, sidecar = _source_location(root, symbol, frame, month)
    for path in (source, sidecar):
        _validate_path_inside_root(root, path)
    expected_start, expected_end = _month_bounds(month)
    step = SOURCE_INTERVALS[frame]
    expected_count = (expected_end - expected_start) // step
    if (expected_end - expected_start) % step:
        raise ValueError("Month does not divide source interval")
    if source.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("Compressed source archive exceeds bounded size")

    record = json.loads(sidecar.read_text(encoding="utf-8"))
    expected_filename = source.name
    url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
           f"{symbol}/{frame}/{expected_filename}")
    expected = {
        "spec_sha256": FROZEN_SOURCE_SPEC_SHA256,
        "symbol": symbol, "timeframe": frame, "month": month,
        "filename": expected_filename,
        "start_ms": expected_start, "end_exclusive_ms": expected_end,
        "expected_rows": expected_count,
        "verified_rows": expected_count,
        "url": url,
    }
    for key, value in expected.items():
        if record.get(key) != value:
            raise ValueError("Pinned source sidecar mismatch: " + key)
    source_sha = record.get("source_sha256")
    if not isinstance(source_sha, str) or not SHA_PATTERN.fullmatch(source_sha):
        raise ValueError("Pinned source sha256 missing or malformed")
    if record.get("checksum_url") != url + ".CHECKSUM":
        raise ValueError("Acquisition checksum URL mismatch")
    if _sha_file(source) != source_sha:
        raise ValueError("Pinned ZIP checksum mismatch")
    selected = deque(maxlen=keep_count)
    count = 0
    with ZipFile(source) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != expected_filename[:-4] + ".csv":
            raise ValueError("Unexpected ZIP entries or CSV name")
        if entries[0].is_dir() or entries[0].file_size > MAX_UNCOMPRESSED_CSV:
            raise ValueError("Invalid or oversized CSV member")
        with archive.open(entries[0]) as binary:
            with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as stream:
                csv.reader(stream, strict=True)
                for row in csv.reader(stream, strict=True):
                    if count == 0 and row and row[0] in ("open_time", "openTime"):
                        continue
                    if len(row) != 12:
                        raise ValueError("Binance monthly CSV row must have 12 columns")
                    t = int(row[0])
                    if t != expected_start + count * step:
                        raise ValueError("Missing, duplicate or future-disordered source bar")
                    if int(row[6]) != t + step - 1:
                        raise ValueError("Source candle close time geometry mismatch")
                    bar = Bar.parse({
                        "open_ms": t,
                        "open": row[1], "high": row[2], "low": row[3],
                        "close": row[4], "volume": row[5],
                    }, frame)
                    if start_needed <= t and t + step <= end_exclusive:
                        selected.append(bar)
                    count += 1
                    if count > expected_count:
                        raise ValueError("Oversized calendar month")
    if count != expected_count:
        raise ValueError("Incomplete calendar month")
    return list(selected), {
        "frame":frame, "month":month, "publisher_archive_sha256":source_sha,
        "sidecar_sha256":_sha_file(sidecar),
        "verified_calendar_rows":count,
    }


def _necessary_first_ms(frame: str, as_of_ms: int) -> tuple[int, int]:
    step = INTERVAL_MS[frame]
    last_completed_end = (as_of_ms // step)*step
    count = OBSERVATION_BARS*5 if frame == "1m" else OBSERVATION_BARS
    return last_completed_end-count*step, last_completed_end


def _bars_to_json(bars: list[Bar]) -> list[dict]:
    return [{
        "open_ms":b.open_ms,
        "open": str(b.opening), "high": str(b.high),
        "low": str(b.low), "close": str(b.close),
        "volume":str(b.volume),
    } for b in bars]


def _derive_5m(minute_bars: list[Bar]) -> list[Bar]:
    if len(minute_bars) != 5*OBSERVATION_BARS:
        raise ValueError("Incomplete minute source for exact 5m rollup")
    output = []
    step = INTERVAL_MS["1m"]
    for idx in range(0, len(minute_bars), 5):
        group = minute_bars[idx:idx+5]
        first = group[0].open_ms
        if first % INTERVAL_MS["5m"] != 0 or any(
            bar.open_ms != first+n*step for n,bar in enumerate(group)
        ):
            raise ValueError("Cannot derive 5m from partial or misaligned minute data")
        output.append(Bar(
            first, group[0].opening,
            max(b.high for b in group),
            min(b.low for b in group),
            group[-1].close,
            sum((b.volume for b in group), D(0)),
        ))
    return output



def _reconcile_higher_frames_against_minutes(frames: dict) -> dict:
    """Strictly reject contradiction between OHLCV timeframes.

    Reconciliation uses only completed minute candles already verified with
    the independently pinned 1m archive. An unavailable/discordant native
    exchange frame must be reviewed; do NOT patch it silently, which would
    manufacture the source time series.
    """
    minutes = frames["1m"]
    if not minutes:
        raise ValueError("Minute source required for independent reconciliation")
    low_time, high_time = minutes[0].open_ms, minutes[-1].open_ms + 60_000
    minute_by_time = {r.open_ms:r for r in minutes}
    checked = {}
    for frame in ("15m","1h","4h"):
        count=0
        step=SOURCE_INTERVALS[frame]
        for native in frames[frame]:
            start=native.open_ms
            if start < low_time or start+step > high_time:
                continue
            segment = [minute_by_time.get(start+j*60_000)
                       for j in range(step//60_000)]
            if any(row is None for row in segment):
                raise ValueError("Insufficient minute bars for resolution reconciliation")
            minute_derived = Bar(
                start, segment[0].opening,
                max(b.high for b in segment),
                min(b.low for b in segment),
                segment[-1].close,
                sum((b.volume for b in segment),D(0)),
            )
            if minute_derived != native:
                raise ValueError(
                    "Native timeframe contradicts independently verified minute OHLCV: "
                    + frame
                )
            count+=1
        if count < 1:
            raise ValueError("Minute source did not cover even one full " + frame + " bar")
        checked[frame]=count
    return {
        "status":"STRICT_EXACT_CROSS_RESOLUTION_RECONCILIATION",
        "native_bars_reconciled_to_1m":checked,
        "disagreement_policy":"FAIL_CLOSED_NO_SYNTHETIC_CORRECTION",
    }

def verified_historical_snapshot(root: Path, symbol: str,
                                 as_of_ms: int) -> tuple[dict, dict]:
    """Construct one complete 5-frame development-only market snapshot.

    Fail closed if even one needed prior month/1m source is unavailable.
    Source verification is performed over whole calendar ZIPs first.
    """
    if symbol not in FROZEN_MARKETS:
        raise ValueError("Symbol absent from frozen 30-market research list")
    if (type(as_of_ms) is not int or
        not DEVELOPMENT_START <= as_of_ms < DEVELOPMENT_END or
        as_of_ms % INTERVAL_MS["5m"]):
        raise ValueError("Only Apr–May 2026 completed five-minute development boundaries")
    if not isinstance(root, Path):
        raise ValueError("Research root must be an explicit Path")
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Research source root invalid")
    frames = {}
    source_provenance = {}
    for frame in HISTORICAL_FRAMES:
        begin,end = _necessary_first_ms(frame,as_of_ms)
        wanted = OBSERVATION_BARS*5 if frame == "1m" else OBSERVATION_BARS
        months = _calendar_months(begin,end)
        parsed = []
        evidence = []
        for month in months:
            part, proof = _verify_month(
                root,symbol,frame,month,begin,end,wanted
            )
            parsed.extend(part)
            evidence.append(proof)
        if (len(parsed) != wanted or
            parsed[0].open_ms != begin or
            parsed[-1].open_ms + INTERVAL_MS[frame] != end or
            any(b.open_ms-a.open_ms != INTERVAL_MS[frame] for a,b in zip(parsed,parsed[1:]))):
            raise ValueError("Missing, stale, duplicated or future historical context: " + frame)
        frames[frame] = parsed
        source_provenance[frame] = evidence
    resolution_proof = _reconcile_higher_frames_against_minutes(frames)
    derived_five = _derive_5m(frames["1m"])
    snapshot = {
        "symbol":symbol, "as_of_ms":as_of_ms,
        "bars":{
            frame:_bars_to_json(
                derived_five if frame=="5m" else
                frames[frame][-OBSERVATION_BARS:]
            )
            for frame in REQUIRED_FRAMES
        },
    }
    # Additional independent no-lookahead/EMA/ATR/volume invariant validation.
    perceive_symbol(snapshot)
    return snapshot, {
        "source_spec_sha256": FROZEN_SOURCE_SPEC_SHA256,
        "symbol":symbol, "as_of_ms":as_of_ms,
        "source_months_verified":source_provenance,
        "resolution_reconciliation":resolution_proof,
        "five_minute_derivation":"EXACT_FIVE_CONSECUTIVE_PINNED_ONE_MINUTE_BARS",
        "upstream_publisher_checksum_authentication":"PINNED_SIDECAR_ONLY_NO_LIVE_PUBLISHER_QUERY",
        "future_validation_and_holdout_access":False,
    }


def historical_research_case(root: Path, symbols: tuple[str, ...],
                             as_of_ms: int) -> dict:
    if not isinstance(symbols, tuple) or not 1 <= len(symbols) <= MAX_INPUT_SYMBOLS:
        raise ValueError("Only explicit bounded 1–6-market development smoke subset")
    if len(set(symbols)) != len(symbols) or any(s not in FROZEN_MARKETS for s in symbols):
        raise ValueError("Duplicate or unknown frozen market")
    perceptions = []
    proofs = {}
    for symbol in symbols:
        snapshot, provenance = verified_historical_snapshot(root,symbol,as_of_ms)
        perceptions.append(perceive_symbol(snapshot))
        proofs[symbol] = provenance
    result = research_market(perceptions)
    result["historical_provenance"] = proofs
    result["development_only"] = True
    result["run_scope"] = "EXPLICIT_SUBSET_NOT_FULL_UNIVERSE"
    result["publication_authorized"] = False
    result["orders_authorized"] = False
    return result
