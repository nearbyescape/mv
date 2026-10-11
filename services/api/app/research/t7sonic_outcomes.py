"""T7Sonic Phase 2C: *retrospective* directional-watch outcomes, not trades.

Separation contract:
  1. Run the existing causal 5m perception/experts to immutable decision
     events and a SHA256 chain, without reading labels or future OHLCV.
  2. Cluster consecutive identical symbol+direction observations into
     directional *episodes*, with attribution for multiple same-direction
     experts. These are not independent opportunities or executions.
  3. In a distinct function only AFTER step 1 is finished, read pinned
     monthly 1m archives for future horizons. Evaluate a hypothetical
     *mark-price proxy* at the open of the following 1m candle.

Outcome labels are NOT forward-looking features, execution fills, net
returns, SL/TP-first results, or validated trade accuracy. Binance kline
last-trade prices are NOT actual executable bid/ask quotes. No model
learning, signals, exchange access, publication or portfolio decisions.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D
from hashlib import sha256
import json
from pathlib import Path

from .t7sonic_perception import Bar
from .t7sonic_history import (
    _calendar_months, _verify_month, INTERVAL_MS,
)
from .t7sonic_replay import (
    BOUNDARY_STEP, MAX_BOUNDARIES, bounded_boundaries, replay_day,
)

HORIZONS = (15, 30, 60, 120)
HURDLE_BPS = D("10")
BPS = D("10000")
ONE_MINUTE_MS = INTERVAL_MS["1m"]


def cluster_directional_episodes(events: list[dict]) -> tuple[list[dict],dict]:
    """Co-activated experts on one symbol+side form ONE directional episode.

    A directional episode continues for contiguous 5m boundaries while
    >=1 expert in that direction remains active. A gap ends it; a new
    appearance becomes a new episode even if it is correlated with older
    exposures. This is *not* statistically independent trade deduplication.
    """
    if not isinstance(events,list) or not events:
        raise ValueError("At least one pre-outcome decision event is required")
    episodes=[]
    live={}
    prior_time=None
    coactivated_boundaries=0
    opposing_symbol_boundaries=0
    for record in events:
        t=record.get("boundary_ms")
        if type(t) is not int or t % BOUNDARY_STEP or (
            prior_time is not None and t != prior_time+BOUNDARY_STEP
        ):
            raise ValueError("Directional episodes require exactly contiguous 5m decisions")
        prior_time=t
        active={}
        for key in record.get("active_watch_keys",[]):
            if (not isinstance(key,list) or len(key)!=3 or
                not isinstance(key[0],str) or not key[0].endswith("USDT") or
                not isinstance(key[1],str) or
                key[2] not in ("LONG","SHORT")):
                raise ValueError("Invalid causal watch key")
            sym,expert,direction=key
            active.setdefault((sym,direction),set()).add(expert)
        unique_symbols={key[0] for key in active}
        opposing_symbol_boundaries+=sum(
            (sym,"LONG") in active and (sym,"SHORT") in active
            for sym in unique_symbols
        )
        coactivated_boundaries+=sum(len(experts)>1 for experts in active.values())
        for key in tuple(live):
            if key not in active:
                del live[key]
        for key,experts in sorted(active.items()):
            if key not in live:
                episode={
                    "id":f"{key[0]}:{key[1]}:{t}",
                    "symbol":key[0],"direction":key[1],
                    "first_decision_boundary_ms":t,
                    "last_active_boundary_ms":t,
                    "active_consecutive_5m_boundaries":0,
                    "experts_at_onset":sorted(experts),
                    "participating_experts":set(),
                }
                episodes.append(episode)
                live[key]=episode
            episode=live[key]
            episode["last_active_boundary_ms"]=t
            episode["active_consecutive_5m_boundaries"]+=1
            episode["participating_experts"].update(experts)
    normalized=[]
    for event in episodes:
        x=dict(event)
        x["participating_experts"]=sorted(event["participating_experts"])
        normalized.append(x)
    return normalized,{
        "directional_episodes":len(normalized),
        "multi_expert_symbol_side_boundaries":coactivated_boundaries,
        "opposing_side_symbol_boundaries":opposing_symbol_boundaries,
        "by_direction":dict(sorted(Counter(e["direction"] for e in normalized).items())),
        "by_onset_expert":dict(sorted(Counter(
            expert for e in normalized for expert in e["experts_at_onset"]
        ).items())),
        "episode_status":"CONTIGUOUS_DIRECTIONAL_WATCH_NOT_INDEPENDENT_TRADE",
    }


def _pinned_future_minutes(root: Path, symbol: str, start_ms: int,
                           end_exclusive_ms: int) -> tuple[dict[int,Bar],list[dict]]:
    """Authenticate *entire* source calendar months before exposing labels.

    Does NOT share objects with model perception; call only after the
    complete pre-outcome decision sequence has been finalized and hashed.
    """
    if type(start_ms) is not int or type(end_exclusive_ms) is not int or (
        start_ms%ONE_MINUTE_MS or end_exclusive_ms%ONE_MINUTE_MS or
        end_exclusive_ms<=start_ms
    ):
        raise ValueError("Invalid full-minute outcome time range")
    months=_calendar_months(start_ms,end_exclusive_ms)
    expected=(end_exclusive_ms-start_ms)//ONE_MINUTE_MS
    selected=[]
    sources=[]
    for month in months:
        bars,provenance=_verify_month(
            root,symbol,"1m",month,start_ms,end_exclusive_ms,expected
        )
        selected.extend(bars)
        sources.append(provenance)
    if (len(selected)!=expected or
        selected[0].open_ms!=start_ms or
        selected[-1].open_ms+ONE_MINUTE_MS!=end_exclusive_ms or
        any(y.open_ms-x.open_ms!=ONE_MINUTE_MS
            for x,y in zip(selected,selected[1:]))):
        raise ValueError("Incomplete future 1m outcome horizon (no extrapolation)")
    return {b.open_ms:b for b in selected},sources


def label_directional_episode(episode:dict, future:dict[int,Bar]) -> dict:
    """One episode's *forward-only* 1m mark proxy, not a trade P&L record."""
    when=episode["first_decision_boundary_ms"]
    direction=episode["direction"]
    if type(when) is not int or when%BOUNDARY_STEP or direction not in ("LONG","SHORT"):
        raise ValueError("Unaligned or invalid directional episode")
    sign=D(1) if direction=="LONG" else D(-1)
    # Cannot know t's first open when making the decision at t;
    # mark proxy is observed AFTER the causal decision, no zero-latency fill.
    if when not in future:
        raise ValueError("Missing first post-decision 1m bar")
    entry=future[when].opening
    if entry<=0:
        raise ValueError("Invalid proxy price")
    labeled={}
    for horizon in HORIZONS:
        bars=[]
        for n in range(horizon):
            minute=when+n*ONE_MINUTE_MS
            if minute not in future:
                raise ValueError("Missing future minute in horizon")
            bars.append(future[minute])
        finish=bars[-1].close
        signed=(finish-entry)*sign/entry*BPS
        if signed>HURDLE_BPS:
            verdict="FAVORABLE_ABOVE_10BPS"
        elif signed<-HURDLE_BPS:
            verdict="ADVERSE_BELOW_MINUS_10BPS"
        else:
            verdict="NEUTRAL_WITHIN_10BPS"
        all_high=max(x.high for x in bars)
        all_low=min(x.low for x in bars)
        if sign==1:
            max_favorable=(all_high-entry)/entry*BPS
            max_adverse=(entry-all_low)/entry*BPS
        else:
            max_favorable=(entry-all_low)/entry*BPS
            max_adverse=(all_high-entry)/entry*BPS
        labeled[str(horizon)]={
            "signed_mark_move_bps":format(signed,"f"),
            "favorable_excursion_bps":format(max(D(0),max_favorable),"f"),
            "adverse_excursion_bps":format(max(D(0),max_adverse),"f"),
            "classification":verdict,
        }
    return {
        "id":episode["id"],
        "symbol":episode["symbol"],
        "direction":direction,
        "first_decision_boundary_ms":when,
        "last_active_boundary_ms":episode["last_active_boundary_ms"],
        "active_consecutive_5m_boundaries":episode["active_consecutive_5m_boundaries"],
        "experts_at_onset":episode["experts_at_onset"],
        "participating_experts":episode["participating_experts"],
        "proxy_entry_type":"FIRST_FUTURE_1M_CANDLE_OPEN_NOT_EXECUTABLE_FILL",
        "proxy_entry_price":format(entry,"f"),
        "horizons_minutes":labeled,
    }


