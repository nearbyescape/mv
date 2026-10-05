"""Local forward shadow observer. Public reads, separate journal, no live plan mutations."""
import argparse
import asyncio
from decimal import Decimal as D
import hashlib
import json
from pathlib import Path
import httpx
from filelock import FileLock, Timeout
from mv_strategy.backtest import Replay, Costs, Funding, validate_minute
from mv_strategy.signals import PriceFilter, canonical_hash
from mv_strategy.entry_filters import ENTRY_POLICIES
from app.database import Session
from app.models import MarketContract
from app.market.binance import BinancePublic, now_ms, validate_contract
from app.market.views import collector_health
from app.signals.service import check_contract, context_at, snapshot_at, data_guard
from app.research.runner import code_hash
from app.research.reports import read_filters
from . import store
from .state import restore, decode


def implementation_hash():
    return canonical_hash({"research": code_hash(), "paper": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(__file__).parent.glob("*.py"))},
                           "context_sources": {name: hashlib.sha256((store.ROOT/name).read_bytes()).hexdigest() for name in (
                               "services/api/app/signals/service.py", "services/api/app/market/binance.py", "services/api/app/market/views.py",
                               "services/api/app/market/store.py", "services/api/app/models.py", "services/api/app/database.py")},
                           "live_strategy": hashlib.sha256((store.ROOT/"packages/contracts/strategy-v1.json").read_bytes()).hexdigest()})


def frozen_specs():
    spec, filters = json.loads(store.SPEC.read_text()), json.loads(store.FILTER_SPEC.read_text())
    expected = [{"id": key, "strategy": val[0], "feature": val[1], "minimum": val[2]} for key, val in ENTRY_POLICIES.items()]
    if filters["policies"] != expected or spec["filter_spec"] != filters["id"] or spec["policies"] != list(ENTRY_POLICIES) or spec["symbols"] != ["BTCUSDT", "ETHUSDT"] or spec["duration_days"] != 90 or spec["observation_grace_ms"] != 120000:
        raise ValueError("Forward versioned policy mismatch")
    return spec, filters


def parse_settlements(rows, symbol, start, end):
    result, previous = [], None
    for row in rows:
        if row.get("symbol") != symbol or type(row.get("fundingTime")) is not int or any(not isinstance(row.get(k), str) for k in ("fundingRate", "markPrice")):
            raise ValueError("Invalid forward funding response")
        event = Funding(row["fundingTime"], D(row["fundingRate"]), D(row["markPrice"]))
        event.validate()
        if previous is not None and event.time <= previous:
            raise ValueError("Funding duplicate or out of order")
        previous = event.time
        if start <= event.time <= end:
            result.append(event)
    return result


