"""Deep read-only recertification of bounded V7Sonic PRIVATE paper pilots.

This verifies evidence integrity, all 31 original responses per accepted
cycle, source-attempt chains, six-market SQLite decisions, and contiguous
five-minute boundaries. It cannot authenticate unsigned exchange data,
independent wall-clock receipts, account balances, model edge, or permission
to publish client messages. Nothing is fetched, written, traded or sent.

Run in UID 10001 *network-none* container with /state mounted READ ONLY.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import stat

from app.v7sonic_readonly_audit import audit_one_stored_cycle
from services.t7sonic.replay_original_capture import replay_original

STEP_MS = 300_000
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
_MAX_ORIGINAL_BYTES = 8_000_000
_MAX_SUMMARY_BYTES = 100_000
_MAX_SMALL_BYTES = 20_000


def _read_regular(root: Path, name: str, size_limit: int) -> bytes:
    path = root / name
    if (path.parent != root or path.is_symlink() or not path.is_file() or
            not stat.S_ISREG(path.stat().st_mode) or
            not 1 <= path.stat().st_size <= size_limit):
        raise ValueError("Missing, symlinked or oversize paper evidence: " + name)
    return path.read_bytes()


def _evidence_file(root: Path, name: str, bound: int) -> dict:
    return json.loads(_read_regular(root, name, bound))


def _ensure_no_gaps(root: Path) -> None:
    bad = (
        "v7sonic-private-gap-*.json",
        "v7sonic-private-acquisition-gap-*.json",
    )
    for pattern in bad:
        if list(root.glob(pattern)):
            raise ValueError("One or more unclosed paper acquisition/scheduler GAPS")


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def recertify_pilot(state_dir: str | Path, *, expected_sha: str,
                    expected_boundaries: tuple[int, ...]) -> dict:
    if (not isinstance(expected_sha, str) or not HEX40.fullmatch(expected_sha)
            or not isinstance(expected_boundaries, tuple)
            or len(expected_boundaries) != 4
            or any(type(n) is not int or n % STEP_MS
                   for n in expected_boundaries)
            or any(b-a != STEP_MS for a, b in
                   zip(expected_boundaries, expected_boundaries[1:]))):
        raise ValueError("Exact source SHA and four consecutive boundaries required")
    root = Path(state_dir)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or root.stat().st_mode & 0o077):
        raise PermissionError("Existing owner-private evidence root mandatory")
    _ensure_no_gaps(root)
    for prefix in ("v7sonic-private-paper-cycle-",
                   "v7sonic-private-claim-"):
        found = {p.name for p in root.glob(prefix + "*.json")}
        wanted = {prefix + str(n) + ".json" for n in expected_boundaries}
        if found != wanted:
            raise ValueError("Missing or extra four-cycle claims or summaries")
    # Unwanted foreign acceptance records are not silently ignored.
    expected_source_files = set()
    expected_rejections = set()
    all_candidates = 0
    all_rejections = 0
    papers = []
    digest_manifest = []
    for boundary in expected_boundaries:
        claim = _evidence_file(
            root, f"v7sonic-private-claim-{boundary}.json", _MAX_SMALL_BYTES
        )
        if (claim.get("decision_boundary_ms") != boundary or
                claim.get("status") != "PRIVATE_PAPER_BOUNDARY_CLAIMED" or
                claim.get("client_publication_authorized") is not False or
                claim.get("telegram_enqueued") is not False or
                claim.get("orders_authorized") is not False):
            raise ValueError("Invalid or tradable paper claim")
        raw_summary = _read_regular(
            root, f"v7sonic-private-paper-cycle-{boundary}.json",
            _MAX_SUMMARY_BYTES,
        )
        summary = json.loads(raw_summary)
        attempts = summary.get("source_attempts")
        if (not isinstance(attempts, list) or
                not 1 <= len(attempts) <= 3 or
                summary.get("attempt_count") != len(attempts)):
            raise ValueError("Incomplete paper source attempt chain")
        for idx, item in enumerate(attempts, 1):
            expected_name = (
                f"v7sonic-original-http-{boundary}" +
                ("" if idx == 1 else f"-attempt-{idx}") + ".json"
            )
            expected_source_files.add(expected_name)
            if (not isinstance(item, dict) or item.get("attempt") != idx
                    or Path(str(item.get("original_http_file", ""))).name != expected_name
                    or not isinstance(item.get("original_http_sha256"), str)
                    or not HEX64.fullmatch(item["original_http_sha256"])):
                raise ValueError("Unsealed original source attempt record")
            raw = _read_regular(root, expected_name, _MAX_ORIGINAL_BYTES)
            if _sha(raw) != item["original_http_sha256"]:
                raise ValueError("Tampered original 31-body source attempt")
            source = json.loads(raw)
            forensic = replay_original(source)
            if (forensic.get("original_http_responses_hash_checked") != 31
                    or forensic.get("decision_boundary_ms") != boundary):
                raise ValueError("Original source not internally verifiable")
            if idx < len(attempts):
                name = f"v7sonic-private-rejected-{boundary}-{idx}.json"
                expected_rejections.add(name)
                rejected = _evidence_file(root, name, _MAX_SMALL_BYTES)
                if (rejected.get("original_http_sha256") != _sha(raw)
                        or rejected.get("retry_eligible") is not True
                        or rejected.get("attempt") != idx
                        or rejected.get("status") != "PRIVATE_PAPER_ANALYSIS_REJECTED"
                        or rejected.get("client_publication_authorized") is not False
                        or rejected.get("telegram_enqueued") is not False
                        or rejected.get("orders_authorized") is not False
                        or rejected.get("retry_classification") not in (
                            "EXACT_CROSS_RESOLUTION_RECONCILIATION",
                            "BOUNDED_PREBOUNDARY_EXCHANGE_BOOK_EVENT",
                        )):
                    raise ValueError("Invalid original attempt rejection proof")
                all_rejections += 1
                if (rejected["retry_classification"] ==
                        "EXACT_CROSS_RESOLUTION_RECONCILIATION" and
                        forensic["exact_reconciliation_passed"] is True):
                    raise ValueError("Claimed cross-resolution retry without mismatch")
            elif forensic["exact_reconciliation_passed"] is not True:
                raise ValueError("Accepted attempt is cross-resolution inconsistent")
        final_digest = attempts[-1]["original_http_sha256"]
        if summary.get("last_original_http_sha256") != final_digest:
            raise ValueError("Final accepted source not the last acquired attempt")
        audited = audit_one_stored_cycle(
            root, boundary_ms=boundary,
            summary_sha256=_sha(raw_summary),
            original_sha256=final_digest,
            batch_sha256=summary.get("paper_batch_sha256"),
        )
        count = len(audited["candidates"])
        all_candidates += count
        papers.append({"boundary_ms": boundary,
                       "attempts": len(attempts), "candidates": count,
                       "no_candidate_reasons": audited["noncandidates"],
                       "summary_sha256": _sha(raw_summary),
                       "source_sha256": final_digest,
                       "batch_sha256": summary["paper_batch_sha256"]})
        digest_manifest.append(f"{boundary}:{_sha(raw_summary)}:{final_digest}:{summary['paper_batch_sha256']}")
    if {p.name for p in root.glob("v7sonic-original-http-*.json")} != expected_source_files:
        raise ValueError("Missing or extraneous original source attempts")
    if {p.name for p in root.glob("v7sonic-private-rejected-*.json")} != expected_rejections:
        raise ValueError("Orphan/extra source rejection receipt")
    return {
        "status": "V7_FOUR_BOUNDARY_PRIVATE_PAPER_LOCAL_RECERTIFICATION_PASS",
        "exact_source_sha_operator_pin": expected_sha,
        "completed_cycles": 4,
        "market_decisions_audited": 24,
        "accepted_original_http_bodies_verified": 4 * 31,
        "rejected_source_attempts_hash_verified": all_rejections,
        "indicative_candidate_count": all_candidates,
        "cycles": papers,
        "local_digests_manifest_sha256": _sha(
            ("\n".join(digest_manifest) + "\n").encode()
        ),
        "off_server_sha_attestation_verified": False,
        "independent_market_timestamp_attestation_verified": False,
        "model_profitability_or_accuracy_certified": False,
        "production_account_or_positions_authenticated": False,
        "production_cutover_certified": False,
        "telegram_messages_sent": 0,
        "orders_submitted": 0,
    }


def main() -> None:
    p = argparse.ArgumentParser(
        description="Offline FOUR-cycle source+SQLite forensic; NEVER LIVE SEND"
    )
    p.add_argument("--state-dir", required=True)
    p.add_argument("--expected-sha", required=True)
    p.add_argument("--first-boundary-ms", type=int, required=True)
    args = p.parse_args()
    start = args.first_boundary_ms
    print(json.dumps(
        recertify_pilot(args.state_dir, expected_sha=args.expected_sha,
                        expected_boundaries=tuple(start+i*STEP_MS
                                                  for i in range(4))),
        indent=2, sort_keys=True
    ))


if __name__ == "__main__":
    main()
