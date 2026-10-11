"""Prospective T7Sonic source adapter: separate June-August path, locked.

Never run this on genuine holdout archives unless the operator has completed
and recorded independent prior-exposure auditing and a separately reviewed
validation protocol. No CLI entrypoint, order logic, Telegram, model tuning
or future-outcome labeling is included. Its tests use synthetic archives.

The April-May replay and expert modules are imported unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .t7sonic_history import (
    FROZEN_MARKETS, HISTORICAL_FRAMES, INTERVAL_MS, OBSERVATION_BARS,
    RECONCILIATION_MINUTE_BARS, _necessary_first_ms,
    _calendar_months, _source_location, _verify_month,
)
from .t7sonic_replay import _as_of
from .t7sonic_perception import perceive_symbol
from .t7sonic_validation_plan import (
    START, END, MARKETS, STRATEGY_SHA, frozen_plan,
)

STEP = INTERVAL_MS["5m"]
MAX_BOUNDARIES = 288
APPROVAL_STATE = "INDEPENDENTLY_AUDITED_CLEAN_APPROVED"
PLAN_SHA = frozen_plan()["frozen_plan_sha256"]


def validation_boundaries(day: str, *, maximum: int = MAX_BOUNDARIES) -> tuple[int, ...]:
    """Exact fixed evaluation days only; future boundaries never leak into features."""
    if not isinstance(day, str):
        raise ValueError("UTC validation day is required")
    try:
        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid ISO UTC validation day") from exc
    if dt.strftime("%Y-%m-%d") != day or not START <= dt.date() <= END:
        raise ValueError("Outside frozen independent validation window")
    if type(maximum) is not int or not 1 <= maximum <= MAX_BOUNDARIES:
        raise ValueError("Exactly 1..288 completed 5m cutoffs required")
    first = int(dt.timestamp() * 1000)
    return tuple(first + (i + 1) * STEP for i in range(maximum))


def _safe_root(root: Path) -> None:
    if (not isinstance(root, Path) or not root.is_absolute() or
            root.is_symlink() or not root.is_dir()):
        raise ValueError("Existing absolute non-symlink archive root required")


def presence_only(root: Path, symbol: str, day: str, *,
                  maximum: int = MAX_BOUNDARIES) -> dict:
    """File-name existence preflight, NEVER opens the source archive or manifest."""
    _safe_root(root)
    if symbol not in MARKETS:
        raise ValueError("Symbol excluded by frozen six-market selection")
    times = validation_boundaries(day, maximum=maximum)
    expected = []
    missing = []
    for frame in HISTORICAL_FRAMES:
        begin, _ = _necessary_first_ms(frame, times[0])
        end = (times[-1] // INTERVAL_MS[frame]) * INTERVAL_MS[frame]
        if end <= begin:
            raise ValueError("Incomplete warmup interval")
        for month in _calendar_months(begin, end):
            zip_path, manifest = _source_location(root, symbol, frame, month)
            if any(x.is_symlink() for x in (
                    root / "archives", root / "archives" / symbol,
                    zip_path.parent, zip_path, manifest)):
                raise ValueError("Symlink in source archive ancestry")
            pair = {
                "frame": frame, "month": month,
                "zip_present": zip_path.is_file(),
                "manifest_present": manifest.is_file(),
            }
            expected.append(pair)
            if not pair["zip_present"] or not pair["manifest_present"]:
                missing.append(pair)
    return {
        "action": "PRESENCE_ONLY_NEVER_OPENS_MARKET_SOURCE",
        "locked_plan_sha256": PLAN_SHA,
        "candidate_source_revision": STRATEGY_SHA,
        "symbol": symbol, "day": day,
        "requested_boundaries": len(times),
        "expected_month_pairs": expected,
        "missing_month_pairs": missing,
        "integrity_verified": False,
        "market_data_opened": False,
        "trading_authorized": False,
    }


def _require_clean_authorization(authorization: dict) -> None:
    """Fail closed; the human audit itself MUST occur outside this adapter.

    Fields are procedural controls, not proof a prior exposure never happened.
    """
    if (not isinstance(authorization, dict) or
            authorization.get("plan_sha256") != PLAN_SHA or
            authorization.get("state") != APPROVAL_STATE or
            authorization.get("strategy_sha") != STRATEGY_SHA or
            authorization.get("independent_exposure_reviewed") is not True or
            authorization.get("reserved_final_test_window") is not True or
            not isinstance(authorization.get("auditor"), str) or
            not authorization["auditor"].strip() or
            not isinstance(authorization.get("evidence_reference"), str) or
            not authorization["evidence_reference"].strip()):
        raise PermissionError(
            "Holdout blocked: independent exposure attestation and sealed final test required"
        )


def verified_source_window(root: Path, symbol: str, day: str,
                           authorization: dict, *,
                           maximum: int = MAX_BOUNDARIES) -> tuple[dict, dict]:
    """Full calendar/sidecar digest validation, then as-of-only source windows.

    Does not claim direct publisher .CHECKSUM validation: an independent
    external audit must authenticate the sidecar publisher digest first.
    """
    _require_clean_authorization(authorization)
    preflight = presence_only(root, symbol, day, maximum=maximum)
    if preflight["missing_month_pairs"]:
        raise FileNotFoundError("Required full-month archive/sidecar pair missing")
    times = validation_boundaries(day, maximum=maximum)
    loaded = {}
    proofs = {}
    for frame in HISTORICAL_FRAMES:
        step = INTERVAL_MS[frame]
        begin, _ = _necessary_first_ms(frame, times[0])
        end = (times[-1] // step) * step
        expected = (end - begin) // step
        chunks, frame_proofs = [], []
        for month in _calendar_months(begin, end):
            bars, proof = _verify_month(
                root, symbol, frame, month, begin, end, expected
            )
            chunks.extend(bars)
            frame_proofs.append(proof)
        if (len(chunks) != expected or not chunks or
                chunks[0].open_ms != begin or
                chunks[-1].open_ms + step != end or
                any(b.open_ms - a.open_ms != step
                    for a, b in zip(chunks, chunks[1:]))):
            raise ValueError("Source timeline incomplete or internally inconsistent")
        loaded[frame] = chunks
        proofs[frame] = frame_proofs
    # Strict as-of invariant at beginning and end; repeat for all 5m
    # boundaries later in the sealed validation replay implementation.
    first = _as_of(loaded, symbol, times[0])
    last = _as_of(loaded, symbol, times[-1])
    for event, when in ((first, times[0]), (last, times[-1])):
        p = perceive_symbol(event["snapshot"])
        if p["as_of_ms"] != when:
            raise ValueError("Unexpected feature observation time")
        for frame, bars in event["snapshot"]["bars"].items():
            step = INTERVAL_MS[frame]
            if not bars or bars[-1]["open_ms"] + step > when:
                raise ValueError("Future bar entered causal snapshot")
    return {
        "first_boundary_ms": times[0],
        "last_boundary_ms": times[-1],
        "first_snapshot": first["snapshot"],
        "last_snapshot": last["snapshot"],
    }, {
        "source_proofs": proofs,
        "reconciliation_first": first["reconciliation"],
        "reconciliation_last": last["reconciliation"],
        "holdout_candidate_only": True,
        "training_or_labeling_done": False,
        "publisher_checksum_requires_separate_audit": True,
        "signal_published": False,
        "order_submitted": False,
    }
