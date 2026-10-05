"""Independent Fraction accounting/cohort checks on the actual full exit-study ledger."""
import importlib.util
from fractions import Fraction as F
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location("baseline_verifier", ROOT / "tools/verify-backtest.py")
verifier = importlib.util.module_from_spec(module)
module.loader.exec_module(verifier)
from app.research.reports import read_study, study_download, read_report
from app.research.runner import code_hash
from app.research.dataset import load_manifest, DATA_ROOT
from app.config import get_settings
import httpx


def main():
    report = read_study()
    assert report is not None
    verifier.verify_source(report)
    baseline = read_report()
    assert report["baseline_report_id"] == baseline["id"]
    assert report["baseline_report_hash"] == baseline["report_hash"]
    verifier.verify_source(baseline)
    manifest = load_manifest()
    assert manifest["dataset_hash"] == report["dataset_hash"]
    for name in report["files"]:
        study_download(name)
    ledger = [json.loads(line) for line in study_download("trades.jsonl")[0].read_text().splitlines()]
    funding = {symbol: json.loads((DATA_ROOT / item["file"]).read_text()) for symbol, item in manifest["funding"].items()}
    scenarios = {s["id"]: s for s in report["research"]["scenarios"]}
    oracle_report = {**report, "provenance": report["provenance"]}
    policies = {p["id"]: p for p in report["study"]["policies"]}
    original = [json.loads(line) for line in verifier.download_path("trades.jsonl")[0].read_text().splitlines()]
    control = [{k: v for k, v in t.items() if k != "exit_policy"} for t in ledger if t["exit_policy"] == "baseline"]
    assert control == original
    for trade in ledger:
        verifier.verify_trade(trade, oracle_report, funding, scenarios)
        policy = policies[trade["exit_policy"]]
        assert trade["plan"]["strategy"] == policy["strategy"]
        assert policy["target"] or trade["exit_reason"] not in ("target", "target_gap")
        assert policy["ema50_exit"] or trade["exit_reason"] != "ema50_exit"
        if trade["exit_policy"] != "baseline":
            assert trade["plan"]["target_active"] == policy["target"]
            assert trade["plan"]["ema50_exit_active"] == policy["ema50_exit"]
    for group, diagnostic in zip(report["groups"], report["diagnostics"]):
        identity = {k: group[k] for k in ("partition", "scenario", "exit_policy")}
        assert all(diagnostic[k] == value for k, value in identity.items())
        trades = [t for t in ledger if all(t[k] == v for k, v in identity.items())]
        assert len(trades) == group["metrics"]["trades"] == diagnostic["summary"]["trades"]
        for key in ("net_pnl", "gross_pnl", "fees", "funding_pnl"):
            value = sum((F(t[key]) for t in trades), F(0))
            verifier.near(value, F(group["metrics"][key]))
            verifier.near(value, F(diagnostic["summary"][key]))
        expected_cohorts = {key: {} for key in diagnostic["dimensions"]}
        reached = losers_reached = 0
        for trade in trades:
            source, previous = (trade["evidence"][key] for key in ("source", "previous"))
            atr = F(source["atr"])
            raw = {"atr_fraction": atr / F(source["ohlcv"]["close"]),
                   "ema_gap_atr": abs(F(source["ema20"]) - F(source["ema50"])) / atr,
                   "aligned_ema50_slope_atr": (F(source["ema50"]) - F(previous["ema50"])) / atr * (1 if trade["direction"] == "long" else -1)}
            for dimension in expected_cohorts:
                cohort = str(sum(raw[dimension] >= F(edge) for edge in report["study"]["diagnostics"][dimension+"_edges"])) if dimension in raw else trade[dimension]
                value = expected_cohorts[dimension].setdefault(cohort, [0, F(0), F(0)])
                value[0] += 1
                value[1] += F(trade["net_pnl"])
                value[2] += F(trade["net_r"])
            moved = F(trade["mfe_observed"]) * F(trade["quantity"]) >= F(trade["initial_risk_usdt"])
            reached += moved
            losers_reached += moved and F(trade["net_pnl"]) < 0
        assert diagnostic["summary"]["observed_at_least_1r"] == reached
        assert diagnostic["summary"]["losers_observed_at_least_1r"] == losers_reached
        for dimension, expected in expected_cohorts.items():
            actual = {row["cohort"]: row for row in diagnostic["dimensions"][dimension]}
            assert actual.keys() == expected.keys()
            for key, (count, pnl, total_r) in expected.items():
                assert actual[key]["trades"] == count
                verifier.near(F(actual[key]["net_pnl"]), pnl)
                verifier.near(F(actual[key]["expectancy_r"]), total_r/count)
        if group["exit_policy"] == "baseline":
            old = next(g for g in baseline["groups"] if g["partition"] == group["partition"] and g["scenario"] == group["scenario"])
            assert {k:v for k,v in group.items() if k not in ("exit_policy", "strategy", "return_delta_vs_baseline")} == old
    with httpx.Client(timeout=20) as client:
        actual = client.get("http://127.0.0.1:8000/v1/research/study", headers={"Authorization": f"Bearer {get_settings().dev_api_token}"}).raise_for_status().json()
        assert actual["report"] == report
    result = {"study_id": report["id"], "dataset_hash": report["dataset_hash"], "code_hash": report["code_hash"],
              "experiments": len(report["groups"]), "trades_checked": len(ledger),
              "checks": "Every trade: independent rational rules/risk/fills/fees/funding/P&L; all cohorts/counts/expectancy/observed 1R; original controls, exports and actual API passed"}
    (ROOT / "artifacts/exit-study-verification.json").write_text(json.dumps(result,indent=2), encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
