"""Checksum-pinned public futures archive acquisition and strict streaming validation."""
import asyncio
import calendar
import csv
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

import httpx
from mv_strategy import Bar
from mv_strategy.signals import canonical_hash

ROOT = Path(__file__).resolve().parents[4]
SPEC_PATH = ROOT / "packages/contracts/research-v1.json"
DATA_ROOT = ROOT / "research-data"
STEPS = {"1m": 60_000, "1h": 3_600_000, "4h": 14_400_000}


def timestamp(date):
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) * 1000


def months(start, end):
    date = datetime.fromtimestamp(start / 1000, timezone.utc)
    while int(date.timestamp()) * 1000 < end:
        yield date.strftime("%Y-%m")
        date = date.replace(year=date.year + (date.month == 12), month=date.month % 12 + 1)


def validate_bar(bar, timeframe):
    if timeframe != "1m":
        bar.validate(timeframe)
        return
    if type(bar.open_time) is not int or bar.open_time < 0 or bar.open_time % 60_000 or bar.close_time != bar.open_time + 59_999:
        raise ValueError("Invalid millisecond minute boundaries")
    values = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    if any(not isinstance(v, Decimal) or not v.is_finite() for v in values) or min(values[:4]) <= 0 or bar.volume < 0 or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
        raise ValueError("Invalid minute OHLCV")


def archive_bars(path, timeframe):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].endswith(".csv"):
            raise ValueError("Archive must contain exactly one CSV")
        with archive.open(names[0]) as member, io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as stream:
            for index, row in enumerate(csv.reader(stream)):
                if index == 0 and row and row[0] in ("open_time", "openTime"):
                    continue
                if len(row) != 12:
                    raise ValueError("Malformed archive row")
                bar = Bar(int(row[0]), int(row[6]), *(Decimal(v) for v in row[1:6]))
                validate_bar(bar, timeframe)
                yield bar


def verified_path(root, item):
    path = (root / item["file"]).resolve()
    if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
        raise ValueError("Dataset checksum/path mismatch")
    return path


def stream_bars(root, manifest, symbol, timeframe, start=None, end=None):
    previous = None
    overrides = {}
    if timeframe != "1m" and manifest.get("canonical_overrides"):
        corrections = json.loads(verified_path(root, manifest["canonical_overrides"]).read_text())
        overrides = {item["open_time"]: item["canonical"] for item in corrections if item["symbol"] == symbol and item["timeframe"] == timeframe}
    for item in manifest["archives"]:
        if item["symbol"] != symbol or item["timeframe"] != timeframe:
            continue
        if start is not None and item["end_exclusive"] <= start or end is not None and item["start"] >= end:
            continue
        path = verified_path(root, item)
        for bar in archive_bars(path, timeframe):
            if bar.open_time in overrides:
                values = overrides[bar.open_time]
                bar = Bar(values["open_time"], values["close_time"], *(Decimal(values[k]) for k in ("open", "high", "low", "close", "volume")))
                validate_bar(bar, timeframe)
            if start is not None and bar.open_time < start or end is not None and bar.open_time >= end:
                continue
            if previous is not None and bar.open_time != previous + STEPS[timeframe]:
                raise ValueError("Gap, duplicate or reordered research bars")
            previous = bar.open_time
            yield bar


def parse_funding(rows, symbol, start, end):
    result = []
    previous = None
    for row in rows:
        if row.get("symbol") != symbol or type(row.get("fundingTime")) is not int or any(not isinstance(row.get(key), str) for key in ("fundingRate", "markPrice")):
            raise ValueError("Invalid funding symbol/time")
        time = row["fundingTime"]
        rate, mark = Decimal(row["fundingRate"]), Decimal(row["markPrice"])
        if not rate.is_finite() or not mark.is_finite() or mark <= 0 or previous is not None and time <= previous:
            raise ValueError("Invalid funding price/rate/order")
        previous = time
        if start <= time < end:
            result.append({"time": time, "rate": str(rate), "mark_price": str(mark)})
    # This dataset is explicitly BTC/ETH 2024-2025. Do not assume every contract
    # always has an 8h interval. Shorter intervals are accepted; missing charges fail.
    max_gap = 28_802_000
    if not result or result[0]["time"] - start > 2000 or end - result[-1]["time"] > max_gap or any(b["time"] - a["time"] > max_gap for a, b in zip(result, result[1:])):
        raise ValueError("Funding coverage missing or interval exceeds registered BTC/ETH bound")
    return result


