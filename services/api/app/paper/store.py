"""Append-only observed minutes and atomic shadow checkpoints in a separate local SQLite DB."""
import json
from pathlib import Path
import sqlite3
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN
from mv_strategy.signals import canonical_hash
from .state import dump, restore, encode
from mv_strategy.backtest import validate_minute

ROOT = Path(__file__).resolve().parents[4]
DB = ROOT / "services/api/forward-paper-v2.db"
SPEC = ROOT / "packages/contracts/forward-paper-v2.json"
PREVIOUS_DB = ROOT / "services/api/forward-paper.db"
FILTER_SPEC = ROOT / "packages/contracts/filter-study-v1.json"


def connection(path=DB, readonly=False):
    if readonly:
        result = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    else:
        result = sqlite3.connect(path, timeout=10)
        result.execute("PRAGMA journal_mode=WAL")
        result.execute("PRAGMA synchronous=FULL")
        result.executescript("""
        CREATE TABLE IF NOT EXISTS run (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, hash TEXT NOT NULL, state TEXT NOT NULL, heartbeat INTEGER NOT NULL, error TEXT);
        CREATE TABLE IF NOT EXISTS sleeves (symbol TEXT NOT NULL, policy TEXT NOT NULL, cursor INTEGER NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(symbol,policy));
        CREATE TABLE IF NOT EXISTS observations (symbol TEXT NOT NULL, time INTEGER NOT NULL, received_at INTEGER NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY(symbol,time));
        """)
    result.row_factory = sqlite3.Row
    return result


def checked(row):
    payload = json.loads(row["payload"])
    if canonical_hash(payload) != row["hash"]:
        raise ValueError("Paper journal integrity failure")
    return payload


def register(db, payload, engines, now):
    with db:
        db.execute("INSERT INTO run VALUES (1,?,?,?, ?,NULL)", (json.dumps(payload), canonical_hash(payload), "observing", now))
        for (symbol, policy), engine in engines.items():
            state = dump(engine)
            db.execute("INSERT INTO sleeves VALUES (?,?,?,?,?)", (symbol, policy, payload["start"], json.dumps(state), canonical_hash(state)))


def commit_minute(db, symbol, bar, received_at, context, funding, engines, next_funding):
    """All policies for one symbol advance together; a crash cannot advance just one cursor."""
    with localcontext() as decimal_context:
        decimal_context.prec, decimal_context.rounding = 34, ROUND_HALF_EVEN
        run = checked(db.execute("SELECT * FROM run").fetchone())
        validate_minute(bar)
        if not 0 <= received_at - bar.close_time - 1 <= run["spec"]["observation_grace_ms"]:
            raise ValueError("Observation gap exceeds frozen grace")
        if any(e.start > bar.open_time or e.end <= bar.open_time for e in engines.values()):
            raise ValueError("Minute outside registered forward window")
        cursors = list(db.execute("SELECT * FROM sleeves WHERE symbol=?", (symbol,)))
        if len(cursors) != len(engines) or any(row["cursor"] != bar.open_time for row in cursors):
            raise ValueError("Noncontiguous or duplicate paper minute")
        payload = {"bar": encode(bar), "context": encode(context), "funding": encode(funding), "next_funding_time": next_funding}
        with db:
            db.execute("INSERT INTO observations VALUES (?,?,?,?,?)", (symbol, bar.open_time, received_at, json.dumps(payload), canonical_hash(payload)))
            for policy, engine in engines.items():
                engine.snapshots = context
                engine.funding, engine.funding_index = funding, 0
                engine.step(bar)
                # Clearly distinguish this forward model from historical and live plans.
                for item in ([engine.position] if engine.position else []) + [t for t in engine.trades if "forward_run_id" not in t["plan"]]:
                    plan, evidence = item["plan"], item["evidence"]
                    if "forward_run_id" not in plan:
                        plan.update({"forward_run_id": run["id"], "execution": "modeled-forward-minute-reference",
                                     "observed_at": received_at,
                                     "id": canonical_hash({"run": run["id"], "policy": policy, "decision": plan["id"]})})
                        evidence["quote"]["source"] = "modeled-from-newly-observed-1m-open"
                        evidence["observed_at"] = received_at
                        evidence["hash"] = canonical_hash({k: v for k, v in evidence.items() if k != "hash"})
                    if "signal_id" in item:
                        item["signal_id"] = plan["id"]
                engine.funding, engine.funding_index = [], 0
                state = dump(engine)
                db.execute("UPDATE sleeves SET cursor=?,payload=?,hash=? WHERE symbol=? AND policy=?", (bar.open_time+60_000, json.dumps(state), canonical_hash(state), symbol, policy))


def view(path=DB, now=None, include_previous=True):
    if not path.exists():
        return {"available": False, "run": None}
    import time
    now = now if now is not None else time.time_ns()//1_000_000
    with connection(path, readonly=True) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM run").fetchone()
        if row is None:
            return {"available": False, "run": None}
        payload = checked(row)
        with localcontext() as context:
            context.prec, context.rounding = 34, ROUND_HALF_EVEN
            sleeves = []
            for state in db.execute("SELECT * FROM sleeves ORDER BY policy,symbol"):
                engine = restore(checked(state))
                equity = D(engine.curve[-1]["equity"])
                sleeves.append({"symbol": state["symbol"], "policy": state["policy"], "cursor": state["cursor"],
                    "closed_trades": len(engine.trades), "cash": str(engine.cash), "last_hourly_equity": str(equity),
                    "net_pnl_closed": str(sum((D(t["net_pnl"]) for t in engine.trades), D(0))),
                    "fees_closed": str(sum((D(t["fees"]) for t in engine.trades), D(0))),
                    "funding_closed": str(sum((D(t["funding_pnl"]) for t in engine.trades), D(0))),
                    "mean_r_closed": str(sum((D(t["net_r"]) for t in engine.trades), D(0))/len(engine.trades)) if engine.trades else None,
                    "position": encode(engine.position), "pending": engine.pending is not None, "blocked": dict(engine.blocked),
                    "trades": engine.trades[-100:], "decisions": engine.decisions[-8:]})
        totals = {policy: sum(s["closed_trades"] for s in sleeves if s["policy"] == policy) for policy in payload["spec"]["policies"]}
        state = row["state"] if row["state"] in ("frozen", "completed", "stopped-by-owner") or 0 <= now-row["heartbeat"] <= 90_000 else "stale"
        previous = []
        if include_previous and PREVIOUS_DB.exists() and path.resolve() != PREVIOUS_DB.resolve():
            old = view(PREVIOUS_DB, now, include_previous=False)
            if old["available"]:
                previous.append({k:old["run"][k] for k in ("id","start","state","error","observed_minutes")})
        return {"available": True, "previous_samples": previous, "run": {**payload, "state": state, "heartbeat": row["heartbeat"], "error": row["error"],
                    "observed_minutes": db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], "sleeves": sleeves,
                    "assessment_ready": state == "completed" and all(v >= 100 for v in totals.values()),
                    "assessment": "Inconclusive until continuous 90-day window and 100 closed trades per policy; modeled shadow fills only."}}
