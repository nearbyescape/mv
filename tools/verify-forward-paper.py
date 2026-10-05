"""Read-only rational and provenance checks of the actual forward journal."""
from fractions import Fraction as F
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location("baseline_verifier", ROOT/"tools/verify-backtest.py")
verifier = importlib.util.module_from_spec(module)
module.loader.exec_module(verifier)
from app.paper import store
from app.paper.state import decode, restore
from app.paper.worker import implementation_hash
from app.config import get_settings
from mv_strategy.signals import canonical_hash
import httpx


def main():
    with store.connection(readonly=True) as db:
        db.execute("BEGIN")
        row = db.execute("SELECT * FROM run").fetchone()
        run = store.checked(row)
        assert run["code_hash"] == implementation_hash()
        assert run["registered_at"] < run["start"]
        assert row["state"] == "observing"
        counts, last = {}, {}
        for observation in db.execute("SELECT * FROM observations ORDER BY symbol,time"):
            payload = store.checked(observation)
            bar = decode(payload["bar"])
            assert run["start"] <= bar.open_time < run["end_exclusive"]
            assert bar.open_time == last.get(observation["symbol"],run["start"])
            last[observation["symbol"]] = bar.open_time+60000
            lag = observation["received_at"]-bar.close_time-1
            assert run["spec"]["completed_minute_settle_ms"] <= lag <= run["spec"]["observation_grace_ms"]
            o,h,l,c = (F(getattr(bar,k)) for k in ("open","high","low","close"))
            assert 0 < l <= min(o,c) <= max(o,c) <= h and F(bar.volume) >= 0
            for event in decode(payload["funding"]):
                assert bar.open_time <= event.time <= bar.close_time and F(event.mark_price)>0
            counts[observation["symbol"]] = counts.get(observation["symbol"],0)+1
        sleeves = []
        for sleeve in db.execute("SELECT * FROM sleeves"):
            engine = restore(store.checked(sleeve))
            assert sleeve["cursor"] == last.get(sleeve["symbol"],run["start"])
            expected = F(engine.initial)+sum((F(t["net_pnl"]) for t in engine.trades),F(0))
            if engine.position:
                expected += F(engine.position["funding"])-F(engine.position["entry_fee"])
            verifier.near(F(engine.cash),expected)
            for trade in engine.trades:
                assert trade["plan"]["forward_run_id"] == run["id"]
                assert trade["plan"]["execution"] == "modeled-forward-minute-reference"
                assert canonical_hash({k:v for k,v in trade["evidence"].items() if k != "hash"}) == trade["evidence"]["hash"]
                long = trade["direction"] == "long"
                gross = (F(trade["exit_fill"])-F(trade["entry_fill"]))*F(trade["quantity"])*(1 if long else -1)
                fees = (F(trade["entry_fill"])+F(trade["exit_fill"]))*F(trade["quantity"])*F(run["spec"]["costs"]["fee_bps"])/10000
                verifier.near(gross,F(trade["gross_pnl"]))
                verifier.near(fees,F(trade["fees"]))
                verifier.near(gross-fees+F(trade["funding_pnl"]),F(trade["net_pnl"]))
            sleeves.append({"symbol":sleeve["symbol"],"policy":sleeve["policy"],"cursor":sleeve["cursor"],"trades":len(engine.trades),"cash":str(engine.cash)})
        assert len(sleeves) == 6 and sum(counts.values()) >= 2
    with httpx.Client(timeout=20) as client:
        api=client.get("http://127.0.0.1:8000/v1/paper",headers={"Authorization":f"Bearer {get_settings().dev_api_token}"}).raise_for_status().json()
        assert api["run"]["id"] == run["id"] and api["run"]["state"] == "observing"
        assert not api["run"]["assessment_ready"]
        assert api["previous_samples"][0]["state"] == "frozen"
    result={"run_id":run["id"],"state":"observing","observed_minutes_by_symbol":counts,"sleeves":sleeves,
            "checks":"Actual journal: immutable run/code/observation/state hashes, future enrollment, contiguous completed minutes, settling/grace timing, rational OHLC/cash reconciliation and protected API; prior frozen sample preserved. No live paper trade or profitability claim unless the ledger contains one."}
    (ROOT/"artifacts/forward-paper-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
