"""Read-only independent rational accounting checks of every actual research trade."""
import csv
from fractions import Fraction as F
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/api"))
os.chdir(ROOT / "services/api")
from app.research.reports import read_report, download_path
from app.research.dataset import DATA_ROOT, load_manifest
from app.research.runner import code_hash
from app.config import get_settings


def near(left, right):
    assert abs(left - right) < F("1e-24"), (left, right)


def verify_source(report):
    """Preserved original source identity survives separately versioned research additions."""
    if report["code_hash"] == code_hash():
        return
    from mv_strategy.signals import canonical_hash
    archive = ROOT / "artifacts/baseline-source" / report["code_hash"]
    manifest = json.loads((archive / "source-manifest.json").read_text())
    assert canonical_hash(manifest) == report["code_hash"]
    for relative, expected in manifest.items():
        source = (archive / relative).resolve()
        assert source.is_relative_to(archive.resolve())
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected


def verify_trade(trade, report, funding, scenarios):
    plan, evidence = trade["plan"], trade["evidence"]
    long = trade["direction"] == "long"
    source, previous, confirmation = (evidence[key] for key in ("source", "previous", "confirmation"))
    for snapshot in (source, confirmation):
        fast, slow, trend = (F(snapshot[key]) for key in ("ema20", "ema50", "sma200"))
        close = F(snapshot["ohlcv"]["close"])
        assert fast > slow > trend and close > fast if long else fast < slow < trend and close < fast
    assert F(previous["ohlcv"]["close"]) <= F(previous["ema20"]) if long else F(previous["ohlcv"]["close"]) >= F(previous["ema20"])
    boundary = source["open_time"] + 3_600_000
    assert confirmation["open_time"] == boundary // 14_400_000 * 14_400_000 - 14_400_000
    assert boundary < trade["entry_time"] < boundary + 300_000 and trade["entry_time"] <= trade["exit_time"]
    entry, atr = F(plan["entry"]), F(source["atr"])
    assert abs(entry - F(source["ohlcv"]["close"])) <= atr / 2
    tick_filter = report["provenance"]["filters"][trade["symbol"]]["price_filter"]
    tick, origin = F(tick_filter["tickSize"]), F(tick_filter["minPrice"])
    def grid(value, up):
        units = (value - origin) / tick
        whole = -((-units.numerator) // units.denominator) if up else units.numerator // units.denominator
        return origin + whole * tick
    stop = grid(entry - 2 * atr if long else entry + 2 * atr, not long)
    risk = abs(entry - stop)
    target = grid(entry + 2 * risk if long else entry - 2 * risk, not long)
    assert F(plan["stop"]) == stop and F(plan["target"]) == target
    costs = scenarios[trade["scenario"]]
    slippage = F(costs["slippage_bps"]) / 10_000
    exit_cost = (F(costs["slippage_bps"]) + F(costs["spread_bps"]) / 2) / 10_000
    assert F(trade["entry_fill"]) == grid(entry * (1 + slippage if long else 1 - slippage), long)
    assert F(trade["exit_fill"]) == grid(F(trade["exit_reference"]) * (1 - exit_cost if long else 1 + exit_cost), not long)
    quantity = F(trade["quantity"])
    gross = (F(trade["exit_fill"]) - F(trade["entry_fill"])) * quantity * (1 if long else -1)
    fees = (F(trade["exit_fill"]) + F(trade["entry_fill"])) * quantity * F(costs["fee_bps"]) / 10_000
    held_events = [event for event in funding[trade["symbol"]] if trade["entry_time"] < event["time"] <= trade["exit_time"]]
    funding_pnl = sum((quantity * F(event["mark_price"]) * F(event["rate"]) * (-1 if long else 1) for event in held_events), F(0))
    assert len(held_events) == trade["funding_events"]
    near(F(trade["gross_pnl"]), gross)
    near(F(trade["fees"]), fees)
    near(F(trade["funding_pnl"]), funding_pnl)
    near(F(trade["net_pnl"]), gross - fees + funding_pnl)


def main():
    report = read_report()
    assert report is not None
    verify_source(report)
    manifest = load_manifest()
    assert manifest["dataset_hash"] == report["dataset_hash"]
    for name in report["files"]:
        path, _ = download_path(name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == report["files"][name]
    trades_path, _ = download_path("trades.jsonl")
    ledger = [json.loads(line) for line in trades_path.read_text().splitlines()]
    funding = {symbol: json.loads((DATA_ROOT / item["file"]).read_text()) for symbol, item in manifest["funding"].items()}
    scenarios = {row["id"]: row for row in report["research"]["scenarios"]}
    for trade in ledger:
        verify_trade(trade, report, funding, scenarios)
    for group in report["groups"]:
        trades = [trade for trade in ledger if trade["partition"] == group["partition"] and trade["scenario"] == group["scenario"]]
        assert len(trades) == group["metrics"]["trades"]
        near(sum((F(trade["net_pnl"]) for trade in trades), F(0)), F(group["metrics"]["net_pnl"]))
    with httpx.Client(timeout=20) as client:
        response = client.get("http://127.0.0.1:8000/v1/research", headers={"Authorization": f"Bearer {get_settings().dev_api_token}"}).raise_for_status().json()
        assert response["report"] == report
    result = {"report_id": report["id"], "dataset_hash": manifest["dataset_hash"], "code_hash": report["code_hash"], "trades_checked": len(ledger),
              "independent_fraction_checks": "entry rules, alignment, drift, tick rounding, fills, both-side fees, actual funding and net P&L passed for every trade",
              "report_exports_and_api": "checksums and exact backend report passed"}
    (ROOT / "artifacts/backtest-verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
