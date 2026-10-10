"""Offline static safety checks for V6HBR operator scripts; never access VPS."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


TOOLS = Path(__file__).resolve().parents[3] / "tools"
SCRIPTS = (
    TOOLS / "v6hbr-btc-replay-pilot.sh",
    TOOLS / "v6hbr-eth-foundation-pilot.sh",
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_scripts_are_isolated_v6hbr_worktree_only(script):
    body = script.read_text(encoding="utf-8")
    assert "codex/mv-v6hbr-research" in body
    assert "/tmp/mv-v5-history-pilot" in body
    assert "/var/tmp/mv-v5-history-archives" in body
    assert "--read-only" in body
    assert "--network none" in body
    assert "--cpus=0.5" in body
    assert "--memory=768m" in body
    assert "docker compose " not in body
    assert "/opt/mv-signal/app" not in body
    assert "MV_TELEGRAM_TOKEN" not in body


@pytest.mark.skipif(shutil.which("bash") is None, reason="Bash unavailable")
@pytest.mark.parametrize("script", SCRIPTS)
def test_bash_syntax_valid(script):
    proc = subprocess.run(
        ["bash", "-n", str(script)],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="Bash unavailable")
def test_eth_fetch_needs_confirmation_before_access():
    proc = subprocess.run(
        ["bash", str(TOOLS / "v6hbr-eth-foundation-pilot.sh"), "fetch"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert proc.returncode == 2
    assert "--confirm-fetch" in proc.stderr


def test_eth_recursive_verify_stays_on_v6hbr_wrapper():
    body = (TOOLS / "v6hbr-eth-foundation-pilot.sh").read_text()
    assert '"$WT/tools/v6hbr-eth-foundation-pilot.sh" verify' in body
    assert '"$WT/tools/v5-eth-foundation-pilot.sh" verify' not in body
    assert "--max-new-mib 64" in body
    assert "--min-free-mib 2048" in body
