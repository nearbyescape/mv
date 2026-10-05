"""Registered exploratory exit comparisons on the pinned, already-viewed baseline data."""
import csv
from decimal import Decimal as D, localcontext, ROUND_HALF_EVEN
import hashlib
import io
import json
import os
from uuid import uuid4

from mv_strategy.backtest import Costs, Funding, Replay, EXIT_POLICIES, validate_minute
from mv_strategy.signals import PriceFilter, canonical_hash
from mv_strategy.research_metrics import aggregate
from mv_strategy.trade_diagnostics import diagnose
from mv_strategy.entry_filters import ENTRY_POLICIES
from .dataset import ROOT, DATA_ROOT, load_manifest, verified_path, timestamp, parse_funding
from .runner import code_hash, snapshots, execution_stream
from .reports import read_report, download_path

STUDY_ROOT = ROOT / "artifacts/exit-studies"
STUDY_SPEC = ROOT / "packages/contracts/exit-study-v1.json"


def replay_policies(symbol, bars, history, funding, price_filter, scenarios, start, end, capital, entry_study=False):
    with localcontext() as context:
        context.prec, context.rounding = 34, ROUND_HALF_EVEN
        registry = ENTRY_POLICIES if entry_study else EXIT_POLICIES
        engines = {(policy, scenario): Replay(symbol, history, funding, price_filter, costs, start, end, capital,
                    "baseline" if entry_study else policy, policy if entry_study else "baseline")
                   for policy in registry for scenario, costs in scenarios.items()}
        expected = start
        for bar in bars:
            validate_minute(bar)
            if bar.open_time != expected or bar.open_time >= end:
                raise ValueError("Missing, duplicate, reordered or out-of-window study minute")
            for engine in engines.values():
                engine.step(bar)
            expected += 60_000
        if expected != end:
            raise ValueError("Incomplete study execution coverage")
        return {key: engine.result() for key, engine in engines.items()}


def publish(report, files, root):
    report["files"] = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    report["report_hash"] = canonical_hash(report)
    files = {**files, "report.json": json.dumps(report, indent=2).encode()}
    root.mkdir(exist_ok=True, parents=True)
    target = root / report["id"]
    if target.exists():
        if any((target / name).read_bytes() != value for name, value in files.items()):
            raise ValueError("Identical exit-study identity produced different report/export bytes")
        print("Repeated exit study reproduced every report/export byte exactly", flush=True)
    else:
        staging = root / f".staging-{uuid4()}"
        staging.mkdir()
        for name, value in files.items():
            (staging / name).write_bytes(value)
        os.rename(staging, target)
    temporary = root / "latest.tmp"
    temporary.write_text(json.dumps({"id": report["id"], "report_hash": report["report_hash"]}), encoding="utf-8")
    os.replace(temporary, root / "latest.json")


