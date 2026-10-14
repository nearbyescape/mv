"""Explicit, bounded public monthly data acquisition for OFFLINE V7 research.

Default performs NO HTTP. When explicitly enabled, only publisher-hosted
Binance Futures USD-M 15m monthly ZIP and .CHECKSUM are downloaded. This
is neither a live signal feed nor independently signed exchange evidence.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

from .v7_recovery_archives import (
    MARKETS, MONTHS, MAX_ZIP, monthly_paths, validate_checksum,
)

HOST = "https://data.binance.vision"
MAX_CHECKSUM = 256


def _http_get(url: str, limit: int) -> bytes:
    if not url.startswith(HOST + "/data/futures/um/monthly/klines/"):
        raise ValueError("Forbidden historical data URL")
    req = Request(url, method="GET", headers={"Accept": "application/octet-stream"})
    with urlopen(req, timeout=25) as response:
        if response.status != 200 or response.url.split("?")[0] != url:
            raise ValueError("Redirect or unexpected publisher response")
        data = response.read(limit + 1)
    if not 32 <= len(data) <= limit:
        raise ValueError("Incomplete/oversized published response")
    return data


def acquire(root: Path, symbols: tuple[str, ...], months: tuple[str, ...], *,
            enabled: bool = False) -> dict:
    if (not isinstance(root, Path) or not root.is_absolute() or root.is_symlink()
            or not symbols or len(symbols) != len(set(symbols))
            or any(s not in MARKETS for s in symbols)
            or not months or len(months) != len(set(months))
            or tuple(sorted(months)) != months
            or any(m not in MONTHS for m in months)):
        raise ValueError("Explicit absolute root, frozen markets/months required")
    if not enabled:
        return {
            "status": "NO_NETWORK_DATA_ACQUISITION_DISABLED",
            "archive_pairs_planned": len(months) * len(symbols),
            "target": str(root),
            "signals_published": 0, "orders_submitted": 0,
        }
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or root.stat().st_mode & 0o077:
        raise PermissionError("Archive root must be owner-private")
    observed = []
    for symbol in symbols:
        folder = root / symbol
        if folder.is_symlink():
            raise PermissionError("Symlink archive subfolder")
        folder.mkdir(mode=0o700, exist_ok=True)
        for month in months:
            dest, sidecar = monthly_paths(root, symbol, month)
            url = (HOST + "/data/futures/um/monthly/klines/"
                   + symbol + "/15m/" + dest.name)
            if dest.exists() or sidecar.exists():
                if not dest.is_file() or not sidecar.is_file() or (
                    dest.is_symlink() or sidecar.is_symlink()
                ):
                    raise ValueError("Partial or invalid pre-existing publisher source")
                from .v7_recovery_archives import verified_month
                _, proof = verified_month(root, symbol, month)
                observed.append({"symbol": symbol, "month": month,
                                 "zip_sha256": proof["zip_sha256"], "mode": "verified_existing"})
                continue
            checksum = _http_get(url + ".CHECKSUM", MAX_CHECKSUM)
            data = _http_get(url, MAX_ZIP)
            digest = sha256(data).hexdigest()
            validate_checksum(checksum, dest.name, digest)
            # Never leave an accepted ZIP without its matching sidecar.
            paths = []
            try:
                for payload, path in ((data, dest), (checksum, sidecar)):
                    fd, temp = tempfile.mkstemp(prefix=".v7partial-", dir=folder)
                    paths.append(Path(temp))
                    os.fchmod(fd, 0o600)
                    with os.fdopen(fd, "wb") as h:
                        h.write(payload)
                        h.flush()
                        os.fsync(h.fileno())
                if dest.exists() or sidecar.exists():
                    raise FileExistsError("Archive created concurrently")
                os.link(paths[0], dest, follow_symlinks=False)
                os.link(paths[1], sidecar, follow_symlinks=False)
            finally:
                for path in paths:
                    path.unlink(missing_ok=True)
            observed.append({"symbol": symbol, "month": month,
                             "zip_sha256": digest, "mode": "new_verified_download"})
    return {
        "status": "HISTORICAL_PUBLISHER_HOSTED_CHECKSUMS_VERIFIED_NOT_INDEPENDENT",
        "archive_pairs": len(observed),
        "sources": observed,
        "no_client_publication": True,
        "orders_submitted": 0,
    }


def main() -> None:
    p = argparse.ArgumentParser(description="V7 offline research archive acquisition")
    p.add_argument("--data-root", required=True)
    p.add_argument("--months", nargs="+", default=list(MONTHS))
    p.add_argument("--symbols", nargs="+", default=list(MARKETS))
    p.add_argument("--acquire", action="store_true")
    p.add_argument("--acknowledge-public-download")
    args = p.parse_args()
    if args.acquire and args.acknowledge_public_download != "YES":
        p.error("Real public HTTPS acquisition requires explicit --acknowledge-public-download YES")
    if not args.acquire and args.acknowledge_public_download:
        p.error("Do not supply download acknowledgement in no-network preflight")
    output = acquire(
        Path(args.data_root), tuple(args.symbols), tuple(args.months),
        enabled=args.acquire,
    )
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
