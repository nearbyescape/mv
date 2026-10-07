"""Decision persistence and signal state. Plans/evidence are never updated."""
from decimal import Decimal
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import delete, select, update
from mv_strategy import INTERVAL_MS, confirmation_open_time
from mv_strategy.signals import STRATEGY_ID as V1_STRATEGY_ID, Snapshot, PriceFilter, canonical_hash, PlanRejected
from mv_strategy.strategy_v4 import (
    LIVE_STRATEGY_ID,
    EXPIRY_MS,
    STRUCTURE_BARS,
    RECENT_RUN_BARS,
    live_decision_id,
    evaluate_setup_v4,
    build_plan_v4,
)
from app.market.binance import now_ms, validate_contract
from app.market.store import as_bar
from app.market.views import collector_health
from app.models import Candle, EngineCursor, EngineStatus, IndicatorCheckpoint, IndicatorSnapshot, MarketContract, SignalDecision, SignalPlan, SignalSlot, SignalEvent, SignalOutcome, ServiceLease, WatchlistItem

CONTRACT = json.loads((Path(__file__).resolve().parents[4] / "packages" / "contracts" / "strategy-v1.json").read_text(encoding="utf-8"))
V1_CONTRACT_HASH = canonical_hash(CONTRACT)
LIVE_CONTRACT = json.loads((Path(__file__).resolve().parents[4] / "packages" / "contracts" / "strategy-v4.json").read_text(encoding="utf-8"))
LIVE_CONTRACT_HASH = canonical_hash(LIVE_CONTRACT)

# Service-local aliases keep the persistence code compact while V1 remains
# available unchanged to the historical research package.
STRATEGY_ID = LIVE_STRATEGY_ID
decision_id = live_decision_id
CONTRACT_HASH = LIVE_CONTRACT_HASH
PENDING = "PENDING"


def check_contract():
    # Refuse silent edits to the version-one financial policy.
    expected_entry = {"long_order": "EMA20 > EMA50 > SMA200", "short_order": "EMA20 < EMA50 < SMA200", "long_trigger": "previous close <= previous EMA20 and current close > current EMA20", "short_trigger": "previous close >= previous EMA20 and current close < current EMA20", "confirmation": "Latest completed 4h candle has matching ordering and closes beyond EMA20 in the setup direction", "closed_candles_only": True, "max_quote_age_seconds": 5, "expires_after_seconds": 300, "max_entry_drift_atr": "0.5", "one_active_position_per_symbol": True}
    expected_risk = {"stop_atr_multiple": "2", "target_r_multiple": "2", "trend_exit": "Completed 1h close crosses EMA50 against the position", "partial_exits": False, "trailing_stop": False}
    valid = CONTRACT.get("id") == V1_STRATEGY_ID and CONTRACT.get("version") == 1 and CONTRACT.get("indicators") == {"ema_fast": 20, "ema_slow": 50, "sma_trend": 200, "atr_wilder": 14} and CONTRACT.get("entry_timeframe") == "1h" and CONTRACT.get("confirmation_timeframe") == "4h" and CONTRACT.get("warmup_bars_per_timeframe") == 500 and CONTRACT.get("entry") == expected_entry and CONTRACT.get("risk") == expected_risk
    if not valid:
        raise ValueError("Version-one financial contract changed; create and validate a new strategy version")


