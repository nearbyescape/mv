"""V6HBR market-context must require as-of synchronized market evidence."""
from copy import deepcopy
from datetime import datetime,timezone

import pytest

from app.research.v6hbr_market_context import (
    FRAMES_MS, snapshot_asof, UNIVERSE_SIZE
)

ASOF=int(datetime(2026,5,4,16,15,30,tzinfo=timezone.utc).timestamp()*1000)
UNIVERSE=["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","DOGEUSDT","BNBUSDT"] + [
    f"TEST{i:02d}USDT" for i in range(24)
]


def source(symbol,frame,*,bear=False,delta=0,late=False):
    step=FRAMES_MS[frame]
    end=(ASOF//step)*step + delta
    return {
        "symbol":symbol,"timeframe":frame,
        "closed_boundary_ms":end,
        "available_at_ms":end+(40_000 if late else 1_000),
        "close":"95" if bear else "105",
        "ema20":"98" if bear else "102",
        "ema50":"100",
        "sma200":"101",
        "atr":"2",
        "volume":"1000",
        "source_sha256":"a"*64,
    }


def frames(markets=UNIVERSE):
    return [
        source(s,frame,bear=(i>=20))
        for i,s in enumerate(markets)
        for frame in FRAMES_MS
    ]


def test_full_30_context_counts_market_breadth_but_never_generates_signals():
    inputs=frames()
    before=deepcopy(inputs)
    snapshot=snapshot_asof(UNIVERSE,inputs,ASOF)
    assert inputs==before
    assert snapshot["status"]=="HEALTHY_RESEARCH_CONTEXT_NOT_TRADING_SIGNAL"
    assert snapshot["ready_markets"]==30
    assert snapshot["market_coverage_fraction"]=="1"
    assert snapshot["missing_markets"]==[]
    assert snapshot["trend_counts"]["1h_bullish"]==20
    assert snapshot["trend_counts"]["1h_bearish"]==10
    assert snapshot["markets"]["BTCUSDT"]["higher_timeframe_alignment"]=="bullish"
    assert snapshot["markets"]["TEST23USDT"]["higher_timeframe_alignment"]=="bearish"
    assert snapshot["signal_action"]=="NONE_RESEARCH_CONTEXT_ONLY"
    assert len(snapshot["snapshot_input_sha256"])==64


def test_future_prices_cannot_influence_snapshot_even_if_provided():
    original=frames()
    baseline=snapshot_asof(UNIVERSE,original,ASOF)
    future=source("BTCUSDT","15m",delta=FRAMES_MS["15m"])
    future.update({"close":"99999","ema20":"1","ema50":"2","sma200":"3"})
    after=snapshot_asof(UNIVERSE,original+[future],ASOF)
    assert baseline==after
    shuffled=snapshot_asof(UNIVERSE,list(reversed(original)),ASOF)
    assert baseline==shuffled


def test_six_symbol_smoke_scope_cannot_masquerade_as_full_universe():
    x=snapshot_asof(UNIVERSE,frames(UNIVERSE[:6]),ASOF)
    assert x["ready_markets"]==6
    assert x["expected_markets"]==30
    assert x["market_coverage_fraction"]=="0.2"
    assert len(x["missing_markets"])==24
    assert x["status"].startswith("INSUFFICIENT")
    assert x["btc_context_ready"] is True
    assert x["signal_action"]=="NONE_RESEARCH_CONTEXT_ONLY"


def test_late_15m_or_stale_1h_source_never_forward_filled():
    inputs=frames()
    for r in inputs:
        if r["symbol"]=="ETHUSDT" and r["timeframe"]=="15m":
            r["available_at_ms"]=ASOF+10_000
        if r["symbol"]=="SOLUSDT" and r["timeframe"]=="1h":
            r["closed_boundary_ms"]-=FRAMES_MS["1h"]
            r["available_at_ms"]=r["closed_boundary_ms"]+1000
    snap=snapshot_asof(UNIVERSE,inputs,ASOF)
    assert snap["ready_markets"]==28
    assert snap["markets"]["ETHUSDT"]["missing_timeframes"]==["15m"]
    assert snap["markets"]["SOLUSDT"]["missing_timeframes"]==["1h"]


def test_29_ready_markets_without_btc_still_fail_global_context():
    x=snapshot_asof(UNIVERSE,frames(UNIVERSE[1:]),ASOF)
    assert x["ready_markets"]==29
    assert x["btc_context_ready"] is False
    assert x["status"].startswith("INSUFFICIENT")


def test_duplicate_and_source_available_before_close_fail_closed():
    inputs=frames()
    with pytest.raises(ValueError,match="Duplicate"):
        snapshot_asof(UNIVERSE,inputs+[deepcopy(inputs[0])],ASOF)
    inputs[0]["available_at_ms"]=inputs[0]["closed_boundary_ms"]-1
    with pytest.raises(ValueError,match="before"):
        snapshot_asof(UNIVERSE,inputs,ASOF)


def test_corrupt_prices_hash_and_out_of_universe_source_fail_closed():
    inputs=frames()
    inputs[0]["atr"]="NaN"
    with pytest.raises(ValueError,match="Nonfinite"):
        snapshot_asof(UNIVERSE,inputs,ASOF)
    inputs=frames()
    inputs[0]["source_sha256"]="unknown"
    with pytest.raises(ValueError,match="checksum"):
        snapshot_asof(UNIVERSE,inputs,ASOF)
    inputs=frames()
    inputs[0]["symbol"]="NOTINUNIVERSEUSDT"
    with pytest.raises(ValueError,match="outside"):
        snapshot_asof(UNIVERSE,inputs,ASOF)


def test_market_breadth_gate_requires_frozen_30_not_six():
    with pytest.raises(ValueError,match="30"):
        snapshot_asof(UNIVERSE[:6],frames(UNIVERSE[:6]),ASOF)
    with pytest.raises(ValueError,match="30"):
        snapshot_asof(UNIVERSE[:-1]+[UNIVERSE[0]],frames(),ASOF)
    with pytest.raises(ValueError,match="requires BTC"):
        snapshot_asof(UNIVERSE[1:]+["EXTRAUSDT"],frames(UNIVERSE[1:]),ASOF)