async def request(client, url, **kwargs):
    for attempt in range(4):
        try:
            response = await client.get(url, **kwargs)
            if response.status_code in (418, 429):
                delay = max(1, float(response.headers.get("Retry-After", "60")))
                raise RuntimeError(f"Research rate limited; retry after {delay}s")
            response.raise_for_status()
            return response
        except (httpx.TransportError, httpx.HTTPStatusError):
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt)


async def prepare(root=DATA_ROOT):
    root.mkdir(exist_ok=True, parents=True)
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        return load_manifest(root)
    spec = json.loads(SPEC_PATH.read_text())
    start, end = timestamp(spec["history_start"]), timestamp(spec["cutoff_exclusive"])
    archives = []
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        catalog = (await request(client, "https://fapi.binance.com/fapi/v1/exchangeInfo")).json()
        metadata = {}
        for symbol in spec["symbols"]:
            item = next(row for row in catalog["symbols"] if row["symbol"] == symbol)
            price = next(row for row in item["filters"] if row["filterType"] == "PRICE_FILTER")
            metadata[symbol] = {"price_filter": price, "as_of": datetime.now(timezone.utc).isoformat(), "historical": False}
        for symbol in spec["symbols"]:
            for timeframe in STEPS:
                for month in months(start, end):
                    filename = f"{symbol}-{timeframe}-{month}.zip"
                    url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{timeframe}/{filename}"
                    checksum = (await request(client, url + ".CHECKSUM")).text.split()[0]
                    if re.fullmatch(r"[a-fA-F0-9]{64}", checksum) is None:
                        raise ValueError("Invalid published checksum")
                    target = root / filename
                    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != checksum.lower():
                        response = await request(client, url)
                        if hashlib.sha256(response.content).hexdigest() != checksum.lower():
                            raise ValueError("Downloaded archive checksum mismatch")
                        target.write_bytes(response.content)
                    count, first, previous = 0, None, None
                    for bar in archive_bars(target, timeframe):
                        if first is None:
                            first = bar.open_time
                        if previous is not None and bar.open_time != previous + STEPS[timeframe]:
                            raise ValueError("Noncontiguous monthly archive")
                        previous, count = bar.open_time, count + 1
                    year, number = map(int, month.split("-"))
                    expected_start = timestamp(month + "-01")
                    expected_end = expected_start + calendar.monthrange(year, number)[1] * 86_400_000
                    if first != expected_start or previous + STEPS[timeframe] != expected_end:
                        raise ValueError("Incomplete monthly archive")
                    archives.append({"symbol": symbol, "timeframe": timeframe, "file": filename, "url": url,
                                     "checksum_url": url + ".CHECKSUM", "sha256": checksum.lower(), "rows": count,
                                     "start": first, "end_exclusive": expected_end})
                    print(f"Verified {filename}: {count} rows", flush=True)
        funding = {}
        evaluation_start = timestamp(spec["partitions"][0]["start"])
        for symbol in spec["symbols"]:
            rows, cursor = [], evaluation_start - 28_800_000
            while cursor < end:
                page = (await request(client, "https://fapi.binance.com/fapi/v1/fundingRate", params={"symbol": symbol, "startTime": cursor, "endTime": end - 1, "limit": 1000})).json()
                if not page:
                    break
                if page[-1]["fundingTime"] < cursor:
                    raise ValueError("Funding pagination did not advance")
                rows.extend(page)
                cursor = page[-1]["fundingTime"] + 1
            parsed = parse_funding(rows, symbol, evaluation_start, end)
            filename = f"{symbol}-funding.json"
            content = json.dumps(parsed, separators=(",", ":")).encode()
            (root / filename).write_bytes(content)
            funding[symbol] = {"file": filename, "sha256": hashlib.sha256(content).hexdigest(), "events": len(parsed),
                               "source": "https://fapi.binance.com/fapi/v1/fundingRate", "start": evaluation_start, "end_exclusive": end}
        manifest = {"schema": 1, "venue": "Binance USD-M perpetual", "symbols": spec["symbols"], "start": start, "end_exclusive": end,
                    "retrieved_at": datetime.now(timezone.utc).isoformat(), "spec_hash": canonical_hash(spec), "archives": archives,
                    "funding": funding, "metadata": metadata, "limitations": [spec["historical_filters"], "Monthly archives may be corrected later; this run pins their downloaded SHA-256."]}
        manifest["dataset_hash"] = canonical_hash(manifest)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def load_manifest(root=DATA_ROOT):
    manifest = json.loads((root / "manifest.json").read_text())
    payload = {k: v for k, v in manifest.items() if k != "dataset_hash"}
    if canonical_hash(payload) != manifest["dataset_hash"]:
        raise ValueError("Manifest checksum mismatch")
    for item in [*manifest["archives"], *manifest["funding"].values(), *([manifest["canonical_overrides"]] if manifest.get("canonical_overrides") else [])]:
        verified_path(root, item)
    return manifest