def run(data_root=DATA_ROOT, report_root=STUDY_ROOT, entry_study=False):
    from app.signals.service import check_contract
    check_contract()
    study = json.loads((ROOT / "packages/contracts/filter-study-v1.json" if entry_study else STUDY_SPEC).read_text())
    registry = ENTRY_POLICIES if entry_study else EXIT_POLICIES
    field = "entry_policy" if entry_study else "exit_policy"
    baseline = read_report()
    if baseline is None or baseline["id"] != study["baseline_report_id"] or baseline["strategy"] != study["base_strategy"]:
        raise ValueError("Registered original baseline report required")
    expected_policies = [{"id": key, "strategy": value[0], **({"feature": value[1], "minimum": value[2]} if entry_study else {"target": value[1], "ema50_exit": value[2]})} for key, value in registry.items()]
    if study["policies"] != expected_policies or baseline["research"]["id"] != study["research_spec"]:
        raise ValueError("Versioned study/implementation policy mismatch")
    manifest = load_manifest(data_root)
    if manifest["dataset_hash"] != baseline["dataset_hash"] or manifest["spec_hash"] != canonical_hash(baseline["research"]):
        raise ValueError("Study must use the exact original dataset/spec")
    original_ledger = [json.loads(line) for line in download_path("trades.jsonl")[0].read_text().splitlines()]
    spec = baseline["research"]
    implementation_hash = code_hash()
    identity = canonical_hash({"study": study, "baseline_report_hash": baseline["report_hash"], "dataset": manifest["dataset_hash"], "code": implementation_hash})
    scenarios = {item["id"]: Costs(*(D(item[key]) for key in ("fee_bps", "spread_bps", "slippage_bps")), item["latency_ms"]) for item in spec["scenarios"]}
    members = {}
    for symbol in spec["symbols"]:
        history, _ = snapshots(data_root, manifest, symbol)
        entry = manifest["funding"][symbol]
        events = json.loads(verified_path(data_root, entry).read_text())
        parse_funding([{"symbol": symbol, "fundingTime": e["time"], "fundingRate": e["rate"], "markPrice": e["mark_price"]} for e in events], symbol, entry["start"], entry["end_exclusive"])
        funding = [Funding(e["time"], D(e["rate"]), D(e["mark_price"])) for e in events]
        price = manifest["metadata"][symbol]["price_filter"]
        price_filter = PriceFilter(*(D(price[key]) for key in ("tickSize", "minPrice", "maxPrice")))
        for partition in spec["partitions"]:
            start, end = timestamp(partition["start"]), timestamp(partition["end"])
            print(f"Exit study {symbol} {partition['name']}: all three policies and costs", flush=True)
            result = replay_policies(symbol, execution_stream(data_root, manifest, symbol, history, start, end), history, funding, price_filter, scenarios, start, end, D(spec["initial_capital_usdt"]) / len(spec["symbols"]), entry_study)
            for (policy, scenario), replay in result.items():
                members.setdefault((partition["name"], scenario, policy), []).append(replay)
    groups, ledger, diagnostic_groups = [], [], []
    for partition in spec["partitions"]:
        start, end = timestamp(partition["start"]), timestamp(partition["end"])
        for scenario in scenarios:
            for policy, policy_values in registry.items():
                rows = members[(partition["name"], scenario, policy)]
                portfolio = aggregate(rows, start, end)
                trades, curve = portfolio.pop("trades"), portfolio.pop("curve")
                group = {"partition": partition["name"], "scenario": scenario, "start": start, "end_exclusive": end, **portfolio,
                         "daily_curve": [p for p in curve if p["time"] % 86_400_000 == 0],
                         "symbols": [{"symbol": row["symbol"], **aggregate([row], start, end)["metrics"]} for row in rows],
                         "decision_hashes": {row["symbol"]: canonical_hash(row["decisions"]) for row in rows}}
                if policy == "baseline":
                    original = next(g for g in baseline["groups"] if g["partition"] == partition["name"] and g["scenario"] == scenario)
                    expected = [t for t in original_ledger if t["partition"] == partition["name"] and t["scenario"] == scenario]
                    if group != original or [{"partition": partition["name"], "scenario": scenario, **t} for t in trades] != expected:
                        raise ValueError("Baseline control differs from original financial results/evidence")
                groups.append({field: policy, "strategy": policy_values[0], **group})
                ledger.extend({"partition": partition["name"], "scenario": scenario, field: policy, **trade} for trade in trades)
                diagnostic_groups.append({"partition": partition["name"], "scenario": scenario, field: policy,
                                          **diagnose(trades, study["diagnostics"])})
    with localcontext() as context:
        context.prec, context.rounding = 34, ROUND_HALF_EVEN
        for group in groups:
            control = next(g for g in groups if g["partition"] == group["partition"] and g["scenario"] == group["scenario"] and g[field] == "baseline")
            group["return_delta_vs_baseline"] = str(D(group["metrics"]["return"]) - D(control["metrics"]["return"]))
    if code_hash() != implementation_hash:
        raise ValueError("Research source changed during study; rerun final implementation")
    report = {"schema": 1, "id": identity, "study": study, "research": spec,
              "baseline_report_id": baseline["id"], "baseline_report_hash": baseline["report_hash"],
              "baseline_control_parity": "All nine baseline groups and every original trade/evidence reproduced exactly",
              "dataset_hash": manifest["dataset_hash"], "code_hash": implementation_hash, "provenance": baseline["provenance"],
              "groups": groups, "diagnostics": diagnostic_groups, "assessment": study["evaluation"],
              "limitations": [*baseline["limitations"],
                  "Fixed slope and separation filters tested independently; thresholds informed by earlier diagnostics, not a fresh holdout. No combined policy." if entry_study else "Entry-time cohorts are descriptive, not tested entry filters. Exit-reason cohorts condition on an outcome and cannot prove causal improvement.",
                  "MAE/MFE and observed 1R counts omit exit-minute unknown extremes. They do not prove an achievable alternative fill or profit.",
                  "Different holding times change later entry eligibility and cash sizes. This compares full policies, not paired isolated exits of every identical trade.",
                  "All periods were previously inspected. No fresh holdout, significance claim, winner selection or live-policy promotion."]}
    stream = io.StringIO(newline="")
    fields = [key for key in ledger[0] if key not in ("plan", "evidence")]
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(ledger)
    files = {"trades.csv": stream.getvalue().encode(), "trades.jsonl": "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in ledger).encode(),
             "diagnostics.json": json.dumps(diagnostic_groups, indent=2).encode(),
             **{name: download_path(name)[0].read_bytes() for name in ("dataset-manifest.json", "source-audit.json")}}
    publish(report, files, report_root)
    print(f"Exit study {identity}: {len(groups)} experiments, {len(ledger)} overlapping trade records; original baseline parity passed", flush=True)
    return report
