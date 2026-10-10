"""Research-only V4 base preservation and causal 15m rescue tests."""
from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from datetime import datetime, timezone

import pytest
from mv_strategy.indicators import Bar, INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import Snapshot

from app.research import v5_decision_replay as replay

H = INTERVAL_MS["1h"]
Q = INTERVAL_MS["15m"]
F = INTERVAL_MS["4h"]


def _ms(day, hour):
    date = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    return int(date.timestamp() * 1000) + hour * H


def _snapshot(frame: str, opening: int):
    step = INTERVAL_MS[frame]
    count = opening // step + 1
    bar = Bar(
        opening, opening + step - 1,
        Decimal(100), Decimal(102), Decimal(99),
        Decimal(101), Decimal(7),
    )
    snapshot = Snapshot(
        frame, bar, Decimal(101), Decimal(100),
        Decimal(99), Decimal(2), count, 0, "fixture",
    )
    snapshot.validate()
    return snapshot


def _maps():
    # 04:00 UTC == 09:30 IST; source hourly candle opened at 03:00.
    published = _ms("2026-04-01", 4)
    source = published - H
    one = {
        t: _snapshot("1h", t)
        for t in range(source - 12 * H, source + H, H)
    }
    fifteen = {
        t: _snapshot("15m", t)
        for t in range(published - 13 * Q, published + 4 * Q, Q)
    }
    confirmed = confirmation_open_time(published)
    four = {confirmed: _snapshot("4h", confirmed)}
    return {"1h": one, "15m": fifteen, "4h": four}, source, published


def _v4_no_trigger(*args):
    return SimpleNamespace(
        outcome="NO_SETUP", reason="NO_PULLBACK_OR_BREAKOUT_TRIGGER",
        direction="long", regime="established", setup_type=None,
    )


def _v4_base(*args):
    return SimpleNamespace(
        outcome="LONG_SETUP", reason="RULES_PASSED",
        direction="long", regime="established",
        setup_type="momentum_breakout",
    )


def test_hybrid_only_checks_15m_after_trend_aligned_v4_no_trigger(monkeypatch):
    maps, source, boundary = _maps()
    seen = []
    monkeypatch.setattr(replay, "evaluate_setup_v4", _v4_no_trigger)
    monkeypatch.setattr(
        replay, "evaluate_context_v5",
        lambda *args: SimpleNamespace(outcome="ARMED", reason="CONTEXT_ARMED", direction="long"),
    )

    def fake_trigger(direction, current, previous, structure):
        assert current.bar.close_time + 1 > boundary
        assert previous.bar.close_time + 1 == current.bar.open_time
        assert structure[-1].bar.open_time == previous.bar.open_time
        seen.append(current.bar.open_time)
        return SimpleNamespace(
            reason="RULES_PASSED" if len(seen) == 2 else "NO_15M_PULLBACK_OR_BREAKOUT_TRIGGER",
            outcome="TRIGGER" if len(seen) == 2 else "NO_TRIGGER",
            trigger_type="momentum_breakout_15m" if len(seen) == 2 else None,
        )

    monkeypatch.setattr(replay, "evaluate_trigger_v5", fake_trigger)
    result = replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + H + 1)
    assert result["counts"]["hourly_contexts"] == 1
    assert result["counts"]["v4_trend_aligned_no_trigger"] == 1
    assert result["counts"]["armed_rescue_hours"] == 1
    assert result["counts"]["completed_15m_trigger_checks"] == 2
    assert result["counts"]["v5_rescue_trigger_references"] == 1
    assert result["candidate_samples"][0]["at_ms"] == boundary + 2 * Q
    assert result["candidate_samples"][0]["status"] == "TRIGGER_ONLY_NOT_PRICED"
    assert seen == [boundary, boundary + Q]


def test_v4_base_is_never_replaced_by_rescue(monkeypatch):
    maps, source, boundary = _maps()
    monkeypatch.setattr(replay, "evaluate_setup_v4", _v4_base)
    monkeypatch.setattr(replay, "evaluate_context_v5", lambda *args: pytest.fail("V5 was called on a V4 base"))
    monkeypatch.setattr(replay, "evaluate_trigger_v5", lambda *args: pytest.fail("rescue was called on base"))
    result = replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + H)
    assert result["counts"]["v4_base_qualifiers"] == 1
    assert result["counts"]["v5_base_preserved_pre_safety"] == 1
    assert result["counts"].get("v5_rescue_trigger_references", 0) == 0
    assert result["candidate_samples"][0]["lane"] == "v4_base"


def test_rescue_cannot_cross_ist_session_end(monkeypatch):
    maps, source, _ = _maps()
    # 17:00 UTC == 22:30 IST. The +15m signal is 22:45 IST;
    # next +30m boundary hits 23:00 IST, outside session.
    boundary = _ms("2026-04-01", 17)
    source = boundary - H
    maps["1h"] = {t: _snapshot("1h", t) for t in range(source - 12 * H, source + H, H)}
    maps["15m"] = {t: _snapshot("15m", t) for t in range(boundary - 13 * Q, boundary + 4 * Q, Q)}
    confirmed = confirmation_open_time(boundary)
    maps["4h"] = {confirmed: _snapshot("4h", confirmed)}
    monkeypatch.setattr(replay, "evaluate_setup_v4", _v4_no_trigger)
    monkeypatch.setattr(
        replay, "evaluate_context_v5",
        lambda *args: SimpleNamespace(outcome="ARMED", reason="CONTEXT_ARMED", direction="long"),
    )
    monkeypatch.setattr(
        replay, "evaluate_trigger_v5",
        lambda *args: SimpleNamespace(outcome="NO_TRIGGER", reason="NO_TRIGGER"),
    )
    result = replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + 2 * H)
    assert result["counts"]["completed_15m_trigger_checks"] == 1
    assert result["counts"].get("v5_rescue_trigger_references", 0) == 0


def test_unwarmed_four_hour_history_is_not_a_valid_decision_window():
    maps, source, boundary = _maps()
    maps["4h"] = {}
    with pytest.raises(ValueError, match="500-bar warmup"):
        replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + H)


def test_decision_digest_and_reference_events_repeat_deterministically(monkeypatch):
    maps, source, boundary = _maps()
    monkeypatch.setattr(replay, "evaluate_setup_v4", _v4_no_trigger)
    monkeypatch.setattr(
        replay, "evaluate_context_v5",
        lambda *args: SimpleNamespace(outcome="NO_CONTEXT", reason="TREND_REGIME_NOT_READY", direction=None),
    )
    one = replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + H)
    two = replay.replay_decisions(maps, "BTCUSDT", boundary, boundary + H)
    assert one == two
    assert len(one["decision_stream_sha256"]) == 64
    assert one["counts"].get("v5_rescue_trigger_references", 0) == 0


def test_replay_forbids_validation_and_holdout_use():
    from app.research.v5_archives import load_spec
    spec, key = load_spec()
    with pytest.raises(ValueError, match="Jan-May only"):
        replay.replay_development(None, spec, key, "BTCUSDT", "2026-01", "2026-06")
