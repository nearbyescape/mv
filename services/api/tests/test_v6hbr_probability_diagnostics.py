"""Rank diagnostics must not conceal zero coverage or use May labels to set cutoffs."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.research import v6hbr_probability_diagnostics_cli as runner
from app.research.v6hbr_chronological_probability import GOOD, BAD, NEUTRAL
from app.research.v6hbr_probability_diagnostics import (
    _auroc, _baseline_rate, _fixed_april_quantile, diagnostic_study
)


def moment(month, day, hour=12):
    return int(datetime(2026,month,day,hour,tzinfo=timezone.utc).timestamp()*1000)


def fixture():
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    rows=[]
    for month,days in ((4,range(1,30)),(5,range(1,31))):
        for day in days:
            for j,symbol in enumerate(symbols):
                t=moment(month,day)
                outcome = (GOOD, BAD, NEUTRAL)[(day+j)%3]
                rows.append({
                    "symbol":symbol,"at_ms":t,
                    "utc_day":datetime.fromtimestamp(
                        t/1000,timezone.utc
                    ).date().isoformat(),
                    "lane":"v4_base",
                    "direction":"long" if j % 2 else "short",
                    "setup_type":"pullback_continuation",
                    "regime":"established" if day%2 else "emerging",
                    "predecision_source_extension_atr":str((day%5)/5),
                    "predecision_ema20_ema50_separation_atr":str((j+1)/5),
                    "horizons":{"60":{
                        "status":"OBSERVED",
                        "direction_classification":outcome
                    }},
                })
    return rows


def test_fixed_april_thresholds_cannot_look_at_may_labels():
    inputs=fixture()
    before=deepcopy(inputs)
    a=diagnostic_study(inputs)
    altered=deepcopy(inputs)
    for r in altered:
        if r["at_ms"]>=moment(5,1):
            r["horizons"]["60"]["direction_classification"]=GOOD
    b=diagnostic_study(altered)
    assert inputs==before
    assert a["coefficient_vector"]==b["coefficient_vector"]
    assert a["late_april_intercept_shift"]==b["late_april_intercept_shift"]
    assert a["training_n"]==b["training_n"]
    assert a["calibration_n"]==b["calibration_n"]
    for key in ("0.2","0.4","0.6"):
        lhs=a["fixed_april_calibration_coverage_thresholds_on_may"][key]
        rhs=b["fixed_april_calibration_coverage_thresholds_on_may"][key]
        assert lhs["minimum_probability_selected_using_april_only"] == rhs[
            "minimum_probability_selected_using_april_only"]
        assert lhs["retained_may"]["n"]==rhs["retained_may"]["n"]
        assert lhs["rejected_may"]["n"]==rhs["rejected_may"]["n"]
    assert a["brier_and_log_loss_comparators"]["model"] != (
        b["brier_and_log_loss_comparators"]["model"])
    assert a["promotion_decision"].startswith("NO_GO")


def test_bin_and_april_cutoffs_account_for_every_may_outcome():
    report=diagnostic_study(fixture())
    may=report["may_n"]
    assert may >= 20
    bins=report["fixed_probability_bins_may"]
    assert sum(x["n"] for x in bins.values())==may
    assert sum(x["correct"]+x["wrong"]+x["neutral"]
               for x in bins.values())==may
    for x in report["fixed_april_calibration_coverage_thresholds_on_may"].values():
        kept=x["retained_may"]
        rejected=x["rejected_may"]
        assert kept["n"]+rejected["n"]==may
        assert (kept["correct"]+rejected["correct"]
                ==sum(z["correct"] for z in bins.values()))
        assert (kept["wrong"]+rejected["wrong"]
                ==sum(z["wrong"] for z in bins.values()))
        assert (kept["neutral"]+rejected["neutral"]
                ==sum(z["neutral"] for z in bins.values()))


def test_auc_corrects_for_tied_predictions():
    rows=[
        {"p":0.8,"y":1},{"p":0.7,"y":1},
        {"p":0.7,"y":0},{"p":0.2,"y":0},
    ]
    assert _auroc(rows)==str(0.875)
    assert _auroc([{"p":.1,"y":1},{"p":.9,"y":0}])==str(0.0)
    assert _auroc([{"p":.9,"y":1},{"p":.1,"y":0}])==str(1.0)
    assert _auroc([{"p":.7,"y":1}]) is None


def test_april_cutoff_uses_pinned_fraction():
    probs=[.1,.2,.3,.4,.5]
    assert _fixed_april_quantile(probs,0.2)==.5
    assert _fixed_april_quantile(probs,0.4)==.4
    assert _fixed_april_quantile(probs,0.6)==.3
    with pytest.raises(ValueError,match="No April"):
        _fixed_april_quantile([],0.2)


def test_smoothed_base_rate_groups_same_timestamp_as_one_market_episode():
    rows=[
        {"at_ms":100,"y":1},{"at_ms":100,"y":1},
        {"at_ms":200,"y":0}
    ]
    # event-weighted positives 1 out of 2 distinct publication boundaries,
    # plus Laplace one-success one-failure smoothing.
    assert _baseline_rate(rows)==.5


def test_cli_never_mislabels_six_market_subset_as_full_universe(monkeypatch):
    symbols=["BTCUSDT","ETHUSDT","SOLUSDT"] + [
        f"TEST{i:02d}USDT" for i in range(27)
    ]
    data=fixture()
    monkeypatch.setattr(runner,"load_spec",
                        lambda:({"symbols":symbols},"f"*64))
    def fake_audit(root,spec,sha,symbol):
        examples=[r for r in data if r["symbol"]==symbol]
        return {
            "symbol":symbol,
            "labeled":examples,
            "candidate_count":len(examples),
            "source_series_sha256":{"15m":"frozen"}
        }
    monkeypatch.setattr(runner,"audit_symbol",fake_audit)
    summary=runner.study("/research",tuple(symbols[:3]))
    assert summary["run_scope"]=="EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE"
    assert summary["complete_symbol_count"]==3
    assert summary["production_mutation"] is False
    assert summary["diagnostics"]["promotion_decision"].startswith("NO_GO")