def canonicalize(root=DATA_ROOT):
    """Keep checksum-pinned native archives; document all differences from raw-minute aggregates."""
    manifest = load_manifest(root)
    spec = json.loads(SPEC_PATH.read_text())
    if manifest.get("source_policy") == spec["source_policy"] and manifest["spec_hash"] == canonical_hash(spec):
        return manifest
    if manifest["symbols"] != spec["symbols"] or manifest["start"] != timestamp(spec["history_start"]) or manifest["end_exclusive"] != timestamp(spec["cutoff_exclusive"]):
        raise ValueError("Existing archive range does not match research specification")
    corrections = []
    count = 0
    def values(bar):
        return {"open_time": bar.open_time, "close_time": bar.close_time, **{key: str(getattr(bar, key)) for key in ("open", "high", "low", "close", "volume")}}
    with localcontext() as context:
        context.prec = 34
        for symbol in manifest["symbols"]:
            # Native comparison always bypasses any previously recorded overrides.
            native_manifest = {key: value for key, value in manifest.items() if key != "canonical_overrides"}
            native = {timeframe: {bar.open_time: bar for bar in stream_bars(root, native_manifest, symbol, timeframe)} for timeframe in ("1h", "4h")}
            groups = {}
            expected = manifest["start"]
            for bar in stream_bars(root, manifest, symbol, "1m"):
                if bar.open_time != expected:
                    raise ValueError("Canonical minute history is incomplete")
                expected += 60_000
                count += 1
                for timeframe in ("1h", "4h"):
                    step = STEPS[timeframe]
                    if bar.open_time % step == 0:
                        groups[timeframe] = [bar.open, bar.high, bar.low, bar.close, Decimal(0)]
                    group = groups[timeframe]
                    group[1], group[2], group[3], group[4] = max(group[1], bar.high), min(group[2], bar.low), bar.close, group[4] + bar.volume
                    if (bar.open_time + 60_000) % step == 0:
                        opening = bar.open_time // step * step
                        canonical = Bar(opening, opening + step - 1, *group)
                        canonical.validate(timeframe)
                        original = native[timeframe].get(opening)
                        if original is None:
                            raise ValueError("Native comparison candle missing")
                        if any(getattr(original, key) != getattr(canonical, key) for key in ("open", "high", "low", "close", "volume")):
                            corrections.append({"symbol": symbol, "timeframe": timeframe, "open_time": opening, "native": values(original), "canonical": values(canonical),
                                                "reason": "Native archive disagrees with completed raw-minute aggregation; raw-minute source policy registered before performance results"})
            if expected != manifest["end_exclusive"]:
                raise ValueError("Canonical minute history has incomplete tail")
            print(f"Audited raw-minute aggregation for {symbol}", flush=True)
    filename = "canonical-overrides.json"
    content = json.dumps(corrections, indent=2).encode()
    (root / filename).write_bytes(content)
    if not (root / "manifest-native.json").exists():
        (root / "manifest-native.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    manifest.pop("dataset_hash", None)
    manifest.update({"source_policy": spec["source_policy"], "spec_hash": canonical_hash(spec),
                     "canonical_overrides": {"file": filename, "sha256": hashlib.sha256(content).hexdigest(), "discrepancies": len(corrections)},
                     "minute_source_audit": {"rows": count, "all_groups_complete": True, "native_discrepancies": len(corrections)}})
    manifest["limitations"].append("Native higher-timeframe archives disagree with raw-minute aggregation in recorded periods; canonical overrides are explicit, not proof of tick-level truth.")
    manifest["dataset_hash"] = canonical_hash(manifest)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Canonical dataset pinned: {len(corrections)} recorded source discrepancies", flush=True)
    return manifest


if __name__ == "__main__":
    asyncio.run(prepare())
