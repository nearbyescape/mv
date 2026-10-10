"""Fast read-only coverage preflight for V6HBR directional research archives.

This checks expected *file presence only*, not ZIP SHA, manifest provenance
or OHLCV continuity. The actual directional study independently performs
full SHA/manifest/continuity checks before calculating any score.
Never substitute this inventory for full source validation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .v5_archives import archive_location, archive_plan, load_spec, valid_research_root

FRAMES = ("15m", "1h", "4h")
MONTHS = ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05")
EXPECTED = 30 * len(FRAMES) * len(MONTHS)


def archive_inventory(root: Path, spec: dict) -> dict:
    symbols = spec.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 30 or len(set(symbols)) != 30:
        raise ValueError("Expected frozen 30-symbol universe")
    if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir():
        raise ValueError("Existing absolute archive root required")
    ready, missing = 0, []
    by_symbol = {}
    for symbol in symbols:
        have = 0
        absent = []
        for frame in FRAMES:
            for month in MONTHS:
                plan = archive_plan(spec, symbol, frame, month)
                zip_file, manifest = archive_location(root, plan)
                # Symlinks must not count as verified sources, even if a
                # symlink target is a regular file.
                zip_ok = zip_file.is_file() and not zip_file.is_symlink()
                manifest_ok = manifest.is_file() and not manifest.is_symlink()
                if zip_ok and manifest_ok:
                    have += 1
                else:
                    absent.append({
                        "timeframe": frame, "month": month,
                        "archive_present": zip_ok,
                        "manifest_present": manifest_ok,
                    })
        ready += have
        by_symbol[symbol] = {
            "present_archive_manifest_pairs": have,
            "required_pairs": len(FRAMES) * len(MONTHS),
            "ready_for_integrity_audit": not absent,
        }
        for item in absent:
            missing.append({"symbol": symbol, **item})
    if ready + len(missing) != EXPECTED:
        raise AssertionError("Internal source pair accounting mismatch")
    all_ok = ready == EXPECTED
    return {
        "status": (
            "ALL_ARCHIVE_MANIFEST_PAIRS_PRESENT_NEEDS_SHA_CONTINUITY_AUDIT"
            if all_ok else "INCOMPLETE_RESEARCH_ARCHIVE_COVERAGE"
        ),
        "frozen_universe_symbols": 30,
        "required_archive_manifest_pairs": EXPECTED,
        "present_archive_manifest_pairs": ready,
        "missing_archive_manifest_pairs": len(missing),
        "full_30_symbol_source_coverage": all_ok,
        "fully_present_symbol_count": sum(
            v["ready_for_integrity_audit"] for v in by_symbol.values()
        ),
        "by_symbol": by_symbol,
        "missing_examples_first_40": missing[:40],
        "note": "Presence is not SHA validation, continuity or a completed accuracy run",
    }


def main():
    parser = argparse.ArgumentParser(description="V6HBR 30-symbol offline archive coverage only")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = valid_research_root(args.root)
    spec, sha = load_spec()
    inventory = archive_inventory(root, spec)
    inventory["frozen_spec_sha256"] = sha
    print(json.dumps(inventory, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
