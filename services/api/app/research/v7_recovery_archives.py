"""Strict offline 15m market-archive reader for V7 recovery research.

Historical Binance ZIP + .CHECKSUM is publisher-hosted integrity metadata,
NOT proof of exchange signature or independently witnessed capture time.
No network, database, Telegram, order entry or production side effects.
"""
from __future__ import annotations

import calendar
import csv
from datetime import datetime, timezone
from decimal import Decimal as D
from hashlib import sha256
from pathlib import Path
import re
from zipfile import ZipFile

from app.research.t7sonic_perception import Bar

MARKETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT")
STEP_MS = 900_000
MAX_ZIP = 16 * 1024 * 1024
MAX_CSV = 64 * 1024 * 1024
MONTH_RE = re.compile(r"2026-(0[1-9]|1[0-2])\Z")
SHA_RE = re.compile(r"[a-f0-9]{64}\Z")
MONTHS = ("2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def monthly_paths(root: Path, symbol: str, month: str) -> tuple[Path, Path]:
    if symbol not in MARKETS or not MONTH_RE.fullmatch(month):
        raise ValueError("Frozen V7 research symbols and 2026 months only")
    name = f"{symbol}-15m-{month}.zip"
    return root / symbol / name, root / symbol / (name + ".CHECKSUM")


def expected_month_start(month: str) -> tuple[int, int]:
    if not MONTH_RE.fullmatch(month):
        raise ValueError("Malformed archive month")
    year, mm = (int(x) for x in month.split("-"))
    start = datetime(year, mm, 1, tzinfo=timezone.utc)
    end = datetime(year + int(mm == 12), mm % 12 + 1, 1, tzinfo=timezone.utc)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def validate_checksum(checksum: bytes, filename: str, sha: str) -> None:
    if len(checksum) > 256 or not checksum:
        raise ValueError("Invalid publisher checksum body")
    try:
        parts = checksum.decode("ascii").strip().split()
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid publisher checksum encoding") from exc
    if (len(parts) != 2 or not SHA_RE.fullmatch(parts[0].lower()) or
            parts[1].lstrip("*") != filename or
            parts[0].lower() != sha.lower()):
        raise ValueError("Published archive checksum mismatch")


def verified_month(root: Path, symbol: str, month: str) -> tuple[list[Bar], dict]:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
        raise ValueError("Absolute non-symlink archive root required")
    archive, checksum = monthly_paths(root, symbol, month)
    if (archive.is_symlink() or checksum.is_symlink() or
            not archive.is_file() or not checksum.is_file() or
            archive.stat().st_size > MAX_ZIP or archive.stat().st_size < 32):
        raise ValueError("Missing, oversized or symlinked original archive")
    sha = _file_sha256(archive)
    validate_checksum(checksum.read_bytes(), archive.name, sha)
    first, end = expected_month_start(month)
    expected = (end - first) // STEP_MS
    results = []
    with ZipFile(archive) as z:
        listing = z.infolist()
        if (len(listing) != 1 or listing[0].is_dir() or
                listing[0].filename != archive.name[:-4] + ".csv" or
                listing[0].file_size > MAX_CSV):
            raise ValueError("Unexpected CSV archive structure")
        with z.open(listing[0]) as src:
            import io
            stream = io.TextIOWrapper(src, encoding="utf-8-sig", newline="")
            for row in csv.reader(stream, strict=True):
                if not results and row and row[0] in ("open_time", "openTime"):
                    continue
                if len(row) != 12:
                    raise ValueError("Unexpected futures klines CSV format")
                expected_open = first + len(results) * STEP_MS
                if (int(row[0]) != expected_open or
                        int(row[6]) != expected_open + STEP_MS - 1):
                    raise ValueError("Missing/duplicate/out-of-order historical bar")
                results.append(Bar.parse({
                    "open_ms": expected_open,
                    "open": row[1], "high": row[2], "low": row[3],
                    "close": row[4], "volume": row[5],
                }, "15m"))
                if len(results) > expected:
                    raise ValueError("Unexpected extra historical bars")
    if len(results) != expected:
        raise ValueError("Incomplete source month")
    return results, {
        "symbol": symbol, "month": month,
        "zip_sha256": sha, "publisher_checksum_sha256": _file_sha256(checksum),
        "verified_rows": len(results),
        "publisher_checksum_is_independent_attestation": False,
    }


def verified_series(root: Path, symbol: str, months: tuple[str, ...] = MONTHS) -> tuple[list[Bar], list[dict]]:
    if not months or len(months) != len(set(months)) or tuple(sorted(months)) != months:
        raise ValueError("Expected ordered, unique archive months")
    if any(month not in MONTHS for month in months):
        raise ValueError("Only declared April-September 2026 development history")
    previous_end = None
    all_rows = []
    provenance = []
    for month in months:
        begin, end = expected_month_start(month)
        if previous_end is not None and begin != previous_end:
            raise ValueError("Archive months are not contiguous")
        rows, p = verified_month(root, symbol, month)
        all_rows.extend(rows)
        provenance.append(p)
        previous_end = end
    if any(b.open_ms - a.open_ms != STEP_MS for a, b in zip(all_rows, all_rows[1:])):
        raise ValueError("Non-contiguous historical data")
    return all_rows, provenance
