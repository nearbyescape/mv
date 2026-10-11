"""Read-only T7Sonic market perception and expert research CLI.

Usage:
  python -m app.research.t7sonic_cli --input /research/verified_snapshot.json

Input is a user-created, as-of snapshot and is NOT trusted simply because
a JSON file exists. No exchange network calls, signal publishing, DB changes,
broker interaction or background tasks are performed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .t7sonic_perception import perceive_symbol
from .t7sonic_experts import research_market

MAX_FILE_SIZE = 20 * 1024 * 1024


def run_offline_snapshot(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"schema", "snapshots"}:
        raise ValueError("Expected exactly schema and snapshots")
    if payload["schema"] != 1 or type(payload["schema"]) is not int:
        raise ValueError("T7Sonic snapshot schema must be 1")
    raw = payload["snapshots"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
        raise ValueError("Require 1–30 explicitly named market snapshots")
    perceptions = [perceive_symbol(s) for s in raw]
    result = research_market(perceptions)
    result["evidence"] = {
        "source_sha256_by_market": {
            p["symbol"]:p["feature_source_sha256"] for p in perceptions
        },
        "source_verification": "NOT_PERFORMED_UPSTREAM_ARCHIVE_VERIFICATION_REQUIRED",
        "historical_source_as_of_guarantee": (
            "COMPLETED_CANDLES_AND_CROSS_MARKET_BOUNDARY_VALIDATED_FROM_INPUT"
        ),
        "live_market_data_access": False,
        "deployment_permission": False,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T7Sonic isolated closed-candle research preview; no signals"
    )
    parser.add_argument("--input", required=True, help="Verified offline snapshot JSON")
    args = parser.parse_args()
    file = Path(args.input)
    if not file.is_file() or file.is_symlink():
        parser.error("Input must be an existing regular non-symlink JSON file")
    if file.stat().st_size > MAX_FILE_SIZE:
        parser.error("Input JSON file too large for bounded research")
    payload = json.loads(file.read_text(encoding="utf-8"))
    print(json.dumps(run_offline_snapshot(payload), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