def research_outcomes(root:Path, symbols:tuple[str,...], day:str, *,
                      maximum:int=MAX_BOUNDARIES,
                      include_episode_records:bool=False) -> dict:
    """Development-only *retrospective* labels, separate from causal model."""
    if type(include_episode_records) is not bool:
        raise ValueError("Explicit boolean detail option required")
    times=bounded_boundaries(day,maximum=maximum)
    perception=replay_day(
        root,symbols,day,maximum=maximum,include_decision_events=True
    )
    # No forward data has been read before THIS step.
    frozen_sha=perception["candidate_stream_sha256"]
    chronological=perception.pop("decision_events")
    episodes,grouping=cluster_directional_episodes(chronological)
    future_provenance={}
    labels=[]
    if episodes:
        by_symbol={}
        for e in episodes:
            by_symbol.setdefault(e["symbol"],[]).append(e)
        for symbol in sorted(by_symbol):
            arrivals=[x["first_decision_boundary_ms"] for x in by_symbol[symbol]]
            first=min(arrivals)
            last=max(arrivals)+max(HORIZONS)*ONE_MINUTE_MS
            forward,proof=_pinned_future_minutes(root,symbol,first,last)
            future_provenance[symbol]=proof
            labels.extend(label_directional_episode(e,forward)
                          for e in by_symbol[symbol])
    labels.sort(key=lambda r:(r["first_decision_boundary_ms"],r["symbol"],r["direction"]))
    label_sha=sha256()
    for item in labels:
        label_sha.update(json.dumps(item,sort_keys=True,separators=(",",":")).encode()+b"\n")
    summary={}
    for horizon in HORIZONS:
        counts=Counter(x["horizons_minutes"][str(horizon)]["classification"]
                       for x in labels)
        summary[str(horizon)]={
            "horizon_minutes":horizon,
            "episode_labels":len(labels),
            "favorable_above_10bps":counts["FAVORABLE_ABOVE_10BPS"],
            "adverse_below_minus_10bps":counts["ADVERSE_BELOW_MINUS_10BPS"],
            "neutral_within_10bps":counts["NEUTRAL_WITHIN_10BPS"],
        }
        if sum((summary[str(horizon)][k] for k in (
            "favorable_above_10bps","adverse_below_minus_10bps","neutral_within_10bps"
        )))!=len(labels):
            raise ValueError("Unaccounted directional outcomes")
    result={
        "schema":1,"engine":"T7Sonic",
        "status":"RETROSPECTIVE_DEVELOPMENT_DIRECTIONAL_MARK_PROXY_NOT_TRADES",
        "scope":"INSPECTED_APRIL_MAY_DEVELOPMENT_ONLY",
        "day":day,"symbols":list(symbols),
        "completed_five_minute_decision_boundaries":len(times),
        "watch_observations_repeated_same_setups":
            perception["watch_observations_repeated_same_setups"],
        "expert_activation_episodes":
            perception["new_watch_activation_episodes"],
        "directional_grouping":grouping,
        "horizon_labels":summary,
        "decision_stream_sha256":frozen_sha,
        "label_stream_sha256":label_sha.hexdigest(),
        "decision_source_provenance":perception["source_provenance"],
        "future_label_source_provenance":future_provenance,
        "label_hurdle":"POSITIVE_SIGNED_MARK_MOVE_STRICTLY_OVER_10BPS",
        "future_first_minute_open_is_only_mark_proxy":True,
        "minimum_execution_latency_model_present":False,
        "quotes_slippage_fees_funding_modeled":False,
        "trade_stop_target_first_touch_modeled":False,
        "trading_wins_claimed":False,
        "actionable_signals":0,
        "all_episode_labels_derived_after_decisions_frozen":True,
        "first_twelve_episode_samples":labels[:12],
        "limitations":[
            "Episodes are consecutive WATCH exposure clusters, not statistically independent trades",
            "Multiple expert votes sharing symbol+side are grouped; correlated successive episodes remain",
            "Forward labels never used by perception or expert selection",
            "First future 1m open is historical last-trade proxy, NOT a feasible executable entry",
            "10bps directional hurdle is NOT exchange fees/slippage or an after-cost return",
            "MFE/MAE intraminute first-touch ordering and fill latency are NOT measured",
            "April–May data previously inspected, not a holdout or proof of deployable skill",
            "No calibrated model, no risk model, no trading signal publication",
        ],
    }
    if include_episode_records:
        result["directional_episode_labels"]=labels
    return result
