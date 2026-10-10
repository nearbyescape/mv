"""Offline bounded acquisition worklist for V5's frozen 30-symbol dataset.

This is a read-only *planner*, not a downloader or trading simulator. Every
proposal is executable through the existing one-symbol, one-timeframe,
six-month-limited v5_archive_batch CLI after explicit operator approval.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import shlex

from .v5_archive_inventory import inspect_one, months_for_spec
from .v5_archives import archive_plan, load_spec, valid_research_root

PHASES = ("pilot", "development", "validation", "holdout", "full")
STAGES = {
    "foundation": ("1h", "4h"),
    "trigger": ("15m",),
    "execution": ("1m",),
}
MAX_JOBS = 3
MAX_MONTHS_PER_JOB = 6
LEDGER_SIZE_LIMIT = 8 * 1024 * 1024


def phase_months(spec: dict, phase: str) -> list[str]:
    """Use frozen partitions, not performance-dependent date choices."""
    all_months = months_for_spec(spec)
    if phase == "full":
        return all_months
    if phase == "pilot":
        return [m for m in all_months if "2026-01" <= m <= "2026-06"]
    name = {
        "development": "development",
        "validation": "validation",
        "holdout": "untouched_holdout",
    }.get(phase)
    if name is None:
        raise ValueError("Invalid worklist phase")
    part = next((p for p in spec["partitions"] if p["name"] == name), None)
    if part is None:
        raise ValueError("Research partition missing from frozen spec")
    return [m for m in all_months if part["start"][:7] <= m < part["end"][:7]]


def publisher_404_evidence(root: Path, spec_sha: str) -> set[tuple[str, str, str]]:
    """An earlier publisher 404 is a blocking review item, not listing evidence.

    Ledgers are append-only, but missing files remain missing until separately
    investigated. Archives already present are evaluated by inspect_one.
    """
    ledger_dir = root / "batch-ledgers"
    blocked = set()
    if not ledger_dir.exists():
        return blocked
    if not ledger_dir.is_dir():
        raise ValueError("Batch ledger location is not a directory")
    for path in sorted(ledger_dir.glob("*.jsonl")):
        if not path.is_file() or path.is_symlink():
            raise ValueError("Batch ledger must be a regular non-symlinked file")
        if path.stat().st_size > LEDGER_SIZE_LIMIT:
            raise ValueError("Oversized batch ledger requires operator review")
        with path.open(encoding="utf-8") as stream:
            for lineno, raw in enumerate(stream, start=1):
                if not raw.strip():
                    raise ValueError(f"Blank or incomplete audit ledger entry: {path.name}:{lineno}")
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Malformed audit ledger: {path.name}:{lineno}") from exc
                if not isinstance(event, dict):
                    raise ValueError(f"Non-object audit ledger event: {path.name}:{lineno}")
                if event.get("spec_sha256") != spec_sha:
                    continue
                if event.get("status") == "SOURCE_HTTP_404_REQUIRES_REVIEW":
                    key = (event.get("symbol"), event.get("timeframe"), event.get("month"))
                    if any(not isinstance(value, str) for value in key):
                        raise ValueError("Publisher 404 ledger event lacks source identity")
                    blocked.add(key)
    return blocked


def _job(
    root: Path, symbol: str, timeframe: str, months: list[str],
    *,
    max_new_mib: int, min_free_mib: int,
) -> dict:
    first, last = months[0], months[-1]
    common = [
        "python", "-m", "app.research.v5_archive_batch",
        "plan", "--root", str(root),
        "--symbol", symbol, "--timeframe", timeframe,
        "--start-month", first, "--end-month", last,
    ]
    fetch = common.copy()
    fetch[3] = "fetch"
    fetch += [
        "--max-new-mib", str(max_new_mib),
        "--min-free-mib", str(min_free_mib),
        "--confirm-fetch",
    ]
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "months": months,
        "archive_cells": len(months),
        "status": "REQUIRES_EXPLICIT_OPERATOR_REVIEW",
        "plan_command": shlex.join(common),
        "fetch_command": shlex.join(fetch),
    }


def make_worklist(
    root: Path, spec: dict, spec_sha: str, *,
    stage: str = "foundation",
    phase: str = "pilot",
    symbols: list[str] | None = None,
    max_jobs: int = 2,
    max_months_per_job: int = 6,
    max_new_mib: int = 64,
    min_free_mib: int = 2048,
) -> dict:
    """Plan small serial work units, never access performance or publisher HTTP."""
    if stage not in STAGES:
        raise ValueError("Unsupported acquisition stage")
    if phase not in PHASES:
        raise ValueError("Unsupported archive calendar phase")
    if not 1 <= max_jobs <= MAX_JOBS:
        raise ValueError("At most three proposed work units per invocation")
    if not 1 <= max_months_per_job <= MAX_MONTHS_PER_JOB:
        raise ValueError("At most six months per work unit")
    if not 1 <= max_new_mib <= 256 or min_free_mib < 1:
        raise ValueError("Invalid bounded fetch budget")
    if not root.is_dir():
        raise FileNotFoundError("Research archive root must already exist")
    symbols = list(spec["symbols"]) if symbols is None else list(symbols)
    if not symbols or len(set(symbols)) != len(symbols) or any(
        sym not in spec["symbols"] for sym in symbols
    ):
        raise ValueError("Worklist symbols must be unique and in frozen universe")
    months = phase_months(spec, phase)
    quarantined = publisher_404_evidence(root, spec_sha)
    counts = Counter()
    issues = []
    jobs = []
    # Symbol-major order completes the two foundation frames for each market
    # before going to the next one. Stable ordering makes repeat plans identical.
    for symbol in symbols:
        for timeframe in STAGES[stage]:
            missing_months = []
            for month in months:
                plan = archive_plan(spec, symbol, timeframe, month)
                cell = inspect_one(root, plan, spec_sha)
                key = (symbol, timeframe, month)
                if cell["status"] == "MISSING" and key in quarantined:
                    cell.update(
                        status="REVIEW_REQUIRED",
                        reason="PREVIOUS_PUBLISHER_404_NOT_INCEPTION_PROOF",
                    )
                counts[cell["status"]] += 1
                if cell["status"] == "REVIEW_REQUIRED":
                    issues.append(cell)
                if cell["status"] == "MISSING":
                    missing_months.append(month)
                elif missing_months:
                    if len(jobs) < max_jobs:
                        for offset in range(0, len(missing_months), max_months_per_job):
                            if len(jobs) >= max_jobs:
                                break
                            jobs.append(_job(
                                root, symbol, timeframe,
                                missing_months[offset:offset + max_months_per_job],
                                max_new_mib=max_new_mib,
                                min_free_mib=min_free_mib,
                            ))
                    missing_months = []
            if missing_months and len(jobs) < max_jobs:
                for offset in range(0, len(missing_months), max_months_per_job):
                    if len(jobs) >= max_jobs:
                        break
                    jobs.append(_job(
                        root, symbol, timeframe,
                        missing_months[offset:offset + max_months_per_job],
                        max_new_mib=max_new_mib,
                        min_free_mib=min_free_mib,
                    ))
    status = "REVIEW_REQUIRED" if issues else (
        "INCOMPLETE" if counts["MISSING"] else "ARCHIVES_PRESENT_NOT_DEEP_VERIFIED"
    )
    return {
        "schema": 1,
        "status": status,
        "stage": stage,
        "phase": phase,
        "symbols": symbols,
        "timeframes": list(STAGES[stage]),
        "months": months,
        "expected_archive_cells": len(symbols) * len(STAGES[stage]) * len(months),
        "counts": {
            k: counts[k]
            for k in ("MISSING", "PRESENT_UNVERIFIED", "VERIFIED", "REVIEW_REQUIRED")
        },
        "blocking_issues": issues[:30],
        "blocking_issue_count": len(issues),
        "proposed_jobs": [] if issues else jobs,
        "source_spec_sha256": spec_sha,
        "warning": (
            "PLAN ONLY: never auto-download, infer prelisting from 404, classify "
            "present manifests as deep-verified, or evaluate validation/holdout P&L. "
            "Run individual plan/fetch commands in the isolated archive-writable "
            "research container only after resource and venue review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline, bounded V5 30-coin archive worklist")
    parser.add_argument("--root", required=True)
    parser.add_argument("--stage", choices=STAGES, default="foundation")
    parser.add_argument("--phase", choices=PHASES, default="pilot")
    parser.add_argument("--symbol", action="append",
                        help="Repeated optional frozen symbol; default all 30")
    parser.add_argument("--max-jobs", type=int, default=2)
    parser.add_argument("--max-months-per-job", type=int, default=6)
    parser.add_argument("--max-new-mib", type=int, default=64)
    parser.add_argument("--min-free-mib", type=int, default=2048)
    args = parser.parse_args()
    spec, digest = load_spec()
    result = make_worklist(
        valid_research_root(args.root), spec, digest,
        stage=args.stage, phase=args.phase, symbols=args.symbol,
        max_jobs=args.max_jobs, max_months_per_job=args.max_months_per_job,
        max_new_mib=args.max_new_mib, min_free_mib=args.min_free_mib,
    )
    print(json.dumps(result, sort_keys=True, indent=2))
    if result["blocking_issue_count"]:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
