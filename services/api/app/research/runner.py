"""Reproducible offline report generation; never writes the live signal database."""
import csv
from decimal import Decimal, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
from uuid import uuid4

from mv_strategy import IndicatorState
from mv_strategy.signals import Snapshot, PriceFilter, canonical_hash
from mv_strategy.backtest import Costs, Funding, replay_many
from mv_strategy.research_metrics import aggregate
from .dataset import ROOT, DATA_ROOT, SPEC_PATH, load_manifest, verified_path, stream_bars, timestamp, parse_funding

REPORT_ROOT = ROOT / "artifacts/backtests"


def snapshots(root, manifest, symbol):
    output, checkpoints = {}, {}
    for timeframe in ("1h", "4h"):
        state, output[timeframe] = IndicatorState(timeframe), {}
        for bar in stream_bars(root, manifest, symbol, timeframe):
            values = state.advance(bar)
            if all(v is not None for v in values.values()):
                output[timeframe][bar.open_time] = Snapshot(timeframe, bar, values["ema20"], values["ema50"], values["sma200"], values["atr"], state.count, state.history_origin, state.lineage)
        checkpoints[timeframe] = state.dump()
    # Validate actual independent 4H archives against complete groups of 1H bars.
    with localcontext() as context:
        context.prec = 34
        hourly = {snapshot.bar.open_time: snapshot.bar for snapshot in output["1h"].values()}
        for snapshot in output["4h"].values():
            group = [hourly.get(snapshot.bar.open_time + n * 3_600_000) for n in range(4)]
            if all(group):
                bar = snapshot.bar
                if (group[0].open, max(b.high for b in group), min(b.low for b in group), group[-1].close, sum((b.volume for b in group), Decimal(0))) != (bar.open, bar.high, bar.low, bar.close, bar.volume):
                    raise ValueError("1H/4H source archives disagree")
    return output, checkpoints