async def enroll(db, public):
    spec, filters = frozen_specs()
    study = read_filters()
    if study is None or study["study"] != filters or study["code_hash"] != code_hash():
        raise ValueError("Verified current filter study required before forward registration")
    server, offset = await public.clock()
    start = (server // 60_000 + 1) * 60_000
    end = ((start + spec["duration_days"]*86_400_000 + 3_599_999)//3_600_000)*3_600_000
    costs = Costs(*(D(spec["costs"][k]) for k in ("fee_bps", "spread_bps", "slippage_bps")), spec["costs"]["latency_ms"])
    metadata, origins, next_funding, engines = {}, {}, {}, {}
    for symbol in spec["symbols"]:
        with Session() as session:
            source, previous, confirmation, contract, _ = context_at(session, symbol, server//3_600_000*3_600_000-3_600_000)
            if source is None or previous is None or confirmation is None or data_guard(session, symbol, source, previous, confirmation, contract, now_ms()):
                raise ValueError("Live collector/context not ready for forward registration")
            metadata[symbol] = next(f for f in contract.metadata_json["filters"] if f["filterType"] == "PRICE_FILTER")
            origins[symbol] = {"1h": source.history_origin, "4h": confirmation.history_origin}
        schedule = await public.get("/fapi/v1/premiumIndex", symbol=symbol)
        if schedule.get("symbol") != symbol or type(schedule.get("nextFundingTime")) is not int or schedule["nextFundingTime"] <= server:
            raise ValueError("Missing upcoming funding schedule")
        next_funding[symbol] = schedule["nextFundingTime"]
        price = metadata[symbol]
        price_filter = PriceFilter(*(D(price[k]) for k in ("tickSize", "minPrice", "maxPrice")))
        for policy in spec["policies"]:
            engine = Replay(symbol, {"1h": {}, "4h": {}}, [], price_filter, costs, start//3_600_000*3_600_000, end, D(spec["capital_per_policy_usdt"])/len(spec["symbols"]), entry_policy=policy)
            engine.start = start
            engine.curve[0]["time"] = start
            engines[(symbol, policy)] = engine
    final_server, _ = await public.clock()
    if final_server >= start:
        raise ValueError("Enrollment crossed start minute; retry with future start")
    payload = {"id": canonical_hash({"start": start, "spec": spec, "filters": filters, "study": study["id"], "code": implementation_hash()}),
               "registered_at": final_server, "start": start, "end_exclusive": end, "spec": spec, "filters": filters,
               "filter_report_id": study["id"], "filter_report_hash": study["report_hash"], "code_hash": implementation_hash(),
               "price_filters": metadata, "history_origins": origins, "next_funding_initial": next_funding, "clock_offset_at_registration": offset}
    store.register(db, payload, engines, now_ms())
    print(f"Registered forward shadow sample {payload['id']} from {start}; six flat sleeves, no old entries", flush=True)


def revision_guard(db, session, symbol, engines, bars):
    # REST overlaps the last observed minute. Retain every observation; never rewrite it.
    by_time = {bar.open_time: bar for bar in bars}
    last = db.execute("SELECT * FROM observations WHERE symbol=? ORDER BY time DESC LIMIT 1", (symbol,)).fetchone()
    if last and last["time"] in by_time and decode(store.checked(last)["bar"]).digest() != by_time[last["time"]].digest():
        raise ValueError("Observed minute source correction")
    recorded = db.execute("SELECT * FROM observations WHERE symbol=? AND time%3600000=0 ORDER BY time DESC LIMIT 24", (symbol,)).fetchall()
    for row in recorded:
        context = decode(store.checked(row)["context"])
        for timeframe in context:
            for snapshot in context[timeframe].values():
                current = snapshot_at(session, symbol, timeframe, snapshot.bar.open_time)
                if current is None or current.evidence() != snapshot.evidence():
                    raise ValueError("Frozen source/indicator lineage correction")
    for engine in engines.values():
        if engine.position or engine.pending:
            evidence = engine.position["evidence"] if engine.position else {k: engine.pending[k].evidence() for k in ("source", "previous", "confirmation")}
            for key in ("source", "previous", "confirmation"):
                frozen = evidence[key]
                current = snapshot_at(session, symbol, frozen["timeframe"], frozen["open_time"])
                if current is None or current.evidence() != frozen:
                    raise ValueError("Active paper source correction")


async def tick(db, public):
    row = db.execute("SELECT * FROM run").fetchone()
    if row["state"] in ("frozen", "completed"):
        return False
    run = store.checked(row)
    spec, filters = frozen_specs()
    if run["spec"] != spec or run["filters"] != filters or run["code_hash"] != implementation_hash():
        raise ValueError("Frozen forward code/contract changed")
    server, _ = await public.clock()
    for symbol in spec["symbols"]:
        states = list(db.execute("SELECT * FROM sleeves WHERE symbol=?", (symbol,)))
        engines = {s["policy"]: restore(store.checked(s)) for s in states}
        cursor = states[0]["cursor"]
        if any(s["cursor"] != cursor for s in states):
            raise ValueError("Paper cursors diverged")
        if cursor >= run["end_exclusive"] or server < cursor+60_000+spec["completed_minute_settle_ms"]:
            continue
        if server-cursor-60_000 > spec["observation_grace_ms"]:
            raise ValueError("Observation gap exceeds frozen grace")
        end_time = min((server-spec["completed_minute_settle_ms"])//60_000*60_000-1, run["end_exclusive"]-1)
        raw = await public.get("/fapi/v1/klines", symbol=symbol, interval="1m", startTime=cursor-60_000, endTime=end_time, limit=5)
        from mv_strategy.indicators import Bar
        bars = []
        for values in raw:
            if not isinstance(values, list) or len(values) < 7 or any(not isinstance(v, str) for v in values[1:6]):
                raise ValueError("Malformed paper minute")
            bar = Bar(values[0], values[6], *map(D, values[1:6]))
            validate_minute(bar)
            bars.append(bar)
        with Session() as session:
            if not collector_health(session)["live"]:
                raise RuntimeError("Collector not live; awaiting fresh context")
            contract = session.get(MarketContract, symbol)
            if not contract or not contract.valid or not 0 <= now_ms()-contract.checked_at <= 600_000 or not validate_contract(contract.metadata_json)[0]:
                raise RuntimeError("Contract metadata stale or invalid")
            price = next(f for f in contract.metadata_json["filters"] if f["filterType"] == "PRICE_FILTER")
            if price != run["price_filters"][symbol]:
                raise ValueError("Frozen exchange price filter changed")
            revision_guard(db, session, symbol, engines, bars)
        last = db.execute("SELECT * FROM observations WHERE symbol=? ORDER BY time DESC LIMIT 1", (symbol,)).fetchone()
        expected_funding = store.checked(last)["next_funding_time"] if last else run["next_funding_initial"][symbol]
        incoming = [bar for bar in bars if bar.open_time >= cursor]
        if not incoming:
            raise RuntimeError("Completed minute not yet available")
        for bar in incoming:
            if bar.open_time != cursor:
                raise ValueError("Missing/reordered forward minute")
            schedule = await public.get("/fapi/v1/premiumIndex", symbol=symbol)
            next_funding = schedule.get("nextFundingTime")
            if schedule.get("symbol") != symbol or type(next_funding) is not int:
                raise ValueError("Invalid upcoming funding schedule")
            rates = await public.get("/fapi/v1/fundingRate", symbol=symbol, startTime=bar.open_time-2000, endTime=bar.close_time, limit=20)
            events = parse_settlements(rates, symbol, bar.open_time, bar.close_time)
            if expected_funding <= bar.close_time and not any(expected_funding <= e.time <= expected_funding+2000 for e in events):
                raise RuntimeError("Due funding settlement/mark missing; no zero-funding assumption")
            if next_funding <= bar.close_time:
                raise RuntimeError("Upcoming funding schedule not advanced")
            context = {"1h": {}, "4h": {}}
            if bar.open_time%3_600_000 == 0:
                with Session() as session:
                    source, previous, confirmation, _, _ = context_at(session, symbol, bar.open_time-3_600_000)
                    if source and previous and confirmation:
                        contract = session.get(MarketContract, symbol)
                        guard = data_guard(session, symbol, source, previous, confirmation, contract, now_ms())
                        if guard:
                            raise RuntimeError("Forward decision context blocked: " + guard)
                if source is None or previous is None or confirmation is None:
                    raise RuntimeError("Required completed 1h/4h snapshots unavailable")
                if source.history_origin != run["history_origins"][symbol]["1h"] or confirmation.history_origin != run["history_origins"][symbol]["4h"]:
                    raise ValueError("Seeded history origin changed")
                context = {"1h": {s.bar.open_time: s for s in (source, previous)}, "4h": {confirmation.bar.open_time: confirmation}}
            observed_server, _ = await public.clock()
            store.commit_minute(db, symbol, bar, observed_server, context, events, engines, next_funding)
            cursor, expected_funding = bar.open_time+60_000, next_funding
    completed = all(s[0] >= run["end_exclusive"] for s in db.execute("SELECT cursor FROM sleeves"))
    with db:
        db.execute("UPDATE run SET heartbeat=?,state=?,error=NULL", (now_ms(), "completed" if completed else "observing"))
    return not completed


async def run(once=False):
    from app.config import get_settings
    if not get_settings().paper_enabled:
        raise SystemExit("Paper observation is disabled by owner configuration")
    check_contract()
    with store.connection() as db:
        async with httpx.AsyncClient(timeout=8) as client:
            public = BinancePublic(client)
            if db.execute("SELECT * FROM run").fetchone() is None:
                await enroll(db, public)
            while True:
                try:
                    active = await tick(db, public)
                except ValueError as exc:
                    with db:
                        db.execute("UPDATE run SET state='frozen',heartbeat=?,error=?", (now_ms(), str(exc)))
                    print(f"Forward sample frozen: {exc}", flush=True)
                    return
                except (RuntimeError, httpx.HTTPError, KeyError) as exc:
                    with db:
                        db.execute("UPDATE run SET heartbeat=?,state='waiting-data',error=?", (now_ms(), type(exc).__name__ + ': ' + str(exc)))
                    print(f"Forward observation waiting: {type(exc).__name__}", flush=True)
                    active = True
                if once or not active:
                    return
                await asyncio.sleep(20)


def main():
    parser = argparse.ArgumentParser(description="Local forward paper observer; no orders, fills are explicitly modeled")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    try:
        with FileLock(str(store.DB)+".lock", timeout=0):
            asyncio.run(run(args.once))
    except Timeout:
        raise SystemExit("Another local forward observer is running")


if __name__ == "__main__":
    main()
