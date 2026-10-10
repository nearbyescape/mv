"""Static shell-safety gate for the isolated V6HBR candidate export pilot."""
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools/v6hbr-candidate-export-pilot.sh"


def test_v6hbr_candidate_pilot_cannot_access_live_compose_or_holdout():
    text = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "/tmp/mv-v5-history-pilot",
        "codex/mv-v6hbr-research",
        "/var/tmp/mv-v5-history-archives",
        "--network none", "--read-only", "--pull never",
        "--user 10001:10001", "--cpus=0.5", "--memory=768m",
        '2026-04-01', '2026-06-01',
        "tests/test_v6hbr_candidate_export.py",
        "tests/test_v6hbr_execution_model.py",
        "v6hbr_candidate_export",
    ):
        assert token in text
    for forbidden in (
        "docker compose", "git reset", "git switch",
        "git checkout", "git fetch", "git pull", "--network host",
        "/opt/mv-signal/app", "2026-08-01", "2026-09-01",
    ):
        assert forbidden not in text


def test_v6hbr_candidate_pilot_bash_syntax():
    if not shutil.which("bash"):
        pytest.skip("Bash unavailable")
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True, capture_output=True)
