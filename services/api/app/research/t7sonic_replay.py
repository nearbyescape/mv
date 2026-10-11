"""T7Sonic bounded causal one-day 5m opportunity *WATCH* replay.

Verifies source-complete monthly ZIPs once per requested month, then at
each completed 5m cutoff slices ONLY candles with end <= that cutoff.
Future months and unseen price labels are never used for opportunity
selection. Output does NOT claim trades, wins, accuracy or profitability.

Important: repeated WATCH hypotheses on consecutive bars are correlated,
not separate actionable signals. Reports both per-boundary observations
and new activation episodes (after an absence).
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .t7sonic_history import (
    DEVELOPMENT_END, DEVELOPMENT_START, FROZEN_MARKETS,
    HISTORICAL_FRAMES, INTERVAL_MS, MAX_INPUT_SYMBOLS, OBSERVATION_BARS,
    RECONCILIATION_MINUTE_BARS,
    _bars_to_json, _calendar_months, _derive_5m,
    _necessary_first_ms, _reconcile_higher_frames_against_minutes,
    _verify_month,
)
from .t7sonic_perception import REQUIRED_FRAMES, perceive_symbol
from .t7sonic_experts import research_market

BOUNDARY_STEP=INTERVAL_MS["5m"]
MAX_BOUNDARIES=288


def bounded_boundaries(day: str, *, maximum: int = MAX_BOUNDARIES) -> tuple[int,...]:
    if not isinstance(day,str) or len(day)!=10 or day[4]!="-" or day[7]!="-":
        raise ValueError("Day must be YYYY-MM-DD")
    parsed=datetime.strptime(day,"%Y-%m-%d").replace(tzinfo=timezone.utc)
    if parsed.strftime("%Y-%m-%d")!=day:
        raise ValueError("Invalid UTC research day")
    first=int(parsed.timestamp()*1000)
    if not (DEVELOPMENT_START <= first and
            first + 86_400_000 < DEVELOPMENT_END):
        raise ValueError("Pilot day must be April 1–May 30, 2026 development only")
    if type(maximum) is not int or not 1<=maximum<=MAX_BOUNDARIES:
        raise ValueError("Bounded replay must contain 1..288 decision cutoffs")
    return tuple(first+(k+1)*BOUNDARY_STEP for k in range(maximum))


def load_source_windows(root: Path, symbol: str, boundaries: tuple[int,...]) -> tuple[dict,dict]:
    if symbol not in FROZEN_MARKETS:
        raise ValueError("Symbol absent from frozen watchlist")
    if not boundaries or any(
        type(t) is not int or t%BOUNDARY_STEP for t in boundaries
    ) or any(b<=a for a,b in zip(boundaries,boundaries[1:])):
        raise ValueError("Invalid ordered 5m decision boundaries")
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("Research root must be real absolute directory")
    first,last=boundaries[0],boundaries[-1]
    loaded={}
    manifest={}
    for frame in HISTORICAL_FRAMES:
        begin,_=_necessary_first_ms(frame,first)
        step=INTERVAL_MS[frame]
        end=(last//step)*step
        if begin<0 or end<=begin:
            raise ValueError("Invalid historical source range")
        months=_calendar_months(begin,end)
        expected=(end-begin)//step
        pieces=[]
        proofs=[]
        for month in months:
            part,proof=_verify_month(root,symbol,frame,month,begin,end,expected)
            pieces.extend(part)
            proofs.append(proof)
        if (len(pieces)!=expected or pieces[0].open_ms!=begin or
            pieces[-1].open_ms+step!=end or
            any(y.open_ms-x.open_ms!=step for x,y in zip(pieces,pieces[1:]))):
            raise ValueError("Unverified missing or overlapping research source: "+frame)
        loaded[frame]=pieces
        manifest[frame]=proofs
    return loaded,manifest


def _as_of(raw: dict, symbol: str, when: int) -> dict:
    """Select only completed candles; a future row cannot affect this result."""
    selected={}
    for frame in HISTORICAL_FRAMES:
        step=INTERVAL_MS[frame]
        end=(when//step)*step
        candidates=raw[frame]
        opens=[r.open_ms for r in candidates]
        ix=bisect_left(opens,end)
        n=RECONCILIATION_MINUTE_BARS if frame=="1m" else OBSERVATION_BARS
        if ix<n:
            raise ValueError("Missing completed causal warmup at "+frame)
        bars=candidates[ix-n:ix]
        if (bars[0].open_ms!=end-n*step or bars[-1].open_ms+step!=end):
            raise ValueError("Causal timeframe window has missing candles: "+frame)
        selected[frame]=bars
    reconciliation=_reconcile_higher_frames_against_minutes(selected)
    five=_derive_5m(selected["1m"][-OBSERVATION_BARS*5:])
    snap={
        "symbol":symbol,"as_of_ms":when,
        "bars":{
            frame:_bars_to_json(
                five if frame=="5m" else
                selected[frame][-OBSERVATION_BARS:]
            )
            for frame in REQUIRED_FRAMES
        },
    }
    return {"snapshot":snap,"reconciliation":reconciliation}


def replay_day(root: Path, symbols: tuple[str,...], day: str, *,
               maximum: int=MAX_BOUNDARIES) -> dict:
    if (not isinstance(symbols,tuple) or not 1<=len(symbols)<=MAX_INPUT_SYMBOLS
        or len(set(symbols))!=len(symbols)
        or any(s not in FROZEN_MARKETS for s in symbols)):
        raise ValueError("Explicit unique 1–6 frozen symbols only")
    times=bounded_boundaries(day,maximum=maximum)
    loaded={}
    provenance={}
    for symbol in symbols:
        loaded[symbol],provenance[symbol]=load_source_windows(root,symbol,times)
    count_by_expert=Counter()
    activation_by_expert=Counter()
    count_by_market=Counter()
    count_by_direction=Counter()
    case_snapshots=0
    watch_observations=0
    previous=set()
    periods_with_any_watch=0
    conflicting_periods=0
    stream=sha256()
    sample=[]
    for when in times:
        perceptions=[]
        window_proof={}
        for symbol in symbols:
            observation=_as_of(loaded[symbol],symbol,when)
            p=perceive_symbol(observation["snapshot"])
            perceptions.append(p)
            window_proof[symbol]=observation["reconciliation"]
        data=research_market(perceptions)
        watch=[]
        for result in data["market_reports"]:
            case_snapshots+=1
            if result["competing_directions"]:
                conflicting_periods+=1
            for h in result["watch_hypotheses"]:
                if h["publishable_signal"] or h["executable_order"]:
                    raise ValueError("WATCH replay attempted to publish an actionable signal")
                key=(h["symbol"],h["expert"],h["direction"])
                watch.append(key)
                count_by_expert[h["expert"]]+=1
                count_by_market[h["symbol"]]+=1
                count_by_direction[h["direction"]]+=1
                watch_observations+=1
        active=set(watch)
        emerging=active-previous
        previous=active
        for key in emerging:
            activation_by_expert[key[1]]+=1
        if watch:
            periods_with_any_watch+=1
        event={
            "boundary_ms":when,
            "active_watch_keys":[list(key) for key in sorted(active)],
            "new_activation_keys":[list(key) for key in sorted(emerging)],
            "market_source_sha256":{
                p["symbol"]:p["feature_source_sha256"] for p in perceptions
            },
        }
        serialized=json.dumps(event,sort_keys=True,separators=(",",":")).encode()
        stream.update(serialized+b"\n")
        if len(sample)<5:
            sample.append(event)
    return {
        "schema":1,
        "status":"T7SONIC_DEV_ONLY_HISTORICAL_WATCH_EPISODES_NOT_TRADE_SIGNALS",
        "engine":"T7Sonic",
        "partition":"INSPECTED_APRIL_MAY_DEVELOPMENT_ONLY",
        "day":day,
        "markets":list(symbols),
        "run_scope":"EXPLICIT_SUBSET_NOT_FULL_UNIVERSE",
        "completed_five_minute_decision_boundaries":len(times),
        "symbol_boundary_observations":case_snapshots,
        "watch_observations_repeated_same_setups":watch_observations,
        "new_watch_activation_episodes":sum(activation_by_expert.values()),
        "active_boundaries_at_least_one_watch":periods_with_any_watch,
        "contradictory_direction_symbol_boundaries":conflicting_periods,
        "by_expert_observations":dict(sorted(count_by_expert.items())),
        "by_expert_new_activations":dict(sorted(activation_by_expert.items())),
        "by_market_observations":dict(sorted(count_by_market.items())),
        "by_direction_observations":dict(sorted(count_by_direction.items())),
        "candidate_stream_sha256":stream.hexdigest(),
        "source_provenance":provenance,
        "first_five_decision_samples":sample,
        "source_interpretation":"V5_FORMAT_ZIP_PLUS_SIDECAR_PINNED_NOT_FRESH_PUBLISHER_AUTHENTICATION",
        "outcomes_labeled":False,
        "actionable_signals":0,
        "trade_profitability_assessed":False,
        "market_feature_validation":"ONLY_COMPLETED_PER_BOUNDARY_1M_5M_15M_1H_4H",
        "limitations":[
            "Repeated WATCH exposures are counted separately from activation episodes",
            "Activation episode is not a tradable entry or independent statistical sample",
            "Only explicit Apr–May development: no validation or holdout access",
            "No probabilities, after-cost expected R, quotes, fills, stops or model selection",
            "Six experts use heuristic initial rules; opportunity quality unproven",
            "Source sidecars must independently match Binance publisher .CHECKSUM evidence",
        ],
    }
