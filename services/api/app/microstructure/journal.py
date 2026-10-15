"""Separate SQLite append-only reference journal for V7 microstructure.

Hashes detect accidental/unsophisticated edits, NOT authenticity or exchange
signatures. No SQLAlchemy/production database; no external order/alert APIs.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from hashlib import sha256

from .core import (
    SYMBOLS, HORIZONS_MS, POLICY_SHA, canonical, digest, classify, horizon_mark,
    PARAMETERS,
)

SCHEMA="""
CREATE TABLE IF NOT EXISTS observations (
 symbol TEXT NOT NULL,
 observed_at_ms INTEGER NOT NULL,
 payload TEXT NOT NULL,
 payload_sha256 TEXT NOT NULL,
 prior_chain_sha256 TEXT NOT NULL,
 chain_sha256 TEXT NOT NULL,
 PRIMARY KEY(symbol, observed_at_ms)
);
CREATE TABLE IF NOT EXISTS paper_ideas (
 id TEXT PRIMARY KEY,
 symbol TEXT NOT NULL,
 decided_at_ms INTEGER NOT NULL,
 payload TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 CHECK(symbol IN ('BTCUSDT','ETHUSDT','SOLUSDT','XRPUSDT','DOGEUSDT','BNBUSDT'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_idea_symbol_time
 ON paper_ideas(symbol,decided_at_ms);
CREATE TABLE IF NOT EXISTS horizon_observations (
 idea_id TEXT NOT NULL REFERENCES paper_ideas(id),
 horizon_ms INTEGER NOT NULL,
 observed_at_ms INTEGER NOT NULL,
 payload TEXT NOT NULL,
 sha256 TEXT NOT NULL,
 PRIMARY KEY(idea_id,horizon_ms)
);
"""


def open_journal(path:Path,*, readonly=False):
    if not path.is_absolute():
        raise ValueError("Require exact absolute paper journal path")
    if path.is_symlink():
        raise ValueError("Do not follow paper DB symlink")
    if readonly and not path.is_file():
        raise FileNotFoundError("No paper journal has been created")
    if not readonly:
        if not path.parent.is_dir() or path.parent.is_symlink():
            raise ValueError("Existing real parent directory is required")
    url=path.resolve().as_uri()+"?mode=ro" if readonly else str(path)
    conn=sqlite3.connect(url,uri=readonly,timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    if readonly:
        conn.execute("PRAGMA query_only=ON")
    else:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(SCHEMA)
    return conn


def _chain(symbol,stamp,body_sha,prior):
    return sha256(f"{symbol}:{stamp}:{body_sha}:{prior}".encode()).hexdigest()


def checked(row):
    item=json.loads(row["payload"])
    if canonical(item)!=row["payload"] or digest(item)!=row["payload_sha256"]:
        raise ValueError("Microstructure evidence tampering or corrupt JSON")
    return item


def verify_chain(conn,symbol):
    if symbol not in SYMBOLS:
        raise ValueError("Unsupported market")
    last="-"
    count=0
    for row in conn.execute(
        "SELECT * FROM observations WHERE symbol=? ORDER BY observed_at_ms",
        (symbol,),
    ):
        item=checked(row)
        if item["symbol"]!=symbol or item["observed_at_ms"]!=row["observed_at_ms"]:
            raise ValueError("Mismatched evidence identity")
        current=_chain(symbol,row["observed_at_ms"],row["payload_sha256"],last)
        if row["prior_chain_sha256"]!=last or row["chain_sha256"]!=current:
            raise ValueError("Broken microstructure evidence hash chain")
        last=current
        count+=1
    return count


def record_snapshot(conn,snapshot):
    """Atomic append, proposal, and observed-outcome update.

    Replayed identical observation cannot create duplicate ideas, but an
    observation timestamp reused with changed market data is rejected.
    """
    symbol=snapshot.get("symbol")
    now=snapshot.get("observed_at_ms")
    if symbol not in SYMBOLS or type(now)!=int or now<=0:
        raise ValueError("Malformed market observation")
    if snapshot.get("eligible_for_live_trades") is not False:
        raise ValueError("Live trading eligibility is forbidden in research")
    if snapshot.get("depth_consistency")!="REST_POINT_SNAPSHOT_NOT_SEQUENCE_PROVED":
        raise ValueError("Source depth integrity contract changed")
    body=canonical(snapshot)
    hashed=digest(snapshot)
    with conn:
        existing=conn.execute(
            "SELECT * FROM observations WHERE symbol=? AND observed_at_ms=?",
            (symbol,now),
        ).fetchone()
        if existing is not None:
            checked(existing)
            if existing["payload_sha256"]!=hashed:
                raise ValueError("Non-identical duplicate observation")
            return {"stored":False,"decision":{"status":"ABSTAIN","reason":"DUPLICATE_OBSERVATION"}}
        last=conn.execute(
            "SELECT * FROM observations WHERE symbol=? ORDER BY observed_at_ms DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if last is not None and last["observed_at_ms"]>=now:
            raise ValueError("Out-of-order market sample; do not rewrite history")
        if last:
            checked(last)
            if last["chain_sha256"]!=_chain(
                symbol,last["observed_at_ms"],last["payload_sha256"],last["prior_chain_sha256"]
            ):
                raise ValueError("Prior evidence chain link inconsistent")
        before=last["chain_sha256"] if last else "-"
        conn.execute(
            "INSERT INTO observations VALUES(?,?,?,?,?,?)",
            (symbol,now,body,hashed,before,_chain(symbol,now,hashed,before)),
        )
        decision={"status":"ABSTAIN","reason":"WAIT_FOR_PREVIOUS_REAL_SAMPLE"}
        if last:
            previous=checked(last)
            decision=classify(previous,snapshot)

        if decision["status"]=="PAPER_CANDIDATE":
            last_idea=conn.execute(
                "SELECT decided_at_ms FROM paper_ideas WHERE symbol=? ORDER BY decided_at_ms DESC LIMIT 1",
                (symbol,),
            ).fetchone()
            active=conn.execute(
                "SELECT COUNT(*) FROM paper_ideas WHERE decided_at_ms>? AND decided_at_ms<?",
                (now-max(HORIZONS_MS),now),
            ).fetchone()[0]
            if last_idea and now-last_idea["decided_at_ms"]<PARAMETERS["same_symbol_cooldown_ms"]:
                decision={"status":"ABSTAIN","reason":"PAPER_SYMBOL_COOLDOWN"}
            elif active>=PARAMETERS["max_active_paper_ideas"]:
                decision={"status":"ABSTAIN","reason":"PAPER_PORTFOLIO_MAX_SLOTS"}
            else:
                unique=digest(decision)
                conn.execute(
                    "INSERT INTO paper_ideas VALUES (?,?,?,?,?)",
                    (unique,symbol,now,canonical(decision),unique),
                )
                decision={**decision,"idea_id":unique}
        _settle_horizons(conn,snapshot)
    return {"stored":True,"decision":decision}


def _settle_horizons(conn,current):
    now=current["observed_at_ms"]
    for idea in conn.execute(
        "SELECT * FROM paper_ideas WHERE symbol=? AND decided_at_ms<? AND decided_at_ms>=?",
        (current["symbol"],now,now-max(HORIZONS_MS)-900_000),
    ).fetchall():
        payload=json.loads(idea["payload"])
        if digest(payload)!=idea["sha256"]:
            raise ValueError("Paper idea ledger integrity failure")
        for horizon in HORIZONS_MS:
            elapsed=now-idea["decided_at_ms"]
            if not horizon<=elapsed<=horizon+600_000:
                continue
            exists=conn.execute(
                "SELECT 1 FROM horizon_observations WHERE idea_id=? AND horizon_ms=?",
                (idea["id"],horizon),
            ).fetchone()
            if exists:
                continue
            output={
                "idea_id":idea["id"],"symbol":current["symbol"],
                "horizon_ms":horizon,
                "observed_book_point_only":True,
                **horizon_mark(payload,current),
            }
            conn.execute(
                "INSERT INTO horizon_observations VALUES(?,?,?,?,?)",
                (idea["id"],horizon,now,canonical(output),digest(output)),
            )


def report(conn,*, verify=True):
    if verify:
        counts={symbol:verify_chain(conn,symbol) for symbol in SYMBOLS}
    else:
        counts={s:conn.execute(
            "SELECT COUNT(*) FROM observations WHERE symbol=?",(s,),
        ).fetchone()[0] for s in SYMBOLS}
    ideas=conn.execute("SELECT * FROM paper_ideas").fetchall()
    count_by_side={"LONG":0,"SHORT":0}
    for row in ideas:
        item=json.loads(row["payload"])
        if digest(item)!=row["sha256"] or item["symbol"]!=row["symbol"]:
            raise ValueError("Corrupted research idea")
        count_by_side[item["direction"]]+=1
    stats={}
    for horizon in HORIZONS_MS:
        vals=[]
        for row in conn.execute("SELECT * FROM horizon_observations WHERE horizon_ms=?",(horizon,)):
            p=json.loads(row["payload"])
            if digest(p)!=row["sha256"]:
                raise ValueError("Corrupted observed horizon")
            from decimal import Decimal as D
            vals.append(D(p["net_reference_R"]))
        stats[str(horizon//60_000)+"m"]={
            "observations":len(vals),
            "positive_net_R":sum(v>0 for v in vals),
            "mean_net_R":str(sum(vals)/len(vals)) if vals else None,
            "observed_positive_fraction":str(sum(v>0 for v in vals)/D(len(vals))) if vals else None,
            "intrabar_stop_target_order_verified":False,
        }
    return {
        "research_policy_sha256":POLICY_SHA,
        "source":"BINANCE_USDM_PUBLIC_REST_BOUNDED_POINT_IN_TIME",
        "per_symbol_verified_samples":counts,
        "paper_candidate_total":len(ideas),
        "paper_candidate_by_direction":count_by_side,
        "marked_horizons":stats,
        "next_action":"COLLECT_PROSPECTIVE_EVIDENCE_NOT_DEPLOY_SIGNALS",
        "independent_strategy_edge_proven":False,
        "client_publication_authorized":False,
        "orders_submitted":0,
        "telegram_messages_sent":0,
    }
