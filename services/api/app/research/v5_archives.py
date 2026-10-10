"""Standalone V5 monthly futures archive acquisition and fail-closed verification.

No MV database, production market collector, scanner, or Telegram access.
This deliberately downloads only ONE explicitly selected archive per invocation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

import httpx

from .dataset import ROOT, archive_bars, timestamp

SPEC = ROOT / "packages/contracts/v5-history-v1.json"
FRAME_MS = {"1m": 60_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
MAX_COMPRESSED_BYTES = 300 * 1024 * 1024
HOST = "https://data.binance.vision"
HEX64 = re.compile(r"[a-fA-F0-9]{64}\Z")
MONTH = re.compile(r"20[0-9]{2}-(?:0[1-9]|1[0-2])\Z")


def load_spec(path: Path = SPEC) -> tuple[dict, str]:
    raw = path.read_bytes()
    spec = json.loads(raw)
    if (
        spec.get("schema") != 1
        or len(spec.get("symbols", [])) != 30
        or len(set(spec["symbols"])) != 30
        or spec.get("timeframes") != list(FRAME_MS)
    ):
        raise ValueError("V5 archive research specification is invalid")
    return spec, sha256(raw).hexdigest()


def archive_plan(spec: dict, symbol: str, timeframe: str, month: str) -> dict:
    if symbol not in spec["symbols"] or timeframe not in FRAME_MS:
        raise ValueError("Symbol/timeframe not in the frozen V5 research universe")
    if MONTH.fullmatch(month) is None:
        raise ValueError("Month must be YYYY-MM")
    year, number = map(int, month.split("-"))
    start = timestamp(month + "-01")
    following = (datetime(year + (number == 12), (number % 12) + 1, 1, tzinfo=timezone.utc))
    end = int(following.timestamp() * 1000)
    if not timestamp(spec["history_start"]) <= start < end <= timestamp(spec["cutoff_exclusive"]):
        raise ValueError("Month outside pinned research history")
    if end > int(datetime.now(timezone.utc).timestamp() * 1000):
        raise ValueError("Requested monthly archive is not completed")
    filename = f"{symbol}-{timeframe}-{month}.zip"
    url = f"{HOST}/data/futures/um/monthly/klines/{symbol}/{timeframe}/{filename}"
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "month": month,
        "filename": filename,
        "start_ms": start,
        "end_exclusive_ms": end,
        "expected_rows": (end - start) // FRAME_MS[timeframe],
        "url": url,
        "checksum_url": url + ".CHECKSUM",
    }


def archive_location(root: Path, plan: dict) -> tuple[Path, Path]:
    folder = root / "archives" / plan["symbol"] / plan["timeframe"]
    return folder / plan["filename"], folder / (plan["filename"] + ".manifest.json")


def valid_research_root(value: str) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ValueError("--root must be an absolute research archive location")
    root = candidate.resolve()
    code_root = ROOT.resolve()
    if root == Path("/") or root == code_root or root in code_root.parents or code_root in root.parents:
        raise ValueError("Archives must not be written inside or above source checkout")
    return root


def digest(path: Path) -> str:
    hasher = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def validate_archive(path: Path, plan: dict, expected_sha: str) -> int:
    if HEX64.fullmatch(expected_sha) is None:
        raise ValueError("Invalid publisher checksum")
    if digest(path) != expected_sha.lower():
        raise ValueError("Archive SHA-256 does not match pinned checksum")
    step = FRAME_MS[plan["timeframe"]]
    count = 0
    for bar in archive_bars(path, plan["timeframe"]):
        if bar.open_time != plan["start_ms"] + count * step:
            raise ValueError(f"Missing, reordered or duplicated source candle at row {count}")
        count += 1
        if count > plan["expected_rows"]:
            raise ValueError("Archive extends beyond its calendar month")
    if count != plan["expected_rows"]:
        raise ValueError(f"Incomplete month: {count} != {plan['expected_rows']}")
    return count


def verify_existing(root: Path, plan: dict, spec_sha: str) -> dict:
    archive, sidecar = archive_location(root, plan)
    if not archive.is_file() or not sidecar.is_file():
        raise FileNotFoundError("Both the archive and its pinned manifest are required")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    for field in ("symbol", "timeframe", "month", "start_ms", "end_exclusive_ms", "expected_rows", "url"):
        if record.get(field) != plan[field]:
            raise ValueError(f"Archive manifest mismatch: {field}")
    if record.get("spec_sha256") != spec_sha:
        raise ValueError("Archive manifest belongs to a different research specification")
    if record.get("source_sha256") != digest(archive):
        raise ValueError("Archived ZIP has changed since acquisition")
    count = validate_archive(archive, plan, record["source_sha256"])
    if count != record.get("verified_rows"):
        raise ValueError("Archive row-count evidence differs")
    return record


def _checksum_text(body: str) -> str:
    first = body.split()
    if not first or HEX64.fullmatch(first[0]) is None:
        raise ValueError("Invalid Binance published CHECKSUM")
    return first[0].lower()


@contextmanager
def single_archive_lock(path: Path):
    """Prevent two independent fetch jobs from altering one archive concurrently."""
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_one(root: Path, plan: dict, spec_sha: str, *, max_archive_bytes: int = MAX_COMPRESSED_BYTES) -> dict:
    if type(max_archive_bytes) is not int or not 0 < max_archive_bytes <= MAX_COMPRESSED_BYTES:
        raise ValueError("Invalid per-archive compressed-byte limit")
    archive, manifest_path = archive_location(root, plan)
    archive.parent.mkdir(parents=True, exist_ok=True)
    with single_archive_lock(archive.with_suffix(archive.suffix + ".lock")):
        # Always read the publisher checksum. A publisher correction must be
        # explicitly reviewed; never replace an existing pinned archive.
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            response = client.get(plan["checksum_url"])
            response.raise_for_status()
            published_sha = _checksum_text(response.text)

            if archive.exists() or manifest_path.exists():
                record = verify_existing(root, plan, spec_sha)
                if published_sha != record["source_sha256"]:
                    raise ValueError("Publisher checksum changed; keep old archive and investigate")
                return record

            # Private temp directory is cleaned even on HTTP, checksum or
            # candle-validation failures; nothing touches a production DB.
            with tempfile.TemporaryDirectory(dir=archive.parent) as scratch:
                temporary = Path(scratch) / plan["filename"]
                total = 0
                hasher = sha256()
                with client.stream("GET", plan["url"]) as download:
                    download.raise_for_status()
                    with temporary.open("wb") as out:
                        for chunk in download.iter_bytes(chunk_size=1024 * 1024):
                            total += len(chunk)
                            if total > max_archive_bytes:
                                raise ValueError("Compressed archive exceeds safety limit")
                            hasher.update(chunk)
                            out.write(chunk)
                if hasher.hexdigest() != published_sha:
                    raise ValueError("Downloaded archive failed published SHA-256")
                rows = validate_archive(temporary, plan, published_sha)
                record = {
                    **plan,
                    "spec_sha256": spec_sha,
                    "source_sha256": published_sha,
                    "verified_rows": rows,
                    "compressed_bytes": total,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                }
                record_temp = Path(scratch) / (plan["filename"] + ".manifest.json")
                record_temp.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                # Neither target existed when the lock was acquired. A
                # two-file recovery after abrupt host death must be manual.
                os.replace(temporary, archive)
                os.replace(record_temp, manifest_path)
                return record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Offline, one-archive-at-a-time MV V5 history acquisition"
    )
    parser.add_argument("action", choices=("plan", "fetch", "verify"))
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", required=True, choices=FRAME_MS.keys())
    parser.add_argument("--month", required=True)
    args = parser.parse_args()
    spec, spec_sha = load_spec()
    plan = archive_plan(spec, args.symbol, args.timeframe, args.month)
    root = valid_research_root(args.root)

    if args.action == "plan":
        result = {"action": args.action, "root": str(root), "spec_sha256": spec_sha, **plan}
    elif args.action == "fetch":
        result = {"action": args.action, **acquire_one(root, plan, spec_sha)}
    else:
        result = {"action": args.action, **verify_existing(root, plan, spec_sha)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
