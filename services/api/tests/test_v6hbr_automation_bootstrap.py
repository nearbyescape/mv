"""Static/fail-closed safety checks for the one-time V6HBR VPS automation.

Never installs a systemd service, runs Docker, uses SSH, or contacts a VPS.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

TOOLS = Path(__file__).resolve().parents[3] / "tools"
INSTALL = TOOLS / "v6hbr-auto-install.sh"
AGENT = TOOLS / "v6hbr-auto-agent.sh"


@pytest.mark.parametrize("script", [INSTALL, AGENT])
def test_bootstrap_shell_syntax(script):
    if not shutil.which("bash"):
        pytest.skip("Bash not installed")
    subprocess.run(["bash", "-n", str(script)], check=True,
                   capture_output=True, timeout=10)


def test_install_requires_pinned_reviewed_commit_without_mutation():
    source = INSTALL.read_text(encoding="utf-8")
    assert 'test "$(id -u)" -ne 0' in source
    assert '"$EXPECTED" =~ ^[0-9a-f]{40}$' in source
    assert 'test "$(git -C "$WT" branch --show-current)" = "$BRANCH"' in source
    assert 'test -z "$(git -C "$WT" status --porcelain)"' in source
    assert '"refs/remotes/origin/$BRANCH^{commit}"' in source
    assert '= "$EXPECTED"' in source
    assert 'git -C "$WT" show "$EXPECTED:tools/v6hbr-auto-agent.sh"' in source
    assert "ConditionPathExists=/var/lib/mv-v6hbr-auto/last-reviewed-ancestor" in source
    assert "ReadWritePaths=/var/lib/mv-v6hbr-auto" in source
    assert "ProtectSystem=strict" in source
    assert "PrivateTmp=true" in source
    assert "BindReadOnlyPaths=/var/tmp/mv-v5-history-archives" in source
    assert "OnCalendar=hourly" in source
    assert "systemctl enable --now mv-v6hbr-auto.timer" in source
    assert "/opt/mv-signal/app" not in source
    assert "docker compose" not in source
    assert "MV_TELEGRAM_TOKEN" not in source


def test_agent_remote_source_executes_only_inside_offline_container():
    source = AGENT.read_text(encoding="utf-8")
    assert "codex/mv-v6hbr-research" in source
    assert "48a460a42a1daf3349fe1b32af31154608dd2c6739cfca34eb14f3a5d1763d64" in source
    assert '--network none' in source
    assert '--read-only' in source
    assert '--cap-drop ALL' in source
    assert '--security-opt no-new-privileges' in source
    assert '--user 10001:10001' in source
    assert '--cpus=0.5' in source
    assert '--memory=768m' in source
    assert '--memory-swap=768m' in source
    assert '--pull never' in source
    assert '--log-driver none' in source
    assert '--tmpfs /tmp:rw,nosuid,nodev,size=64m' in source
    assert 'test ! -L "$SOURCE"' in source
    assert "archive symlinks and special files prohibited" in source
    assert "git -C \"$REPO\" merge-base --is-ancestor" in source
    assert "tests/test_v6hbr_attribution.py" in source
    assert "tests/test_v6hbr_automation_bootstrap.py" in source
    assert "--acknowledge-proxy-not-fills" in source
    for forbidden in (
        "docker compose", "--network host", "git reset",
        "git checkout", "git switch", "/opt/mv-signal/app",
        "MV_TELEGRAM_TOKEN", "/etc/mv-signal",
    ):
        assert forbidden not in source


def test_installer_without_exact_reviewed_sha_fails_before_any_side_effects():
    if not shutil.which("bash"):
        pytest.skip("Bash not installed")
    result = subprocess.run(
        ["bash", str(INSTALL)], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 2
    assert "exact-reviewed-40-char-commit" in result.stderr