def check_live_contract():
    """Refuse silent production-rule edits; V4 changes require a new contract version."""
    expected_indicators = {"ema_fast": 20, "ema_slow": 50, "sma_trend": 200, "atr_wilder": 14}
    expected_pullback = {
        "max_previous_ema20_depth_atr": "0.75",
        "min_reclaim_or_loss_atr": "0.10",
        "min_body_atr": "0.20",
        "min_directional_close_location": "0.60",
        "max_source_extension_atr": "1.00",
        "max_entry_drift_atr": "0.50",
        "max_entry_extension_atr": "1.00",
    }
    expected_breakout = {
        "lookback_bars": 12,
        "min_break_distance_atr": "0.05",
        "min_body_atr": "0.35",
        "min_directional_close_location": "0.70",
        "max_source_extension_atr": "1.50",
        "max_entry_drift_atr": "0.75",
        "max_entry_extension_atr": "1.50",
    }
    expected_anti_chase = {
        "recent_run_bars": 6,
        "max_recent_run_atr": "2.50",
        "same_direction_signals_per_symbol_per_ist_session": 1,
    }
    expected_execution = {
        "max_quote_age_seconds": 5,
        "expires_after_seconds": 300,
        "max_spread_bps": "10",
        "one_active_position_per_symbol_across_strategies": True,
        "closed_candles_only": True,
    }
    expected_risk = {
        "stop_atr_multiple": "2",
        "targets": [
            {"id": "TP1", "r_multiple": "1.0", "allocation": "0.30"},
            {"id": "TP2", "r_multiple": "1.5", "allocation": "0.30"},
            {"id": "TP3", "r_multiple": "2.0", "allocation": "0.40"},
        ],
        "after_tp1": "move_remaining_stop_to_entry",
        "after_tp2": "move_remaining_stop_to_tp1",
        "reference_only": True,
        "trailing_stop": False,
    }
    valid = (
        LIVE_CONTRACT.get("id") == LIVE_STRATEGY_ID
        and LIVE_CONTRACT.get("version") == 4
        and LIVE_CONTRACT.get("indicators") == expected_indicators
        and LIVE_CONTRACT.get("entry_timeframe") == "1h"
        and LIVE_CONTRACT.get("confirmation_timeframe") == "4h"
        and LIVE_CONTRACT.get("warmup_bars_per_timeframe") == 500
        and LIVE_CONTRACT.get("structure_lookback_bars") == STRUCTURE_BARS
        and LIVE_CONTRACT.get("setups", {}).get("pullback_continuation") == expected_pullback
        and LIVE_CONTRACT.get("setups", {}).get("momentum_breakout") == expected_breakout
        and LIVE_CONTRACT.get("anti_chase") == expected_anti_chase
        and LIVE_CONTRACT.get("execution_quality") == expected_execution
        and LIVE_CONTRACT.get("risk") == expected_risk
        and LIVE_CONTRACT.get("market_regime", {}).get("alt_btc_contradiction_veto") is True
        and LIVE_CONTRACT.get("market_regime", {}).get("btc_15m_timing_veto") is True
        and LIVE_CONTRACT.get("market_regime", {}).get("btc_15m_hard_contradiction_only") is True
        and LIVE_CONTRACT.get("portfolio_safety") == {
            "max_same_direction_signals_per_source_close": 2,
            "max_active_same_direction_reference_plans": 6,
            "active_reference_definition": "Published V4 reference plans whose scaled outcome is still open; a published plan without an analytics row counts as active.",
            "ranking": "Least stretched candidate first: lower recent-run ATR, then lower source EMA20 extension, then established before emerging, then symbol.",
            "directional_circuit_breaker": {
                "deterioration_threshold_r": "0.50",
                "required_recent_signals": 2,
                "recent_window_minutes": 120,
                "pause_minutes": 120,
                "rule": "Pause a direction when two recent V4 published signals reach -0.5R before +0.5R. The opposite direction remains eligible.",
            },
            "fail_closed_on_missing_btc_15m": True,
            "analytics_max_age_seconds": 45,
            "fail_closed_on_stale_safety_analytics": True,
        }
        and RECENT_RUN_BARS == 6
    )
    if not valid:
        raise ValueError("Production V4 financial contract changed; create and validate a new strategy version")


def engine_health(session):
    from .session import session_view
    row = session.get(EngineStatus, "engine")
    collector = collector_health(session)
    operating = session_view(now_ms() + collector["clock_offset_ms"])
    running = bool(row and 0 <= now_ms() - row.updated_at <= 15_000 and row.state in ("running", "waiting-data", "session-paused"))
    return {"state": row.state if row and 0 <= now_ms() - row.updated_at <= 15_000 else "stale" if row else "not-running", "running": running,
            "ready": running and row.state in ("running", "session-paused") and collector["live"], "session": operating,
            "last_decision_at": row.last_decision_at if row else None, "error": row.error if row else None}


def add_event(session, signal_id, type, now, payload=None, identity=None):
    session.add(SignalEvent(id=identity or str(uuid4()), signal_id=signal_id, type=type, created_at=now, payload_json=payload or {}))


def expire_slots(session, now):
    rows = session.execute(select(SignalSlot, SignalPlan.expires_at).join(SignalPlan, SignalSlot.signal_id == SignalPlan.id).where(SignalSlot.state == "reserved", SignalPlan.expires_at <= now)).all()
    for slot, _ in rows:
        removed = session.execute(delete(SignalSlot).where(SignalSlot.symbol == slot.symbol, SignalSlot.strategy == slot.strategy, SignalSlot.signal_id == slot.signal_id, SignalSlot.state == "reserved"))
        if removed.rowcount:
            add_event(session, slot.signal_id, "expired", now)


