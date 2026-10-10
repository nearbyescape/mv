"""Offline 30-symbol development-only V6HBR directional signal study.

Reads Jan–May 2026 frozen-spec 15m/1h/4h monthly archives from the
isolated research volume, using the inherited checksum/continuity validators.
No network, no data acquisition, no DB, no Telegram and no execution.

Default requires all 30 frozen symbols. Explicit subset permitted only as
a *labelled smoke test*, never interpreted as full-universe evidence.
June–July validation and August–September holdout are not read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import timestamp
from .v5_archives import load_spec, valid_research_root
from .v5_archive_batch import batch_plan
from .v5_decision_replay import snapshots_from_pinned
from .v6hbr_candidate_export import export_events
from .v6hbr_directional_accuracy import (
    label_directional_events, directional_accuracy_study,
)

DEVELOPMENT_START = "2026-04-01"
DEVELOPMENT_END = "2026-06-01"
FRAMES = ("15m", "1h", "4h")


def select_symbols(spec: dict, requested: tuple[str, ...] | None) -> list[str]:
    frozen = list(spec["symbols"])
    if len(frozen) != 30 or len(set(frozen)) != 30:
        raise ValueError("Unreviewed frozen 30-market research contract")
    if requested is None:
        return frozen
    if not requested or len(set(requested)) != len(requested):
        raise ValueError("Explicit nonempty, unique subset required")
    if any(x not in frozen for x in requested):
        raise ValueError("Symbol absent from frozen research contract")
    return [x for x in frozen if x in requested]


def audit_symbol(root: Path, spec: dict, spec_sha: str, symbol: str) -> dict:
    maps, hashes = {}, {}
    for frame in FRAMES:
        plans = batch_plan(spec, symbol, frame, "2026-01", "2026-05")
        maps[frame], proof = snapshots_from_pinned(root, plans, spec_sha)
        hashes[frame] = proof["canonical_series_sha256"]
    events = export_events(
        maps, symbol, timestamp(DEVELOPMENT_START), timestamp(DEVELOPMENT_END)
    )
    labeled = label_directional_events(
        events["events"], maps["15m"], maps["1h"],
        end_exclusive_ms=timestamp(DEVELOPMENT_END)
    )
    if len(labeled) != events["candidates"]:
        raise ValueError("Missing directional label for an original candidate")
    return {
        "symbol": symbol,
        "source_series_sha256": hashes,
        "candidate_stream_sha256": events["export_stream_sha256"],
        "candidate_count": events["candidates"],
        "v4_base": events["v4_base"],
        "15m_rescue": events["15m_rescue"],
        "labeled": labeled,
    }


def study_development(
    root: Path, *, requested_symbols: tuple[str, ...] | None = None
) -> dict:
    spec, spec_sha = load_spec()
    symbols = select_symbols(spec, requested_symbols)
    labeled, sources = [], {}
    for symbol in symbols:
        result = audit_symbol(root, spec, spec_sha, symbol)
        labeled.extend(result.pop("labeled"))
        sources[symbol] = result
    report = directional_accuracy_study(labeled)
    return {
        "schema": 1,
        "status": "APRIL_MAY_DIRECTIONAL_ACCURACY_AUDIT_NOT_SIGNAL_TRADE_PNL",
        "archive_contract_sha256": spec_sha,
        "research_partition": "DEVELOPMENT_ONLY",
        "candidate_window": "2026-04-01T00:00:00Z..2026-06-01T00:00:00Z",
        "run_scope": "ALL_30_FROZEN_SYMBOLS" if requested_symbols is None
                     else "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE",
        "requested_symbols": symbols,
        "omitted_symbols": [s for s in spec["symbols"] if s not in symbols],
        "complete_symbol_count": len(sources),
        "per_symbol_source_provenance": sources,
        "directional_accuracy": report,
        "limitations": [
            "No live V4 outcome evidence from October 2026 is used",
            "Validation and sealed holdout data are not accessed",
            "Full research scope requires all 30 symbols and every verified archive",
            "An accurate direction label does not prove executable or profitable entry",
            "Single-symbol smoke studies must not be presented as all-market results",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline 30-symbol development-only direction study")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbols", help="Comma-separated smoke-only symbol subset")
    args = parser.parse_args()
    selected = None
    if args.symbols is not None:
        selected = tuple(x.strip() for x in args.symbols.split(","))
        if not selected or any(not x for x in selected):
            parser.error("Nonempty comma-separated symbols required")
    root = valid_research_root(args.root)
    print(json.dumps(
        study_development(root, requested_symbols=selected),
        sort_keys=True, indent=2,
    ))


if __name__ == "__main__":
    main()
