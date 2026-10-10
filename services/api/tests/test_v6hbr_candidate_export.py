"""Causal, complete V6HBR development candidate export without fills/P&L."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.research import v5_decision_replay as frozen
from app.research import v6hbr_candidate_export as export
from test_v5_decision_replay import H, Q, _maps, _v4_base, _v4_no_trigger


def _patch_both(monkeypatch, name, function):
    monkeypatch.setattr(frozen, name, function)
    monkeypatch.setattr(export, name, function)


def test_complete_candidate_export_matches_frozen_base_digest(monkeypatch):
    maps, source, boundary = _maps()
    _patch_both(monkeypatch, "evaluate_setup_v4", _v4_base)
    _patch_both(monkeypatch, "evaluate_context_v5", lambda *args: pytest.fail("unexpected rescue"))
    _patch_both(monkeypatch, "evaluate_trigger_v5", lambda *args: pytest.fail("unexpected trigger"))
    result = export.export_events(maps, "BTCUSDT", boundary, boundary + H)
    assert result["status"] == "COMPLETE_CANDIDATE_EXPORT_NO_PNL"
    assert result["v4_base"] == 1
    assert result["15m_rescue"] == 0
    assert result["events"][0]["at_ms"] == boundary
    assert result["events"][0]["source_1h_open_ms"] == source
    assert result["reference_candidate_stream_sha256"] == frozen.replay_decisions(
        maps, "BTCUSDT", boundary, boundary + H
    )["candidate_stream_sha256"]
    assert export.export_events(maps, "BTCUSDT", boundary, boundary + H) == result


def test_first_completed_rescue_export_matches_frozen_digest(monkeypatch):
    maps, _, boundary = _maps()
    _patch_both(monkeypatch, "evaluate_setup_v4", _v4_no_trigger)
    _patch_both(monkeypatch, "evaluate_context_v5", lambda *args: SimpleNamespace(
        outcome="ARMED", reason="CONTEXT_ARMED", direction="long", regime="emerging"
    ))

    def trigger(direction, current, previous, structure):
        pass_trigger = current.bar.open_time == boundary + Q
        return SimpleNamespace(
            outcome="TRIGGER" if pass_trigger else "NO_TRIGGER",
            reason="RULES_PASSED" if pass_trigger else "NO_TRIGGER",
            trigger_type="momentum_breakout_15m" if pass_trigger else None,
        )

    _patch_both(monkeypatch, "evaluate_trigger_v5", trigger)
    result = export.export_events(maps, "BTCUSDT", boundary, boundary + H + 1)
    assert result["v4_base"] == 0
    assert result["15m_rescue"] == 1
    row = result["events"][0]
    assert row["at_ms"] == boundary + 2 * Q
    assert row["trigger_15m_open_ms"] == boundary + Q
    assert row["regime"] == "emerging"
    assert row["status"] == "TRIGGER_ONLY_NOT_PRICED"
    assert "net_r" not in result and "fill" not in row


def test_fails_closed_if_reference_stream_diverges(monkeypatch):
    maps, _, boundary = _maps()
    _patch_both(monkeypatch, "evaluate_setup_v4", _v4_base)
    original = export.replay_decisions

    def bad_reference(*args, **kwargs):
        result = original(*args, **kwargs)
        result["candidate_stream_sha256"] = "0" * 64
        return result

    monkeypatch.setattr(export, "replay_decisions", bad_reference)
    with pytest.raises(ValueError, match="diverges"):
        export.export_events(maps, "BTCUSDT", boundary, boundary + H)


def test_validation_and_holdout_are_forbidden_even_with_complete_archives():
    with pytest.raises(ValueError, match="April-May development only"):
        export.export_development(None, symbol="BTCUSDT", start="2026-06-01", end="2026-08-01")
    with pytest.raises(ValueError, match="April-May development only"):
        export.export_development(None, symbol="ETHUSDT", start="2026-04-01", end="2026-06-01")