def snapshot_at(session, symbol, timeframe, open_time):
    candle = session.get(Candle, (symbol, timeframe, open_time))
    snapshot = session.get(IndicatorSnapshot, (symbol, timeframe, open_time))
    checkpoint = session.get(IndicatorCheckpoint, (symbol, timeframe))
    if not candle or not snapshot or not checkpoint or any(getattr(snapshot, key) is None for key in ("ema20", "ema50", "sma200", "atr")):
        return None
    bar = as_bar(candle)
    if bar.digest() != candle.source_hash:
        raise ValueError("Source hash mismatch")
    origin = checkpoint.state_json["history_origin"]
    result = Snapshot(timeframe, bar, *(Decimal(getattr(snapshot, key)) for key in ("ema20", "ema50", "sma200", "atr")), (open_time - origin) // INTERVAL_MS[timeframe] + 1, origin, snapshot.lineage)
    result.validate()
    return result


def context_at(session, symbol, open_time):
    current = snapshot_at(session, symbol, "1h", open_time)
    previous = snapshot_at(session, symbol, "1h", open_time - INTERVAL_MS["1h"])
    required = confirmation_open_time(open_time + INTERVAL_MS["1h"])
    confirmation = snapshot_at(session, symbol, "4h", required)
    structure = [
        snapshot_at(session, symbol, "1h", open_time - n * INTERVAL_MS["1h"])
        for n in range(STRUCTURE_BARS, 0, -1)
    ]
    contract = session.get(MarketContract, symbol)
    evidence = {
        "strategy": STRATEGY_ID,
        "contract_hash": CONTRACT_HASH,
        "indicator_version": 1,
        "decimal_precision": 34,
        "source": current.evidence() if current else None,
        "previous": previous.evidence() if previous else None,
        "confirmation": confirmation.evidence() if confirmation else None,
        "structure": [snapshot.evidence() if snapshot else None for snapshot in structure],
        "required_confirmation_open_time": required,
        "metadata": contract.metadata_json if contract else None,
        "metadata_checked_at": contract.checked_at if contract else None,
    }
    from app.config import get_settings
    if get_settings().signal_session_enabled:
        from .session import policy_evidence
        evidence["operating_session"] = policy_evidence()
    return current, previous, confirmation, structure, contract, evidence


def data_guard(session, symbol, current, previous, confirmation, contract, local_now):
    health = collector_health(session)
    if not health["live"]:
        return "COLLECTOR_NOT_LIVE"
    if session.get(WatchlistItem, symbol) is None:
        return "SYMBOL_REMOVED"
    if not contract or not contract.valid or not 0 <= local_now - contract.checked_at <= 600_000 or not validate_contract(contract.metadata_json)[0]:
        return "CONTRACT_NOT_VALIDATED"
    expected = (local_now + health["clock_offset_ms"]) // INTERVAL_MS["1h"] * INTERVAL_MS["1h"] - INTERVAL_MS["1h"]
    if current.bar.open_time != expected:
        return "SOURCE_NOT_CURRENT"
    for snapshot in (current, confirmation):
        checkpoint = session.get(IndicatorCheckpoint, (symbol, snapshot.timeframe))
        if checkpoint.state_json["last_open_time"] != snapshot.bar.open_time or checkpoint.state_json["lineage"] != snapshot.lineage or checkpoint.state_json["count"] != snapshot.count:
            return "CHECKPOINT_NOT_ALIGNED"
    if hashlib.sha256((previous.lineage + current.bar.digest()).encode()).hexdigest() != current.lineage:
        return "SOURCE_LINEAGE_MISMATCH"
    return None


def btc_regime_guard(session, symbol, direction, open_time):
    """Veto only a strong BTC contradiction; neutral/mixed BTC does not block alts."""
    if symbol == "BTCUSDT":
        return None, {"state": "self", "passed": True}
    btc_1h = snapshot_at(session, "BTCUSDT", "1h", open_time)
    required = confirmation_open_time(open_time + INTERVAL_MS["1h"])
    btc_4h = snapshot_at(session, "BTCUSDT", "4h", required)
    if btc_1h is None or btc_4h is None:
        return "BTC_REGIME_UNAVAILABLE", {"state": "unavailable", "passed": False}
    bullish = (
        btc_1h.ema20 > btc_1h.ema50
        and btc_1h.bar.close > btc_1h.ema20
        and btc_4h.ema20 > btc_4h.ema50
        and btc_4h.bar.close > btc_4h.ema20
    )
    bearish = (
        btc_1h.ema20 < btc_1h.ema50
        and btc_1h.bar.close < btc_1h.ema20
        and btc_4h.ema20 < btc_4h.ema50
        and btc_4h.bar.close < btc_4h.ema20
    )
    state = "bullish" if bullish else "bearish" if bearish else "neutral"
    contradiction = (direction == "long" and bearish) or (direction == "short" and bullish)
    evidence = {
        "state": state,
        "passed": not contradiction,
        "symbol": "BTCUSDT",
        "source_1h": btc_1h.evidence(),
        "confirmation_4h": btc_4h.evidence(),
    }
    return ("BTC_REGIME_CONTRADICTION" if contradiction else None), evidence



BTC_TIMING_TIMEFRAME = "15m"
BTC_TIMING_STEP = INTERVAL_MS[BTC_TIMING_TIMEFRAME]
MAX_DIRECTION_SIGNALS_PER_SOURCE = 2
MAX_ACTIVE_SAME_DIRECTION_REFERENCES = 6
CIRCUIT_THRESHOLD_R = Decimal("0.50")
CIRCUIT_RECENT_MS = 120 * 60_000
CIRCUIT_PAUSE_MS = 120 * 60_000
SAFETY_ANALYTICS_MAX_AGE_MS = 45_000


def btc_timing_guard(session, direction, source_open_time):
    """Fail closed on missing BTC 15m data; veto only a clear opposite short-term regime."""
    boundary = source_open_time + INTERVAL_MS["1h"]
    open_time = boundary - BTC_TIMING_STEP
    current = snapshot_at(session, "BTCUSDT", BTC_TIMING_TIMEFRAME, open_time)
    previous = snapshot_at(session, "BTCUSDT", BTC_TIMING_TIMEFRAME, open_time - BTC_TIMING_STEP)
    checkpoint = session.get(IndicatorCheckpoint, ("BTCUSDT", BTC_TIMING_TIMEFRAME))
    ready = bool(
        current
        and previous
        and checkpoint
        and current.count >= 500
        and previous.count >= 499
        and checkpoint.state_json["last_open_time"] == current.bar.open_time
        and checkpoint.state_json["lineage"] == current.lineage
    )
    if not ready:
        return "BTC_15M_TIMING_UNAVAILABLE", {
            "state": "unavailable",
            "passed": False,
            "symbol": "BTCUSDT",
            "timeframe": BTC_TIMING_TIMEFRAME,
            "required_open_time": open_time,
        }
    if direction == "long":
        contradicted = (
            current.bar.close < current.ema20 < current.ema50
            and current.ema20 < previous.ema20
        )
        state = "bearish-conflict" if contradicted else "not-contradicted"
    elif direction == "short":
        contradicted = (
            current.bar.close > current.ema20 > current.ema50
            and current.ema20 > previous.ema20
        )
        state = "bullish-conflict" if contradicted else "not-contradicted"
    else:
        return "BTC_15M_TIMING_UNAVAILABLE", {"state": "invalid-direction", "passed": False}
    passed = not contradicted
    evidence = {
        "state": state,
        "passed": passed,
        "symbol": "BTCUSDT",
        "timeframe": BTC_TIMING_TIMEFRAME,
        "current": current.evidence(),
        "previous": previous.evidence(),
    }
    return (None if passed else "BTC_15M_TIMING_CONFLICT"), evidence


def safety_analytics_guard(session, local_now):
    """Fail closed when the worker producing circuit-breaker milestones is stale."""
    lease = session.get(ServiceLease, "outcome-analytics")
    age_ms = local_now - lease.heartbeat if lease is not None else None
    ready = bool(age_ms is not None and 0 <= age_ms <= SAFETY_ANALYTICS_MAX_AGE_MS)
    evidence = {
        "ready": ready,
        "max_age_ms": SAFETY_ANALYTICS_MAX_AGE_MS,
        "age_ms": age_ms,
    }
    return (None if ready else "SAFETY_ANALYTICS_UNAVAILABLE"), evidence


def directional_circuit_breaker(session, direction, now):
    """Pause one direction for 120m after two clustered V4 signals deteriorate."""
    empty = {
        "paused": False,
        "direction": direction,
        "triggered_signals": [],
        "pause_until": None,
    }
    if direction not in ("long", "short"):
        return False, empty

    # A trigger can remain active for another 120 minutes after it occurs, so
    # retain enough publication history to reconstruct an active trigger
    # without a separate mutable circuit-breaker state table.
    rows = list(
        session.scalars(
            select(SignalOutcome)
            .where(
                SignalOutcome.strategy == STRATEGY_ID,
                SignalOutcome.direction == direction,
                SignalOutcome.published_at
                >= now - CIRCUIT_RECENT_MS - CIRCUIT_PAUSE_MS,
                SignalOutcome.adverse_050_at.is_not(None),
            )
            .order_by(SignalOutcome.adverse_050_at, SignalOutcome.signal_id)
        )
    )
    deteriorated = [
        row
        for row in rows
        # Same-minute +/-0.5R ordering is unknowable, so the safety governor
        # treats equality conservatively as adverse-first.
        if row.favorable_050_at is None
        or row.adverse_050_at <= row.favorable_050_at
    ]

    active_pair = None
    active_trigger_at = None
    for index, row in enumerate(deteriorated):
        trigger_at = row.adverse_050_at
        if trigger_at is None or trigger_at > now:
            continue
        if now >= trigger_at + CIRCUIT_PAUSE_MS:
            continue
        clustered = [
            candidate
            for candidate in deteriorated[: index + 1]
            if candidate.adverse_050_at is not None
            and candidate.adverse_050_at <= trigger_at
            and trigger_at - CIRCUIT_RECENT_MS <= candidate.published_at <= trigger_at
        ]
        if len(clustered) >= 2:
            active_pair = clustered[-2:]
            active_trigger_at = trigger_at

    if active_pair is None or active_trigger_at is None:
        recent = [
            row.signal_id
            for row in deteriorated
            if row.published_at >= now - CIRCUIT_RECENT_MS
        ]
        return False, {**empty, "triggered_signals": recent[-2:]}

    pause_until = active_trigger_at + CIRCUIT_PAUSE_MS
    return True, {
        "paused": True,
        "direction": direction,
        "triggered_signals": [row.signal_id for row in active_pair],
        "triggered_at": active_trigger_at,
        "pause_until": pause_until,
        "threshold_r": str(CIRCUIT_THRESHOLD_R),
    }

def market_safety_view(session, now):
    analytics_reason, analytics_evidence = safety_analytics_guard(session, now_ms())
    paused = {}
    for direction in ("long", "short"):
        active, evidence = directional_circuit_breaker(session, direction, now)
        if active:
            paused[direction] = evidence
    degraded = analytics_reason is not None
    return {
        "status": "degraded" if degraded else "guarded" if paused else "normal",
        "publication_enabled": not degraded,
        "analytics": analytics_evidence,
        "paused_directions": sorted(paused),
        "direction_details": paused,
        "max_same_direction_signals_per_source_close": MAX_DIRECTION_SIGNALS_PER_SOURCE,
        "max_active_same_direction_reference_plans": MAX_ACTIVE_SAME_DIRECTION_REFERENCES,
        "active_directional_reference_plans": {
            direction: active_directional_reference_count(session, direction)
            for direction in ("long", "short")
        },
        "btc_15m_timing_veto": True,
        "message": (
            "Market Safety Mode: signal publication is temporarily paused because safety analytics is unavailable."
            if degraded
            else (
                "Market Safety Mode: " + ", ".join(d.upper() for d in sorted(paused)) +
                " opportunities are temporarily paused after correlated deterioration."
                if paused
                else "Market safety governor active."
            )
        ),
    }

def active_directional_reference_count(session, direction):
    """Count unresolved published V4 reference plans; missing analytics rows count active."""
    rows = list(
        session.execute(
            select(SignalDecision.id, SignalOutcome.status)
            .outerjoin(
                SignalOutcome,
                SignalOutcome.signal_id == SignalDecision.id,
            )
            .where(
                SignalDecision.strategy == STRATEGY_ID,
                SignalDecision.direction == direction,
                SignalDecision.outcome == "PUBLISHED",
            )
        )
    )
    return sum(1 for _, status in rows if status is None or status == "open")


def _cluster_limit_reached(session, direction, source_open_time):
    published = list(
        session.scalars(
            select(SignalDecision.id)
            .where(
                SignalDecision.strategy == STRATEGY_ID,
                SignalDecision.direction == direction,
                SignalDecision.source_open_time == source_open_time,
                SignalDecision.outcome == "PUBLISHED",
            )
            .limit(MAX_DIRECTION_SIGNALS_PER_SOURCE)
        )
    )
    return len(published) >= MAX_DIRECTION_SIGNALS_PER_SOURCE


def decision_priority(session, row):
    """Deterministic safety ranking: least stretched qualified candidates first."""
    try:
        current, previous, confirmation, structure, _, _ = context_at(
            session, row.symbol, row.source_open_time
        )
        setup = evaluate_setup_v4(current, previous, confirmation, structure) if current else None
        if not setup or setup.outcome not in ("LONG_SETUP", "SHORT_SETUP"):
            return (row.source_open_time, Decimal("999"), Decimal("999"), 2, row.symbol)
        values = {item["id"].split(".")[-1]: item.get("value") for item in setup.checks}
        recent = Decimal(values.get("recent_run_atr") or "999")
        extension = Decimal(values.get("source_extension_atr") or "999")
        regime = 0 if setup.regime == "established" else 1
        return (row.source_open_time, recent, extension, regime, row.symbol)
    except Exception:
        return (row.source_open_time, Decimal("999"), Decimal("999"), 2, row.symbol)


def _evidence_snapshots(evidence, default_symbol):
    for key in ("source", "previous", "confirmation"):
        item = evidence.get(key)
        if item:
            yield default_symbol, key, item
    for index, item in enumerate(evidence.get("structure") or []):
        if item:
            yield default_symbol, f"structure:{index}", item
    btc = evidence.get("btc_regime") or {}
    if btc.get("symbol") == "BTCUSDT":
        for key in ("source_1h", "confirmation_4h"):
            item = btc.get(key)
            if item:
                yield "BTCUSDT", f"btc_regime:{key}", item
    timing = evidence.get("btc_timing") or {}
    if timing.get("symbol") == "BTCUSDT":
        for key in ("current", "previous"):
            item = timing.get(key)
            if item:
                yield "BTCUSDT", f"btc_timing:{key}", item


def discover(session, local_now):
    """First start records a baseline; restart resumes durable cursors, without backdated entries."""
    symbols = session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order))
    for symbol in symbols:
        checkpoint = session.get(IndicatorCheckpoint, (symbol, "1h"))
        if not checkpoint or not checkpoint.state_json["count"]:
            continue
        head = checkpoint.state_json["last_open_time"]
        cursor = session.get(EngineCursor, (symbol, STRATEGY_ID))
        if cursor is None:
            health = collector_health(session)
            exchange_now = local_now + health["clock_offset_ms"]
            paired = session.get(IndicatorCheckpoint, (symbol, "4h"))
            expected = exchange_now // INTERVAL_MS["1h"] * INTERVAL_MS["1h"] - INTERVAL_MS["1h"]
            expected_4h = confirmation_open_time(expected + INTERVAL_MS["1h"])
            if not health["live"] or head != expected or checkpoint.state_json["count"] < 500 or not paired or paired.state_json["count"] < 500 or paired.state_json["last_open_time"] != expected_4h:
                continue
            session.add(EngineCursor(symbol=symbol, strategy=STRATEGY_ID, last_open_time=head, initialized_at=local_now))
            identity = decision_id(symbol, head)
            if session.get(SignalDecision, identity) is None:
                session.add(SignalDecision(id=identity, symbol=symbol, strategy=STRATEGY_ID, source_open_time=head, outcome="BASELINE", reason="STARTUP_BASELINE_NO_RETROACTIVE_ENTRY", updated_at=local_now, expires_at=head + INTERVAL_MS["1h"] + EXPIRY_MS, attempts=0, evidence_json={"history_origin": checkpoint.state_json["history_origin"], "lineage": checkpoint.state_json["lineage"]}))
            continue
        times = list(session.scalars(select(Candle.open_time).where(Candle.symbol == symbol, Candle.timeframe == "1h", Candle.open_time > cursor.last_open_time, Candle.open_time <= head).order_by(Candle.open_time).limit(100)))
        for time in times:
            identity = decision_id(symbol, time)
            if session.get(SignalDecision, identity) is None:
                session.add(SignalDecision(id=identity, symbol=symbol, strategy=STRATEGY_ID, source_open_time=time, outcome=PENDING, reason="AWAITING_EVALUATION", updated_at=local_now, expires_at=time + INTERVAL_MS["1h"] + EXPIRY_MS, attempts=0, evidence_json={}))
            cursor.last_open_time = time