def code_hash():
    files = sorted([*(ROOT / "packages/strategy/mv_strategy").glob("*.py"), *(ROOT / "services/api/app/research").glob("*.py")])
    return canonical_hash({str(path.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest() for path in files})


def execution_stream(root, manifest, symbol, history, start, end):
    """Independently reconcile each complete 60-minute source group to its 1H archive."""
    opening = high = low = volume = None
    for bar in stream_bars(root, manifest, symbol, "1m", start, end):
        if bar.open_time % 3_600_000 == 0:
            opening, high, low, volume = bar.open, bar.high, bar.low, Decimal(0)
        high, low, volume = max(high, bar.high), min(low, bar.low), volume + bar.volume
        if (bar.open_time + 60_000) % 3_600_000 == 0:
            source = history["1h"][bar.open_time // 3_600_000 * 3_600_000].bar
            if (opening, high, low, bar.close, volume) != (source.open, source.high, source.low, source.close, source.volume):
                raise ValueError("1m execution data and 1H source archive disagree")
        yield bar


def run(data_root=DATA_ROOT, report_root=REPORT_ROOT):
    spec = json.loads(SPEC_PATH.read_text())
    strategy = json.loads((ROOT / "packages/contracts/strategy-v1.json").read_text())
    manifest = load_manifest(data_root)
    if manifest["spec_hash"] != canonical_hash(spec) or manifest["symbols"] != spec["symbols"]:
        raise ValueError("Dataset does not match preregistered research specification")
    # Reuse the live worker's explicit financial-contract compatibility gate.
    from app.signals.service import check_contract
    check_contract()
    implementation_hash = code_hash()
    identity = canonical_hash({"dataset": manifest["dataset_hash"], "spec": spec, "strategy": strategy, "code": implementation_hash})
    results, checkpoint_evidence = {}, {}
    scenarios = {item["id"]: Costs(*(Decimal(item[key]) for key in ("fee_bps", "spread_bps", "slippage_bps")), item["latency_ms"]) for item in spec["scenarios"]}
    symbol_sleeve = Decimal(spec["initial_capital_usdt"]) / len(spec["symbols"])
    for symbol in spec["symbols"]:
        history, checkpoint_evidence[symbol] = snapshots(data_root, manifest, symbol)
        funding_item = manifest["funding"][symbol]
        events = json.loads(verified_path(data_root, funding_item).read_text())
        # Validate normalized events without ever replacing missing funding with zero.
        raw = [{"symbol": symbol, "fundingTime": e["time"], "fundingRate": e["rate"], "markPrice": e["mark_price"]} for e in events]
        parse_funding(raw, symbol, funding_item["start"], funding_item["end_exclusive"])
        funding = [Funding(e["time"], Decimal(e["rate"]), Decimal(e["mark_price"])) for e in events]
        price = manifest["metadata"][symbol]["price_filter"]
        price_filter = PriceFilter(*(Decimal(price[key]) for key in ("tickSize", "minPrice", "maxPrice")))
        for partition in spec["partitions"]:
            start, end = timestamp(partition["start"]), timestamp(partition["end"])
            print(f"Replay {symbol} {partition['name']} ({partition['start']} to {partition['end']})", flush=True)
            replay = replay_many(symbol, execution_stream(data_root, manifest, symbol, history, start, end), history, funding, price_filter, scenarios, start, end, symbol_sleeve)
            for scenario, result in replay.items():
                results.setdefault((partition["name"], scenario), []).append(result)
    groups, ledger = [], []
    for partition in spec["partitions"]:
        start, end = timestamp(partition["start"]), timestamp(partition["end"])
        for scenario in scenarios:
            members = results[(partition["name"], scenario)]
            portfolio = aggregate(members, start, end)
            trades = portfolio.pop("trades")
            for trade in trades:
                ledger.append({"partition": partition["name"], "scenario": scenario, **trade})
            hourly_curve = portfolio.pop("curve")
            groups.append({"partition": partition["name"], "scenario": scenario, "start": start, "end_exclusive": end, **portfolio,
                           "daily_curve": [point for point in hourly_curve if point["time"] % 86_400_000 == 0],
                           "symbols": [{"symbol": member["symbol"], **aggregate([member], start, end)["metrics"]} for member in members],
                           "decision_hashes": {member["symbol"]: canonical_hash(member["decisions"]) for member in members}})
    if code_hash() != implementation_hash:
        raise ValueError("Research source changed during replay; rerun with the final implementation")
    report = {"schema": 1, "id": identity, "strategy": strategy["id"], "strategy_hash": canonical_hash(strategy), "research": spec,
              "dataset_hash": manifest["dataset_hash"], "code_hash": implementation_hash, "dataset_retrieved_at": manifest["retrieved_at"],
              "provenance": {"venue": manifest["venue"], "source_policy": manifest.get("source_policy"), "source_audit": manifest.get("minute_source_audit"),
                             "archives": len(manifest["archives"]), "rows": sum(a["rows"] for a in manifest["archives"]),
                             "funding_events": {symbol: manifest["funding"][symbol]["events"] for symbol in spec["symbols"]},
                             "history_origins": {symbol: {timeframe: value["history_origin"] for timeframe, value in evidence.items()} for symbol, evidence in checkpoint_evidence.items()},
                             "filters": manifest["metadata"]},
              "groups": groups, "assessment": "Research only. No parameters selected from results; historical holdout is procedural, not a forward unseen market sample.",
              "limitations": ["1m OHLC cannot identify intrabar order; stop-first ties and approximate exit times are disclosed.",
                              "Spread, slippage and publication latency are modeled; historical order-book liquidity/fills are unavailable.",
                              *manifest["limitations"], spec["historical_filters"], "Fractional research quantities; historical quantity/notional filters and liquidation are not simulated.",
                              "Funding within a minute precedes its unknown intrabar exit; exact settlement/exit ordering may differ.",
                              "Partition boundaries force flat positions; results are separate experiments, not one continuously compounded account.",
                              "Equity/drawdown use hourly contract-price marks after paid costs, without hypothetical liquidation fees on open positions.",
                              "MAE/MFE omit exit-minute unknown extremes; observations are censored, not exact tick excursions.",
                              "No parameter/strategy search, walk-forward refitting, regime classification or SMA benchmark has been performed.",
                              "Two chosen survivors do not represent Binance's historical universe; no survivorship-free universe claim.",
                              "Bootstrap intervals have only 6 or 12 calendar months per partition and are exploratory.",
                              "No forward paper performance or production reliability claim."]}
    report_root.mkdir(exist_ok=True, parents=True)
    target = report_root / identity
    evidence_bytes = "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in ledger).encode()
    fields = [key for key in ledger[0] if key not in ("evidence", "plan")] if ledger else ["partition", "scenario", "symbol", "signal_id"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(ledger)
    files = {"trades.jsonl": evidence_bytes, "trades.csv": stream.getvalue().encode(),
             "dataset-manifest.json": json.dumps(manifest, indent=2).encode(),
             "source-audit.json": verified_path(data_root, manifest["canonical_overrides"]).read_bytes()}
    report["files"] = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    report["report_hash"] = canonical_hash(report)
    files["report.json"] = json.dumps(report, indent=2).encode()
    if target.exists():
        if any(not (target / name).exists() or (target / name).read_bytes() != content for name, content in files.items()):
            raise ValueError("Repeated run with identical identity produced different artifacts")
        print("Repeated replay reproduced every report/export byte exactly", flush=True)
    else:
        staging = report_root / f".staging-{uuid4()}"
        staging.mkdir()
        for name, content in files.items():
            (staging / name).write_bytes(content)
        os.rename(staging, target)
    temporary = report_root / "latest.tmp"
    temporary.write_text(json.dumps({"id": identity, "report_hash": report["report_hash"]}), encoding="utf-8")
    os.replace(temporary, report_root / "latest.json")
    print(f"Report {identity}: {len(ledger)} trades across {len(groups)} preregistered experiments", flush=True)
    return report


if __name__ == "__main__":
    run()
