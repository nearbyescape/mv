"""Frozen April-May all-symbol scope, and no silent omission of missing archives."""
from types import SimpleNamespace

import pytest

from app.research import v6hbr_directional_development as stage

SYMBOLS = ["BTCUSDT", "ETHUSDT"] + [f"TEST{i:02d}USDT" for i in range(28)]


def test_default_requires_exact_30_and_explicit_subsets_are_marked():
    assert stage.select_symbols({"symbols": SYMBOLS}, None) == SYMBOLS
    assert stage.select_symbols({"symbols": SYMBOLS}, ("ETHUSDT", "BTCUSDT")) == SYMBOLS[:2]
    with pytest.raises(ValueError, match="contract"):
        stage.select_symbols({"symbols": SYMBOLS[:29]}, None)
    with pytest.raises(ValueError, match="unique"):
        stage.select_symbols({"symbols": SYMBOLS}, ("BTCUSDT", "BTCUSDT"))
    with pytest.raises(ValueError, match="absent"):
        stage.select_symbols({"symbols": SYMBOLS}, ("UNKNOWNUSDT",))


def test_full_symbol_run_is_not_certified_from_partial_success(monkeypatch):
    monkeypatch.setattr(stage, "load_spec", lambda: ({"symbols": SYMBOLS}, "pinned"))
    done = []
    def fake_audit(root, spec, digest, symbol):
        done.append(symbol)
        if symbol == "TEST02USDT":
            raise FileNotFoundError("frozen monthly source absent")
        return {"symbol": symbol, "candidate_count": 0, "v4_base": 0,
                "15m_rescue": 0, "labeled": []}
    monkeypatch.setattr(stage, "audit_symbol", fake_audit)
    with pytest.raises(FileNotFoundError, match="absent"):
        stage.study_development("/research")
    assert "TEST02USDT" in done
    assert "TEST03USDT" not in done


def test_only_explicit_subset_uses_subset_label(monkeypatch):
    monkeypatch.setattr(stage, "load_spec", lambda: ({"symbols": SYMBOLS}, "pinned"))
    def fake_audit(root, spec, digest, symbol):
        return {"symbol": symbol, "candidate_count": 0, "v4_base": 0,
                "15m_rescue": 0, "labeled": [],
                "source_series_sha256": {"1h": "abc"}}
    monkeypatch.setattr(stage, "audit_symbol", fake_audit)
    full = stage.study_development("/research")
    assert full["run_scope"] == "ALL_30_FROZEN_SYMBOLS"
    assert full["complete_symbol_count"] == 30
    assert full["omitted_symbols"] == []
    subset = stage.study_development(
        "/research", requested_symbols=("BTCUSDT",)
    )
    assert subset["run_scope"] == "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE"
    assert subset["complete_symbol_count"] == 1
    assert len(subset["omitted_symbols"]) == 29
    assert subset["requested_symbols"] == ["BTCUSDT"]


def test_symbol_cannot_emit_missing_or_extra_forward_labels(monkeypatch):
    # All mocks are in-process: this does not download or read archived data.
    monkeypatch.setattr(stage, "batch_plan", lambda spec, s, f, start, end:
                        (s, f, start, end))
    monkeypatch.setattr(stage, "snapshots_from_pinned",
                        lambda root, plans, digest:
                        ({"mock": "closed"},{ "canonical_series_sha256":"hash"}))
    monkeypatch.setattr(stage, "export_events",
                        lambda maps, symbol, start, end: {
                            "events": ["one"], "candidates": 1,
                            "v4_base": 1, "15m_rescue": 0,
                            "export_stream_sha256": "stream",
                        })
    monkeypatch.setattr(stage, "label_directional_events",
                        lambda events, fifteen, one, end_exclusive_ms: [])
    with pytest.raises(ValueError, match="Missing directional label"):
        stage.audit_symbol("/research", {}, "hash", "BTCUSDT")