IST_OFFSET_MS = 330 * 60_000
DAY_MS = 86_400_000
SESSION_OPEN_MS = 9 * 3_600_000


def _same_direction_signal_this_session(session, symbol, direction, source_close):
    """Suppress repeated same-direction V4 signals for a symbol in one IST session."""
    if direction not in ("long", "short"):
        return False
    ist_day_start = ((source_close + IST_OFFSET_MS) // DAY_MS) * DAY_MS - IST_OFFSET_MS
    session_open = ist_day_start + SESSION_OPEN_MS
    earliest_source_open = session_open - INTERVAL_MS["1h"]
    return session.scalar(
        select(SignalDecision.id)
        .where(
            SignalDecision.strategy == STRATEGY_ID,
            SignalDecision.symbol == symbol,
            SignalDecision.direction == direction,
            SignalDecision.outcome == "PUBLISHED",
            SignalDecision.source_open_time >= earliest_source_open,
            SignalDecision.source_open_time < source_close,
        )
        .limit(1)
    ) is not None

def evaluate_decision(session, row, local_now, quote=None):
    """Two-phase evaluation: quote fetched outside transaction; all guards repeated before commit."""
    if row.outcome != PENDING or row.strategy != STRATEGY_ID:
        return None
    offset = collector_health(session)["clock_offset_ms"]
    now = local_now + offset
    row.updated_at, row.attempts = local_now, row.attempts + 1
    from .session import allowed, policy_evidence
    if not allowed(row.source_open_time + INTERVAL_MS["1h"], now):
        row.outcome, row.reason = "SKIPPED", "OUTSIDE_SIGNAL_SESSION"
        row.evidence_json = {"operating_session": policy_evidence(), "source_close": row.source_open_time + INTERVAL_MS["1h"]}
        return None
    if session.get(WatchlistItem, row.symbol) is None:
        row.outcome, row.reason = "REJECTED", "SYMBOL_REMOVED"
        return None
    try:
        current, previous, confirmation, structure, contract, evidence = context_at(session, row.symbol, row.source_open_time)
        row.evidence_json = deepcopy(evidence)
        setup = evaluate_setup_v4(current, previous, confirmation, structure) if current else None
    except (ValueError, ArithmeticError, KeyError) as exc:
        row.reason = "INVALID_SOURCE_DATA"
        row.evidence_json = {"error": str(exc)[:200], "contract_hash": CONTRACT_HASH}
        if now >= row.expires_at:
            row.outcome = "EXPIRED"
        return None
    if setup:
        row.direction = setup.direction
        evidence["checks"] = setup.checks
        evidence["setup"] = {
            "type": setup.setup_type,
            "regime": setup.regime,
            "structure_level": str(setup.structure_level) if setup.structure_level is not None else None,
            "recent_run_anchor": str(setup.recent_run_anchor) if setup.recent_run_anchor is not None else None,
        }
        row.evidence_json = deepcopy(evidence)
        if setup.outcome == "NO_SETUP":
            row.outcome, row.reason = "NO_SETUP", setup.reason
            return None
    if now >= row.expires_at:
        row.outcome, row.reason = "EXPIRED", "EXPIRED_ENTRY_WINDOW"
        return None
    if setup is None or setup.outcome == "BLOCKED_DATA":
        row.reason = setup.reason if setup else "MISSING_SOURCE_SNAPSHOT"
        return None
    btc_reason, btc_evidence = btc_regime_guard(session, row.symbol, setup.direction, row.source_open_time)
    evidence["btc_regime"] = btc_evidence
    row.evidence_json = deepcopy(evidence)
    if btc_reason == "BTC_REGIME_CONTRADICTION":
        row.outcome, row.reason = "NO_SETUP", btc_reason
        return None
    if btc_reason:
        row.reason = btc_reason
        return None

    timing_reason, timing_evidence = btc_timing_guard(
        session, setup.direction, row.source_open_time
    )
    evidence["btc_timing"] = timing_evidence
    row.evidence_json = deepcopy(evidence)
    if timing_reason == "BTC_15M_TIMING_CONFLICT":
        row.outcome, row.reason = "REJECTED", timing_reason
        return None
    if timing_reason:
        row.reason = timing_reason
        return None

    blocked = data_guard(session, row.symbol, current, previous, confirmation, contract, local_now)
    if blocked:
        if blocked == "SYMBOL_REMOVED":
            row.outcome = "REJECTED"
        row.reason = blocked
        return None
    if _same_direction_signal_this_session(
        session,
        row.symbol,
        setup.direction,
        row.source_open_time + INTERVAL_MS["1h"],
    ):
        row.outcome, row.reason = "REJECTED", "SAME_DIRECTION_SIGNAL_THIS_SESSION"
        return None
    analytics_reason, analytics_evidence = safety_analytics_guard(
        session, local_now
    )
    evidence["safety_analytics"] = analytics_evidence
    row.evidence_json = deepcopy(evidence)
    if analytics_reason:
        row.reason = analytics_reason
        return None

    circuit_paused, circuit_evidence = directional_circuit_breaker(
        session, setup.direction, now
    )
    evidence["directional_circuit_breaker"] = circuit_evidence
    row.evidence_json = deepcopy(evidence)
    if circuit_paused:
        row.outcome, row.reason = "REJECTED", "DIRECTIONAL_CIRCUIT_BREAKER"
        return None
    active_directional = active_directional_reference_count(
        session, setup.direction
    )
    evidence["active_directional_exposure"] = {
        "passed": active_directional < MAX_ACTIVE_SAME_DIRECTION_REFERENCES,
        "active_reference_plans": active_directional,
        "max_active_same_direction_reference_plans": MAX_ACTIVE_SAME_DIRECTION_REFERENCES,
    }
    row.evidence_json = deepcopy(evidence)
    if active_directional >= MAX_ACTIVE_SAME_DIRECTION_REFERENCES:
        row.outcome, row.reason = "REJECTED", "ACTIVE_DIRECTIONAL_EXPOSURE_LIMIT"
        return None

    if _cluster_limit_reached(session, setup.direction, row.source_open_time):
        evidence["market_concentration"] = {
            "passed": False,
            "max_same_direction_signals_per_source_close": MAX_DIRECTION_SIGNALS_PER_SOURCE,
        }
        row.evidence_json = deepcopy(evidence)
        row.outcome, row.reason = "REJECTED", "MARKET_DIRECTION_CONCENTRATION_LIMIT"
        return None
    evidence["market_concentration"] = {
        "passed": True,
        "max_same_direction_signals_per_source_close": MAX_DIRECTION_SIGNALS_PER_SOURCE,
    }
    row.evidence_json = deepcopy(evidence)
    expire_slots(session, now)
    if session.scalar(select(SignalSlot).where(SignalSlot.symbol == row.symbol).limit(1)) is not None:
        row.outcome, row.reason = "REJECTED", "ACTIVE_SIGNAL_OR_HELD_POSITION"
        return None
    row.reason = "AWAITING_FRESH_QUOTE"
    if quote is None:
        return canonical_hash(evidence)
    price = next((f for f in contract.metadata_json["filters"] if f["filterType"] == "PRICE_FILTER"), {})
    evidence["quote"] = quote.evidence()
    try:
        plan = build_plan_v4(row.symbol, setup, current, quote, PriceFilter(*(Decimal(price[k]) for k in ("tickSize", "minPrice", "maxPrice"))), now)
    except PlanRejected as exc:
        row.evidence_json = deepcopy(evidence)
        row.reason = exc.code
        if not exc.retryable:
            row.outcome = "REJECTED"
        return None
    except (KeyError, ArithmeticError):
        row.evidence_json = deepcopy(evidence)
        row.outcome, row.reason = "REJECTED", "INVALID_PRICE_FILTER"
        return None
    evidence["guards"] = {
        "collector_live": True,
        "both_timeframes_warmed": True,
        "structure_history_ready": True,
        "exact_confirmation": True,
        "contract_valid": True,
        "btc_regime_passed": True,
        "btc_15m_timing_passed": True,
        "safety_analytics_fresh": True,
        "directional_circuit_breaker_clear": True,
        "active_directional_exposure_limit_passed": True,
        "market_direction_concentration_limit_passed": True,
        "no_active_slot": True,
        "source_current": True,
        "quote_fresh": True,
        "quote_after_close": True,
        "entry_drift_passed": True,
        "entry_ema20_side": True,
        "spread_quality_passed": True,
        "price_filter_passed": True,
        "anti_chase_passed": True,
        "same_direction_session_limit_passed": True,
    }
    evidence_hash = canonical_hash(evidence)
    plan.update({"id": row.id, "evidence_hash": evidence_hash, "confirmation_open_time": confirmation.bar.open_time})
    if "operating_session" in evidence:
        plan["operating_session"] = evidence["operating_session"]
    plan["plan_hash"] = canonical_hash(plan)
    row.outcome, row.reason, row.evidence_json = "PUBLISHED", "RULES_AND_GUARDS_PASSED", deepcopy(evidence)
    session.flush()
    session.add(SignalPlan(id=row.id, symbol=row.symbol, strategy=STRATEGY_ID, created_at=now, expires_at=row.expires_at, plan_json=plan, evidence_json=evidence, evidence_hash=evidence_hash))
    session.flush()
    session.add(SignalSlot(symbol=row.symbol, strategy=STRATEGY_ID, signal_id=row.id, state="reserved"))
    add_event(session, row.id, "published", now, {"evidence_hash": evidence_hash})
    return None


def check_source_revisions(session, now):
    recent = list(session.scalars(select(SignalPlan).order_by(SignalPlan.created_at.desc()).limit(100)))
    active = list(session.scalars(select(SignalPlan).join(SignalSlot, SignalSlot.signal_id == SignalPlan.id)))
    for plan in {p.id: p for p in recent + active}.values():
        identity = str(uuid5(NAMESPACE_URL, plan.id + ":source-revised"))
        if session.get(SignalEvent, identity):
            continue
        for evidence_symbol, key, evidence in _evidence_snapshots(plan.evidence_json, plan.symbol):
            snapshot = session.get(IndicatorSnapshot, (evidence_symbol, evidence["timeframe"], evidence["open_time"]))
            if snapshot is None or snapshot.lineage != evidence["lineage"]:
                add_event(session, plan.id, "source-revised", now, {"affected": key, "message": "Retained source lineage changed after publication; original plan remains immutable"}, identity)
                session.execute(delete(SignalSlot).where(SignalSlot.signal_id == plan.id, SignalSlot.state == "reserved"))
                break


def signal_view(session, row, now):
    from app.ai.service import review_view
    from app.telegram.service import delivery_view
    from .session import allowed
    slot = session.get(SignalSlot, (row.symbol, row.strategy))
    state = slot.state if slot and slot.signal_id == row.id else None
    events = list(session.scalars(select(SignalEvent).where(SignalEvent.signal_id == row.id).order_by(SignalEvent.created_at, SignalEvent.id)))
    types = {event.type for event in events}
    revised = "source-revised" in types
    if not revised:
        # Fail closed immediately; persisted withdrawal events may follow on
        # the worker's next scan. Original plan/evidence remain unchanged.
        for evidence_symbol, _, evidence in _evidence_snapshots(row.evidence_json, row.symbol):
            current=session.get(IndicatorSnapshot,(evidence_symbol,evidence["timeframe"],evidence["open_time"]))
            if not current or current.lineage!=evidence["lineage"]:
                revised=True
                break
    payload = {key: value for key, value in row.plan_json.items() if key != "plan_hash"}
    integrity = canonical_hash(row.evidence_json) == row.evidence_hash == row.plan_json.get("evidence_hash") and canonical_hash(payload) == row.plan_json.get("plan_hash")
    status = "integrity-failed" if not integrity else "withdrawn" if revised else "held" if state == "held" else "released" if "released" in types else "expired" if now >= row.expires_at else "active" if state == "reserved" else "closed"
    ai_review = review_view(session,row,integrity,revised)
    circuit_paused, _ = directional_circuit_breaker(session, row.plan_json.get("direction"), now)
    analytics_ready = safety_analytics_guard(session, now_ms())[0] is None
    return {**row.plan_json, "status": status, "slot": state, "entry_actionable": status == "active" and engine_health(session)["ready"] and analytics_ready and not circuit_paused and allowed(row.plan_json["source_close_boundary"],now), "source_revised": revised,
            "integrity_valid": integrity, "evidence": row.evidence_json, "events": [{"type": e.type, "time": e.created_at, "detail": e.payload_json} for e in events], "ai": ai_review["status"], "ai_review": ai_review, "telegram": delivery_view(session,row.id)}


def slot_action(session, row, action, local_now, note):
    now = local_now + collector_health(session)["clock_offset_ms"]
    slot = session.get(SignalSlot, (row.symbol, row.strategy))
    if action == "hold":
        if slot and slot.signal_id == row.id and slot.state == "held":
            return
        view = signal_view(session, row, now)
        if not view["entry_actionable"] or not slot or slot.signal_id != row.id:
            raise ValueError("Signal is expired, unavailable, withdrawn or no longer owns this slot")
        changed = session.execute(update(SignalSlot).where(SignalSlot.signal_id == row.id, SignalSlot.state == "reserved").values(state="held"))
        if not changed.rowcount:
            raise ValueError("Signal slot changed; reload before marking it held")
        add_event(session, row.id, "held", now, {"note": note, "source": "operator-report", "fill": "not-recorded"})
    else:
        if not slot or slot.signal_id != row.id:
            if session.scalar(select(SignalEvent.id).where(SignalEvent.signal_id == row.id, SignalEvent.type == "released")):
                return
            raise ValueError("This signal no longer owns an active slot")
        removed = session.execute(delete(SignalSlot).where(SignalSlot.signal_id == row.id))
        if removed.rowcount:
            add_event(session, row.id, "released", now, {"note": note, "source": "operator-report", "fill": "not-recorded"})
