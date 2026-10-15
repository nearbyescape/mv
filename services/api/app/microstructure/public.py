"""Fixed-origin public USD-M REST reads; no orders, credentials, or subscriptions.

Order-book point snapshots do NOT reconstruct Binance diff-depth sequences;
this is a research-level top-20 visible-liquidity observation only.
"""
from __future__ import annotations

import asyncio
import time

import httpx

from .core import SYMBOLS, normalize

ORIGIN="https://fapi.binance.com"
PATHS={
    "server_time":"/fapi/v1/time",
    "depth":"/fapi/v1/depth",
    "open_interest":"/fapi/v1/openInterest",
    "taker":"/futures/data/takerlongshortRatio",
    "premium":"/fapi/v1/premiumIndex",
}


def wall_ms():
    return time.time_ns()//1_000_000


async def capture_symbol(client:httpx.AsyncClient,symbol:str) -> dict:
    if symbol not in SYMBOLS:
        raise ValueError("Symbol not in frozen small-market research universe")
    started=wall_ms()
    payload={}
    for name,path in PATHS.items():
        params=(
            {"symbol":symbol,"limit":20} if name=="depth" else
            {"symbol":symbol,"period":"5m","limit":3} if name=="taker" else
            {"symbol":symbol} if name in ("open_interest","premium") else {}
        )
        response=await client.get(ORIGIN+path,params=params,timeout=4)
        if response.status_code in (418,429):
            raise RuntimeError("EXCHANGE_RATE_LIMIT_NO_AUTO_RETRY")
        if response.status_code==451:
            raise RuntimeError("PUBLIC_BINANCE_DATA_HTTP_451_REGION_OR_LEGAL_RESTRICTION")
        response.raise_for_status()
        if len(response.content)>150_000:
            raise ValueError("Unexpectedly large public response")
        payload[name]=response.json()
    observed=wall_ms()
    return normalize(symbol,payload,observed,started_ms=started)


async def capture_all(symbols=SYMBOLS):
    """Sequential six-symbol probe: bounded requests, no auto retries.

    Caller must explicitly allow public network from the CLI. A single
    failed market is surfaced as a failure rather than a silently guessed
    observation or a trade.
    """
    if not symbols or len(symbols)>len(SYMBOLS) or len(set(symbols))!=len(symbols) or any(s not in SYMBOLS for s in symbols):
        raise ValueError("Unsupported market set")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(4), follow_redirects=False,
        trust_env=False, headers={"User-Agent":"mv-microstructure-paper-v1"}
    ) as client:
        results=[]
        for symbol in symbols:
            results.append(await capture_symbol(client,symbol))
        return results
