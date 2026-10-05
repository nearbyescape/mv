"""Independent rational checks of every actual filter-study trade and original controls."""
import importlib.util
from fractions import Fraction as F
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location("baseline_verifier", ROOT/"tools/verify-backtest.py")
verifier = importlib.util.module_from_spec(module)
module.loader.exec_module(verifier)
from app.research.reports import read_filters, filter_download, read_report
from app.research.dataset import load_manifest, DATA_ROOT
from app.research.runner import code_hash
from app.config import get_settings
from mv_strategy.signals import canonical_hash
import httpx


def main():
    report, baseline = read_filters(), read_report()
    assert report["code_hash"] == code_hash()
    assert report["baseline_report_hash"] == baseline["report_hash"]
    verifier.verify_source(baseline)
    manifest = load_manifest()
    assert report["dataset_hash"] == manifest["dataset_hash"]
    for name in report["files"]:
        filter_download(name)
    ledger = [json.loads(line) for line in filter_download("trades.jsonl")[0].read_text().splitlines()]
    original = [json.loads(line) for line in verifier.download_path("trades.jsonl")[0].read_text().splitlines()]
    assert [{k:v for k,v in t.items() if k != "entry_policy"} for t in ledger if t["entry_policy"] == "baseline"] == original
    funding = {s:json.loads((DATA_ROOT/item["file"]).read_text()) for s,item in manifest["funding"].items()}
    scenarios = {s["id"]:s for s in report["research"]["scenarios"]}
    for trade in ledger:
        verifier.verify_trade(trade, report, funding, scenarios)
        evidence, policy = trade["evidence"], trade["entry_policy"]
        assert canonical_hash({k:v for k,v in evidence.items() if k != "hash"}) == evidence["hash"]
        source, previous = evidence["source"], evidence["previous"]
        if policy != "baseline":
            check = evidence["entry_filter"]
            assert check["passed"] and check["policy"] == policy
            assert trade["plan"]["research_entry_policy"] == policy
            atr = F(source["atr"])
            if policy == "slope":
                difference = (F(source["ema50"])-F(previous["ema50"]))* (1 if trade["direction"] == "long" else -1)
                assert difference >= F("0.05")*atr
            else:
                assert abs(F(source["ema20"])-F(source["ema50"])) >= F("0.5")*atr
    for group in report["groups"]:
        trades = [t for t in ledger if all(t[k]==group[k] for k in ("partition","scenario","entry_policy"))]
        assert len(trades) == group["metrics"]["trades"]
        for key in ("net_pnl","gross_pnl","fees","funding_pnl"):
            verifier.near(sum((F(t[key]) for t in trades),F(0)),F(group["metrics"][key]))
        if group["entry_policy"] == "baseline":
            old = next(g for g in baseline["groups"] if g["partition"]==group["partition"] and g["scenario"]==group["scenario"])
            assert {k:v for k,v in group.items() if k not in ("entry_policy","strategy","return_delta_vs_baseline")} == old
    with httpx.Client(timeout=20) as client:
        actual = client.get("http://127.0.0.1:8000/v1/research/filters",headers={"Authorization":f"Bearer {get_settings().dev_api_token}"}).raise_for_status().json()
        assert actual["report"] == report
    result = {"report_id":report["id"],"code_hash":report["code_hash"],"experiments":len(report["groups"]),"trades_checked":len(ledger),
              "checks":"Independent Fraction entry rules, each filter threshold, risk/grid, fills, fees, actual funding and P&L; all controls, group sums, evidence/export hashes and actual API passed"}
    (ROOT/"artifacts/filter-study-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
