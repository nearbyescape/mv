"""Operator script safety checks: do not invoke Docker or historical downloads."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[3] / "tools" / "v5-eth-foundation-pilot.sh"
HAS_BASH = shutil.which("bash") is not None


@pytest.mark.skipif(not HAS_BASH, reason="Bash is required for operator shell script")
def test_bash_syntax_is_valid():
    assert SCRIPT.is_file()
    run = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert run.returncode == 0, run.stderr


@pytest.mark.skipif(not HAS_BASH, reason="Bash is required for operator shell script")
def test_fetch_requires_explicit_confirmation_before_vps_access():
    run = subprocess.run(
        ["bash", str(SCRIPT), "fetch"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert run.returncode == 2
    assert "--confirm-fetch" in run.stderr
    assert "docker" not in run.stderr.lower()


@pytest.mark.skipif(not HAS_BASH, reason="Bash is required for operator shell script")
def test_invalid_mode_is_rejected_before_vps_access():
    run = subprocess.run(
        ["bash", str(SCRIPT), "production"],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert run.returncode == 2
    assert "Usage:" in run.stderr


def test_script_avoids_production_writes_and_pins_eth_scope():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "readonly SYMBOL=ETHUSDT" in body
    assert "readonly WT=/tmp/mv-v5-history-pilot" in body
    assert "readonly RESEARCH=/var/tmp/mv-v5-history-archives" in body
    assert "--network none" in body
    assert "--network bridge" in body
    assert "--max-new-mib 64" in body
    assert "--min-free-mib 2048" in body
    assert "--read-only" in body
    assert "reconcile-1h-4h" in body
    assert "docker compose" not in body
    assert "/opt/mv-signal/app" not in body
