"""Guard isolated V6HBR BTC cost proxy operator script against live effects."""
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "tools/v6hbr-btc-pricing-pilot.sh"


def test_explicit_proxy_script_cannot_touch_production_or_holdout():
    text = SCRIPT.read_text(encoding="utf-8")
    required = (
        "/tmp/mv-v5-history-pilot", "codex/mv-v6hbr-research",
        "/var/tmp/mv-v5-history-archives",
        "--network none", "--read-only", "--pull never",
        "--user 10001:10001", "--cpus=0.5", "--memory=768m",
        "tests/test_v6hbr_portfolio_replay.py",
        "tests/test_v6hbr_btc_pricing_pilot.py",
        "v6hbr_btc_pricing_pilot",
        "--acknowledge-proxy-not-fills",
    )
    for token in required:
        assert token in text
    forbidden = (
        "docker compose", "git reset", "git switch", "git checkout",
        "git fetch", "git pull", "--network host",
        "/opt/mv-signal/app", "2026-08-01", "2026-09-01",
    )
    for token in forbidden:
        assert token not in text


def test_bash_syntax():
    if not shutil.which("bash"):
        pytest.skip("Bash unavailable")
    subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, check=True)
