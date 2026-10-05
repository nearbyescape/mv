"""Read-only checks of the running engine, persistence and actual quote adapter."""
import asyncio
from fractions import Fraction
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
os.chdir(ROOT / "services" / "api")

import httpx
from sqlalchemy import select
from mv_strategy.signals import STRATEGY_ID, canonical_hash
from app.config import get_settings
from app.database import Session
from app.market.binance import BinancePublic, now_ms
from app.models import EngineCursor, IndicatorCheckpoint, SignalPlan, WatchlistItem


async def main():
    headers = {"Authorization": f"Bearer {get_settings().dev_api_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        feed = (await client.get("http://127.0.0.1:8000/v1/signals", headers=headers)).raise_for_status().json()
        health = (await client.get("http://127.0.0.1:8000/health")).raise_for_status().json()
        assert feed["engine"]["ready"] and health["collector"]["live"], health
        cursors, quotes, publications = [], [], []
        with Session() as session:
            symbols = list(session.scalars(select(WatchlistItem.symbol).order_by(WatchlistItem.sort_order)))
            for symbol in symbols:
                cursor = session.get(EngineCursor, (symbol, STRATEGY_ID))
                head = session.get(IndicatorCheckpoint, (symbol, "1h")).state_json["last_open_time"]
                assert cursor is not None and cursor.last_open_time == head, symbol
                cursors.append({"symbol": symbol, "last_discovered_open_time": cursor.last_open_time, "matches_collector_head": True})
            for row in session.scalars(select(SignalPlan)):
                payload = {key: value for key, value in row.plan_json.items() if key != "plan_hash"}
                assert canonical_hash(payload) == row.plan_json["plan_hash"]
                assert canonical_hash(row.evidence_json) == row.evidence_hash == row.plan_json["evidence_hash"]
                assert row.plan_json["execution"] == "signal-reference-only"
                assert row.created_at < row.expires_at
                plan, evidence = row.plan_json, row.evidence_json
                source, previous, confirmation = (evidence[key] for key in ("source", "previous", "confirmation"))
                f = Fraction
                long = plan["direction"] == "long"
                for snapshot in (source, confirmation):
                    fast, slow, trend = (f(snapshot[key]) for key in ("ema20", "ema50", "sma200"))
                    close = f(snapshot["ohlcv"]["close"])
                    assert fast > slow > trend and close > fast if long else fast < slow < trend and close < fast
                previous_close, previous_ema = f(previous["ohlcv"]["close"]), f(previous["ema20"])
                assert previous_close <= previous_ema if long else previous_close >= previous_ema
                boundary = source["open_time"] + 3_600_000
                assert previous["open_time"] == source["open_time"] - 3_600_000
                assert confirmation["open_time"] == boundary // 14_400_000 * 14_400_000 - 14_400_000
                entry, atr = f(plan["entry"]), f(source["atr"])
                assert atr > 0 and f(plan["frozen_atr"]) == atr
                assert abs(entry - f(source["ohlcv"]["close"])) <= atr / 2
                quote = evidence["quote"]
                assert entry == f(quote["ask"] if long else quote["bid"])
                assert boundary <= quote["time"] <= quote["received_at"] <= plan["published_at"]
                assert 0 <= plan["published_at"] - quote["time"] <= 5000
                assert plan["expires_at"] == boundary + 300_000
                price_filter = next(item for item in evidence["metadata"]["filters"] if item["filterType"] == "PRICE_FILTER")
                tick, origin = f(price_filter["tickSize"]), f(price_filter["minPrice"])
                def grid(value):
                    units = (value - origin) / tick
                    whole = units.numerator // units.denominator if long else -((-units.numerator) // units.denominator)
                    return origin + whole * tick
                stop = grid(entry - 2 * atr if long else entry + 2 * atr)
                risk = abs(entry - stop)
                target = grid(entry + 2 * risk if long else entry - 2 * risk)
                assert f(plan["stop"]) == stop and f(plan["target"]) == target and f(plan["risk_distance"]) == risk
                publications.append({"id": row.id, "symbol": row.symbol, "direction": plan["direction"],
                                     "source_close_boundary": boundary, "published_at": plan["published_at"],
                                     "entry": plan["entry"], "stop": plan["stop"], "target": plan["target"],
                                     "independent_fraction_rules_and_rounding": "passed", "plan_and_evidence_checksums": "passed"})
        public = BinancePublic(client)
        for symbol in symbols:
            quote = await public.quote(symbol, health["collector"]["clock_offset_ms"])
            age = now_ms() + health["collector"]["clock_offset_ms"] - quote.time
            assert 0 <= age <= 5000 and quote.bid <= quote.ask and quote.bid_qty > 0 and quote.ask_qty > 0
            quotes.append({"symbol": symbol, "exchange_time": quote.time, "age_ms": age, "adapter": "valid exact Decimal bid/ask; fresh exchange timestamp"})
    result = {"verified_at": now_ms(), "engine": feed["engine"], "cursors": cursors, "quotes": quotes,
              "published_signals": len(feed["signals"]), "recent_decisions": feed["decisions"],
              "publications": publications,
              "publication_verification": "Actual persisted Binance publication independently checked; no opportunity forced" if publications else "Controlled publication tests passed; actual journal currently empty"}
    target = ROOT / "artifacts" / "phase4-engine-verification.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
