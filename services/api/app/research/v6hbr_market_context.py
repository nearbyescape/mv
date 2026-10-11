"""Causal synchronized market-context snapshot, V6HBR RESEARCH ONLY.

No I/O, no external calls, no production DB/signal worker, no order methods.
Inputs must be a frozen 30-market universe and source-verified completed frames.
A context is not a buy/sell or trading decision, even when healthy.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D, InvalidOperation
from hashlib import sha256
import json

FRAMES_MS = {"15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
UNIVERSE_SIZE = 30
MIN_HEALTHY_MARKETS = 24  # Research context quality only, NOT a trade threshold.
REQUIRED_LEADER = "BTCUSDT"


def _decimal(raw, field: str) -> D:
    if isinstance(raw, bool) or isinstance(raw, (int, float)):
        # Source prices and technical indicators must retain exact decimal strings.
        raise ValueError(f"{field} requires an exact decimal string")
    if not isinstance(raw, str):
        raise ValueError(f"{field} requires an exact decimal string")
    try:
        v = D(raw)
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Malformed {field}") from e
    if not v.is_finite():
        raise ValueError(f"Nonfinite {field}")
    return v


def _frame(r: dict, allowed: set[str]) -> dict:
    if not isinstance(r, dict):
        raise ValueError("Source frame must be a record")
    symbol = r.get("symbol")
    tf = r.get("timeframe")
    if symbol not in allowed or tf not in FRAMES_MS:
        raise ValueError("Source outside frozen symbol/timeframe contract")
    end = r.get("closed_boundary_ms")
    available = r.get("available_at_ms")
    if type(end) is not int or end < FRAMES_MS[tf] or end % FRAMES_MS[tf]:
        raise ValueError("Malformed source close boundary")
    if type(available) is not int or available < end:
        raise ValueError("Source available before its completed candle close")
    vals = {
        field: _decimal(r.get(field), field) for field in
        ("close", "ema20", "ema50", "sma200", "atr", "volume")
    }
    if any(vals[k] <= 0 for k in ("close", "ema20", "ema50", "sma200", "atr")):
        raise ValueError("Nonpositive source price, moving average, or ATR")
    if vals["volume"] < 0:
        raise ValueError("Negative source volume")
    lineage = r.get("source_sha256")
    if not isinstance(lineage, str) or len(lineage) != 64 or any(
        c not in "0123456789abcdef" for c in lineage
    ):
        raise ValueError("Verified 64-digit lowercase source checksum required")
    return {
        "symbol":symbol, "timeframe":tf,
        "closed_boundary_ms":end, "available_at_ms":available,
        "source_sha256":lineage,
        **{k:str(v) for k,v in vals.items()},
    }


def _trend(r: dict) -> str:
    close = D(r["close"])
    e20 = D(r["ema20"])
    e50 = D(r["ema50"])
    s200 = D(r["sma200"])
    if close > e20 > e50 and close > s200:
        return "bullish"
    if close < e20 < e50 and close < s200:
        return "bearish"
    return "mixed"


def snapshot_asof(universe: list[str], source_frames: list[dict], asof_ms: int) -> dict:
    """Synchronized **completed and actually available** 15m/1h/4h contexts.

    Exactly 30 symbols must be enumerated; partial markets are counted and
    diagnosed but never marked as full-market context. A future frame never
    influences the as-of snapshot, even if the caller also supplies it.
    Missing/late completed candle => missing context, never stale forward-fill.
    """
    if not isinstance(universe, list) or len(universe) != UNIVERSE_SIZE or (
        len(set(universe)) != UNIVERSE_SIZE
    ) or any(not isinstance(s, str) or not s.endswith("USDT") for s in universe):
        raise ValueError("Exactly 30 unique frozen USDT markets required")
    if REQUIRED_LEADER not in universe:
        raise ValueError("Market-wide context requires BTCUSDT in universe")
    if type(asof_ms) is not int or asof_ms <= 0 or asof_ms % FRAMES_MS["15m"]:
        raise ValueError("Decision must be at completed 15m UTC boundary")
    if not isinstance(source_frames, list):
        raise ValueError("Explicit source frame list required")

    allowed = set(universe)
    latest = {}
    identities = set()
    for raw in source_frames:
        r = _frame(raw, allowed)
        identity = (r["symbol"], r["timeframe"], r["closed_boundary_ms"])
        if identity in identities:
            raise ValueError("Duplicate source frame at frozen boundary")
        identities.add(identity)
        if r["closed_boundary_ms"] > asof_ms or r["available_at_ms"] > asof_ms:
            continue
        key = (r["symbol"], r["timeframe"])
        prior = latest.get(key)
        if prior is None or r["closed_boundary_ms"] > prior["closed_boundary_ms"]:
            latest[key] = r

    markets, selected_for_digest = {}, []
    summary = Counter()
    for symbol in universe:
        by_frame = {}
        missing = []
        for tf, step in FRAMES_MS.items():
            expected = (asof_ms // step) * step
            frame = latest.get((symbol,tf))
            if frame is None or frame["closed_boundary_ms"] != expected:
                missing.append(tf)
            else:
                by_frame[tf] = frame
        if missing:
            markets[symbol] = {
                "status":"MISSING_OR_UNAVAILABLE_CONTEXT",
                "missing_timeframes":missing,
            }
            continue
        votes = {tf:_trend(row) for tf,row in by_frame.items()}
        for tf in ("15m", "1h", "4h"):
            summary[f"{tf}_{votes[tf]}"] += 1
        if votes["1h"] == votes["4h"] and votes["1h"] != "mixed":
            alignment = votes["1h"]
        else:
            alignment = "conflicting"
        markets[symbol] = {
            "status":"COMPLETE_ASOF_FRAMES_RESEARCH_ONLY",
            "trend_by_timeframe":votes,
            "higher_timeframe_alignment":alignment,
            "hourly_atr_percent_close":str(
                D(by_frame["1h"]["atr"]) / D(by_frame["1h"]["close"]) * D(100)
            ),
            "source_timeframes": {
                tf:{
                    "closed_boundary_ms":by_frame[tf]["closed_boundary_ms"],
                    "available_at_ms":by_frame[tf]["available_at_ms"],
                    "source_sha256":by_frame[tf]["source_sha256"],
                } for tf in FRAMES_MS
            },
        }
        selected_for_digest.extend(by_frame.values())
    n = sum(x["status"] == "COMPLETE_ASOF_FRAMES_RESEARCH_ONLY"
            for x in markets.values())
    missing_symbols = [s for s in universe if (
        markets[s]["status"] != "COMPLETE_ASOF_FRAMES_RESEARCH_ONLY"
    )]
    digest = sha256(json.dumps(
        sorted(selected_for_digest,key=lambda r: (
            r["symbol"],r["timeframe"],r["closed_boundary_ms"]
        )),sort_keys=True,separators=(",",":")
    ).encode()).hexdigest()
    ready = n >= MIN_HEALTHY_MARKETS and (
        markets[REQUIRED_LEADER]["status"] ==
        "COMPLETE_ASOF_FRAMES_RESEARCH_ONLY"
    )
    return {
        "schema":1,
        "status":"HEALTHY_RESEARCH_CONTEXT_NOT_TRADING_SIGNAL" if ready
                 else "INSUFFICIENT_SYNCHRONIZED_CONTEXT_NO_GLOBAL_MARKET_CLAIM",
        "asof_decision_ms":asof_ms,
        "expected_markets":UNIVERSE_SIZE,
        "ready_markets":n,
        "minimum_healthy_markets_for_research":MIN_HEALTHY_MARKETS,
        "market_coverage_fraction":str(D(n)/D(UNIVERSE_SIZE)),
        "missing_markets":missing_symbols,
        "trend_counts":dict(sorted(summary.items())),
        "btc_context_ready": (
            markets[REQUIRED_LEADER]["status"] ==
            "COMPLETE_ASOF_FRAMES_RESEARCH_ONLY"
        ),
        "snapshot_input_sha256":digest,
        "markets":markets,
        "signal_action":"NONE_RESEARCH_CONTEXT_ONLY",
        "limitations":[
            "Only completed time-aligned price/EMA/ATR/volume fields are represented",
            "No historic order book, stop locations, liquidation, crowd sentiment or actual exchange fills",
            "Min 24/30 is an observation-quality threshold not an entry/filter policy",
            "Partial smoke subsets cannot be interpreted as the state of all 30 markets",
            "No signals, confidence forecasts, AI model action or trading authorization are produced",
        ],
    }
