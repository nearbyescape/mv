"""T7Sonic operator-approved *single* 1m archive acquisition utility.

Run from a separate checkout with the stdlib Python interpreter, never
inside MV production workers and never inside the T7Sonic strategy image.
Downloads at most ONE complete Jan–May 2026 monthly Binance USD-M
perpetual 1m ZIP per explicitly authorized fetch. Atomic new-file output,
published SHA256 validation, CSV row/coverage validation, disk budget and
read-only matching-existing verification. No database, deployment, signal
publishing, strategy import, automatic retry or background monitoring.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

FROZEN_SHA = "48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64"
FROZEN_SYMBOLS = frozenset((
    "BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT",
    "UNIUSDT","NEARUSDT","SUIUSDT","ADAUSDT","LINKUSDT","WLDUSDT",
    "TAOUSDT","ARBUSDT","AAVEUSDT","AVAXUSDT","FILUSDT","DOTUSDT",
    "BCHUSDT","LTCUSDT","INJUSDT","APTUSDT","XLMUSDT","TRXUSDT",
    "TIAUSDT","HYPEUSDT","ETCUSDT","OPUSDT","SEIUSDT","ASTERUSDT",
))
ALLOWED_MONTHS = frozenset(f"2026-{m:02d}" for m in range(1, 6))
STEP = 60_000
MAX_ZIP_BYTES = 48 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
DISK_RESERVE_BYTES = 2 * 1024 * 1024 * 1024
HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


def safe_root(root: Path) -> Path:
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Research archive root must be an existing absolute non-symlink directory")
    actual = root.resolve()
    if not (actual == Path("/var/tmp") or
            actual.is_relative_to(Path("/var/tmp")) or
            actual == Path("/tmp") or actual.is_relative_to(Path("/tmp"))):
        raise ValueError("Refusing writes outside /var/tmp or /tmp research directories")
    return actual


def plan(root: Path, symbol: str, month: str) -> dict:
    safe_root(root)
    if symbol not in FROZEN_SYMBOLS or month not in ALLOWED_MONTHS:
        raise ValueError("Symbol/month outside frozen development acquisition scope")
    year, mon = map(int, month.split("-"))
    start = int(datetime(year, mon, 1, tzinfo=timezone.utc).timestamp() * 1000)
    after = int(datetime(year + (mon == 12), mon % 12 + 1, 1,
                         tzinfo=timezone.utc).timestamp() * 1000)
    name = f"{symbol}-1m-{month}.zip"
    url = (f"https://data.binance.vision/data/futures/um/monthly/klines/"
           f"{symbol}/1m/{name}")
    folder = root / "archives" / symbol / "1m"
    archive = folder / name
    manifest = folder / (name + ".manifest.json")
    for node in (root/"archives", root/"archives"/symbol, folder, archive, manifest):
        if node.is_symlink():
            raise ValueError("Symlinked archive path forbidden")
    return {
        "symbol": symbol, "timeframe": "1m", "month": month,
        "filename": name, "start_ms": start, "end_exclusive_ms": after,
        "expected_rows": (after-start)//STEP,
        "url": url, "checksum_url": url + ".CHECKSUM",
        "spec_sha256": FROZEN_SHA,
        "archive_path": str(archive), "manifest_path": str(manifest),
        "present_pair": archive.is_file() and manifest.is_file(),
        "partial_pair": archive.exists() != manifest.exists(),
        "max_compressed_mib": MAX_ZIP_BYTES//(1024*1024),
        "free_floor_mib": DISK_RESERVE_BYTES//(1024*1024),
        "action": "PLANNED_ONLY_NO_DOWNLOAD",
    }


def _sha(path: Path) -> str:
    h = sha256()
    with path.open("rb") as fp:
        while chunk := fp.read(1024*1024):
            h.update(chunk)
    return h.hexdigest()


def _verify_zip(path: Path, p: dict) -> int:
    if path.stat().st_size > MAX_ZIP_BYTES:
        raise ValueError("Archive compressed size above bound")
    count = 0
    with ZipFile(path) as src:
        infos = src.infolist()
        expected_csv = p["filename"][:-4] + ".csv"
        if len(infos) != 1 or infos[0].filename != expected_csv:
            raise ValueError("Archive must contain one named CSV")
        if infos[0].file_size > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("CSV decompressed length exceeds bound")
        with src.open(infos[0]) as stream:
            rows = csv.reader(io.TextIOWrapper(stream, encoding="utf-8-sig",
                                              newline=""), strict=True)
            for row in rows:
                if count == 0 and row and row[0] in ("open_time","openTime"):
                    continue
                if len(row) != 12:
                    raise ValueError("Malformed Binance archive row")
                t = int(row[0])
                if t != p["start_ms"] + count*STEP or int(row[6]) != t + STEP - 1:
                    raise ValueError("Missing/overlapping candles or source close-time mismatch")
                try:
                    o,h,l,c,v=(Decimal(row[i]) for i in (1,2,3,4,5))
                except InvalidOperation as exc:
                    raise ValueError("Invalid numeric candle") from exc
                if not all(x.is_finite() for x in (o,h,l,c,v)):
                    raise ValueError("Nonfinite candle")
                if not (0 < l <= min(o,c) <= max(o,c) <= h and v >= 0):
                    raise ValueError("Invalid source OHLCV geometry")
                count += 1
                if count > p["expected_rows"]:
                    raise ValueError("Archive contains extra future source rows")
    if count != p["expected_rows"]:
        raise ValueError("Incomplete calendar-month 1m archive")
    return count


def verify_pinned(root: Path, symbol: str, month: str) -> dict:
    p = plan(root,symbol,month)
    if p["partial_pair"]:
        raise ValueError("Partial ZIP/sidecar pair requires operator repair")
    a,m = Path(p["archive_path"]),Path(p["manifest_path"])
    if not p["present_pair"]:
        raise FileNotFoundError("Pinned archive and sidecar required")
    rec=json.loads(m.read_text(encoding="utf-8"))
    for key in (
        "symbol","timeframe","month","filename","start_ms",
        "end_exclusive_ms","expected_rows","url","checksum_url","spec_sha256"
    ):
        if rec.get(key)!=p[key]:
            raise ValueError("Source manifest identity mismatch: "+key)
    checksum=rec.get("source_sha256")
    if not isinstance(checksum,str) or not HASH.fullmatch(checksum):
        raise ValueError("Source SHA256 missing")
    if _sha(a)!=checksum.lower():
        raise ValueError("Local archive SHA256 differs from pinned publisher checksum")
    if _verify_zip(a,p)!=rec.get("verified_rows"):
        raise ValueError("Archive count differs from acquisition ledger")
    return {
        "action":"LOCAL_ONLY_FULL_MONTH_VERIFY",
        "status":"COMPLETE_VERIFIED_EXISTING",
        "symbol":symbol,"month":month,
        "archive_sha256":checksum.lower(),
        "rows":rec["verified_rows"],
        "spec_sha256":FROZEN_SHA,
        "network_used":False,"production_mutation":False,
    }


def _fetch_published_sha(url: str) -> str:
    with urlopen(Request(url,headers={"User-Agent":"T7Sonic-History-Research/1"}),
                 timeout=35) as resp:
        raw=resp.read(512)
        if len(raw)==512:
            raise ValueError("Excessively large published checksum")
    items=raw.decode("ascii").split()
    if not items or not HASH.fullmatch(items[0]):
        raise ValueError("Invalid publisher SHA256 response")
    return items[0].lower()


def fetch_one(root: Path, symbol: str, month: str, *, approved: bool) -> dict:
    if approved is not True:
        raise ValueError("Explicit --confirm-single-fetch required")
    p = plan(root,symbol,month)
    if p["partial_pair"]:
        raise ValueError("Existing partial ZIP/sidecar pair: no overwrite allowed")
    if p["present_pair"]:
        raise ValueError("Archive already present; use verify, never silently replace it")
    if shutil.disk_usage(root).free < DISK_RESERVE_BYTES + MAX_ZIP_BYTES:
        raise OSError("Insufficient disk free space for safe bounded acquisition")
    target=Path(p["archive_path"])
    sidecar=Path(p["manifest_path"])
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_symlink() or sidecar.is_symlink() or target.exists() or sidecar.exists():
        raise ValueError("Existing or symlinked research source; no overwrite")
    published=_fetch_published_sha(p["checksum_url"])
    with tempfile.TemporaryDirectory(prefix=".t7source-",dir=target.parent) as tmp:
        candidate=Path(tmp)/p["filename"]
        h=sha256()
        size=0
        with urlopen(Request(p["url"],headers={"User-Agent":"T7Sonic-History-Research/1"}),
                     timeout=65) as response, candidate.open("wb") as out:
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>MAX_ZIP_BYTES:
                    raise ValueError("Publisher archive exceeds compressed 48 MiB budget")
                h.update(chunk)
                out.write(chunk)
        if h.hexdigest()!=published:
            raise ValueError("Downloaded ZIP differs from publisher .CHECKSUM")
        rows=_verify_zip(candidate,p)
        record={
            key:p[key] for key in (
                "symbol","timeframe","month","filename","start_ms",
                "end_exclusive_ms","expected_rows","url","checksum_url","spec_sha256"
            )
        }
        record.update({
            "source_sha256":published,
            "verified_rows":rows,
            "compressed_bytes":size,
            "publisher_checksum_retrieved_at":datetime.now(timezone.utc).isoformat(),
            "checksum_policy":"PUBLIC_PUBLISHER_SHA256_VERIFIED_AT_DOWNLOAD_TIME",
        })
        saved=Path(tmp)/(p["filename"]+".manifest.json")
        saved.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        # A crash between renames leaves a partial pair and fails closed.
        if target.exists() or sidecar.exists():
            raise ValueError("Source was concurrently added; cannot overwrite")
        os.rename(candidate,target)
        os.rename(saved,sidecar)
    result=verify_pinned(root,symbol,month)
    result.update({
        "action":"SINGLE_EXPLICIT_PUBLISHER_FETCH",
        "status":"ONE_MONTH_ACQUIRED_VERIFIED",
        "new_compressed_bytes":size,
        "publisher_checksum_authenticated":True,
        "network_used":True,
    })
    return result


def main():
    parser=argparse.ArgumentParser(description="T7Sonic single archived 1m month")
    parser.add_argument("action",choices=("plan","verify","fetch"))
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbol",required=True)
    parser.add_argument("--month",required=True)
    parser.add_argument("--confirm-single-fetch",action="store_true")
    args=parser.parse_args()
    root=safe_root(Path(args.root))
    if args.action=="plan":
        result=plan(root,args.symbol,args.month)
    elif args.action=="verify":
        result=verify_pinned(root,args.symbol,args.month)
    else:
        result=fetch_one(root,args.symbol,args.month,
                         approved=args.confirm_single_fetch)
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":
    main()
