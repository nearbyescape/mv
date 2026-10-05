"""Read-only, checksum-verified research artifacts. No client-controlled filesystem paths."""
import hashlib
import json
from pathlib import Path
import re

from mv_strategy.signals import canonical_hash

REPORT_ROOT = Path(__file__).resolve().parents[4] / "artifacts/backtests"
FILES = {"report.json": "application/json", "dataset-manifest.json": "application/json", "source-audit.json": "application/json", "trades.csv": "text/csv", "trades.jsonl": "application/x-ndjson"}
STUDY_ROOT = REPORT_ROOT.parent / "exit-studies"
FILTER_ROOT = REPORT_ROOT.parent / "filter-studies"


def read_report(root=None):
    root = root or REPORT_ROOT
    pointer = root / "latest.json"
    if not pointer.exists():
        return None
    latest = json.loads(pointer.read_text())
    if not isinstance(latest.get("id"), str) or not re.fullmatch(r"[a-f0-9]{64}", latest["id"]):
        raise ValueError("Invalid research report pointer")
    path = (root / latest["id"] / "report.json").resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Research artifact outside report root")
    report = json.loads(path.read_text())
    payload = {key: value for key, value in report.items() if key != "report_hash"}
    if report.get("id") != latest["id"] or canonical_hash(payload) != report.get("report_hash") or latest.get("report_hash") != report["report_hash"]:
        raise ValueError("Research report integrity check failed")
    return report


def download_path(name, root=None, files=None):
    root = root or REPORT_ROOT
    allowed = FILES if files is None else files
    if name not in allowed:
        raise ValueError("Unknown research export")
    report = read_report(root)
    if report is None:
        raise FileNotFoundError("No research report generated")
    path = (root / report["id"] / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Research export outside report root")
    if name != "report.json" and hashlib.sha256(path.read_bytes()).hexdigest() != report["files"].get(name):
        raise ValueError("Research export checksum mismatch")
    return path, allowed[name]


def read_study():
    return read_report(STUDY_ROOT)


def study_download(name):
    return download_path(name, STUDY_ROOT, {**FILES, "diagnostics.json": "application/json"})


def read_filters():
    return read_report(FILTER_ROOT)


def filter_download(name):
    return download_path(name, FILTER_ROOT, {**FILES, "diagnostics.json": "application/json"})
