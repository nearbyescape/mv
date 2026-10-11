"""Causal chronological evaluation must not train on May or falsify coverage."""
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite

import pytest

from app.research.v6hbr_chronological_probability import (
    BAD, GOOD, NEUTRAL, CAL_END, TRAIN_END,
    _features, _sigmoid, run_chronological_pilot, split_matured
)
from app.research import v6hbr_chronological_pilot as cli


def ms(month, day, hour=12, minute=0):
    return int(datetime(2026, month, day, hour, minute,
                        tzinfo=timezone.utc).timestamp() * 1000)


def row(symbol, moment, label, *, direction="long", lane="v4_base",
        setup=None, regime="established"):
    if setup is None:
        setup = "momentum_breakout_15m" if lane == "15m_rescue" \
                else "pullback_continuation"
    return {
        "symbol": symbol, "at_ms": moment,
        "utc_day": datetime.fromtimestamp(
            moment/1000,timezone.utc
        ).date().isoformat(),
        "lane": lane, "direction": direction, "setup_type": setup,
        "regime": regime,
        "predecision_source_extension_atr": "0.45",
        "predecision_ema20_ema50_separation_atr": "0.7",
        "horizons": {"60": {
            "status": "OBSERVED", "direction_classification": label,
        }},
    }


def synthetic():
    result = []
    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    for month, days in ((4, range(1, 30)), (5, range(1, 31))):
        for day in days:
            for idx, symbol in enumerate(symbols):
                label = GOOD if (day + idx) % 5 < 2 else (
                    NEUTRAL if (day + idx) % 5 == 2 else BAD
                )
                result.append(row(
                    symbol, ms(month, day),
                    label, direction="long" if idx % 2 == 0 else "short",
                    lane="15m_rescue" if idx == 1 else "v4_base",
                ))
    return result


def test_chronological_partitions_have_no_horizon_maturity_overlap():
    rows = synthetic()
    rows.append(row("DOGEUSDT", ms(4, 19, 23, 30), GOOD))
    rows.append(row("DOGEUSDT", ms(4, 30, 23, 30), GOOD))
    splits = split_matured(rows)
    assert all(r["at_ms"]+3_600_000 <= TRAIN_END for r in splits["training"])
    assert all(r["at_ms"] >= TRAIN_END and r["at_ms"]+3_600_000 <= CAL_END
               for r in splits["calibration"])
    assert all(r["at_ms"] >= CAL_END
               for r in splits["may_development_evaluation"])
    assert all(r["at_ms"] != ms(4, 19, 23, 30) for r in splits["training"])
    assert all(r["at_ms"] != ms(4, 30, 23, 30) for r in splits["calibration"])


def test_training_and_intercept_are_invariant_to_may_future_outcomes():
    raw = synthetic()
    before = deepcopy(raw)
    first = run_chronological_pilot(raw)
    altered = deepcopy(raw)
    for r in altered:
        if r["at_ms"] >= CAL_END:
            r["horizons"]["60"]["direction_classification"] = GOOD
    changed = run_chronological_pilot(altered)
    assert raw == before
    assert first["coefficient_vector"] == changed["coefficient_vector"]
    assert first["late_april_intercept_shift"] == changed["late_april_intercept_shift"]
    assert first["training_correct_prevalence"] == changed["training_correct_prevalence"]
    assert first["may_correct_fraction_all_original_candidates"] != (
        changed["may_correct_fraction_all_original_candidates"]
    )
    assert first["promotion_decision"].startswith("NO_GO")


def test_probability_thresholds_account_for_all_rejected_correct_references():
    r = run_chronological_pilot(synthetic())
    n = r["evaluation_references"]
    assert n >= 20
    assert r["training_references"] >= 35
    assert r["calibration_references"] >= 15
    assert all(isfinite(float(x)) for x in r["coefficient_vector"])
    assert 0 < float(r["may_model_brier"]) < 1
    assert 0 < float(r["may_training_prevalence_baseline_brier"]) < 1
    for cutoff in ("0.6", "0.7", "0.8"):
        decision = r["thresholds_FIXED_NOT_TUNED_ON_MAY"][cutoff]
        keep = decision["retained"]
        reject = decision["rejected_counterfactual"]
        assert keep["n"] + reject["n"] == n
        assert keep["correct"] + reject["correct"] == sum(
            1 for x in synthetic()
            if x["at_ms"] >= CAL_END and
            x["horizons"]["60"]["direction_classification"] == GOOD
        )
        assert keep["correct"]+keep["wrong"]+keep["neutral"] == keep["n"]
        assert reject["correct"]+reject["wrong"]+reject["neutral"] == reject["n"]


def test_decision_features_read_no_forward_horizons():
    r = synthetic()[0]
    f = _features(r)
    poisoned = deepcopy(r)
    poisoned["horizons"]["60"]["direction_classification"] = BAD
    poisoned["horizons"]["60"]["future_attractor_price"] = "999999"
    assert _features(poisoned) == f
    assert _sigmoid(1000) <= 1
    assert _sigmoid(-1000) >= 0


def test_source_feature_and_duplicate_identity_fail_closed():
    rows = synthetic()
    with pytest.raises(ValueError, match="Duplicate"):
        run_chronological_pilot(rows + [deepcopy(rows[0])])
    rows[0]["predecision_ema20_ema50_separation_atr"] = "NaN"
    with pytest.raises(ValueError, match="indicator"):
        run_chronological_pilot(rows)


def test_thin_dataset_does_not_make_high_confidence_claim():
    rows = synthetic()[:20]
    with pytest.raises(ValueError, match="Insufficient chronological"):
        run_chronological_pilot(rows)


def test_networkless_standalone_runner_marks_subset_and_keeps_provenance(monkeypatch):
    from app.research import v6hbr_chronological_pilot as runner
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"] + [
        f"TEST{i:02d}USDT" for i in range(27)
    ]
    monkeypatch.setattr(runner, "load_spec",lambda: ({"symbols": symbols}, "f"*64))
    mock = synthetic()
    def audit(root, spec, digest, symbol):
        return {"symbol": symbol, "candidate_count": len(
            [r for r in mock if r["symbol"] == symbol]
        ), "labeled": [r for r in mock if r["symbol"] == symbol]}
    monkeypatch.setattr(runner, "audit_symbol", audit)
    data = cli.study("/research",tuple(symbols[:3]))
    assert data["run_scope"] == "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE"
    assert data["requested_symbols"] == symbols[:3]
    assert data["complete_symbol_count"] == 3
    assert data["pilot"]["promotion_decision"].startswith("NO_GO")
