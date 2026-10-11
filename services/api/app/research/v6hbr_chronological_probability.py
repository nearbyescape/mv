"""Fixed chronological probability-of-correctness research baseline for V6HBR.

Only frozen, prepublication source indicators may affect the probability:
direction, original V4/V5 lane, breakout/pullback identifier, 1h/4h trend
regime, published 1h EMA20 distance/ATR, published EMA20–EMA50 separation.
No forward prices, target, settled trades or mark features enter the model.

Trains on early April 2026, calibrates intercept on late April 2026, and
reports May 2026 merely as *later development*, NOT independent validation.
One timestamp counts as one weighted market episode in fitting/calibration.
No threshold is chosen using May outcomes. This module never publishes trades.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from math import exp, isfinite, log
from statistics import fmean

from .dataset import timestamp
from .v6hbr_setup_taxonomy import BREAKOUT_SETUP_TYPES, validated_setup_type

TRAIN_END = timestamp("2026-04-20")
CAL_END = timestamp("2026-05-01")
EVAL_END = timestamp("2026-06-01")
HORIZON_MS = 3_600_000
MIN_TRAIN = 35
MIN_CAL = 15
MIN_EVAL = 20
MIN_TRAIN_DAYS = 10
MIN_CAL_DAYS = 5
RIDGE = 0.20
STEPS = 500
STEP_SIZE = 0.40
CAL_RIDGE = 3.0
PROBABILITY_CUTOFFS = (0.60, 0.70, 0.80)

GOOD = "DIRECTION_SUPPORTED_OVER_HURDLE"
BAD = "DIRECTION_OPPOSITE_OVER_HURDLE"
NEUTRAL = "NEUTRAL_WITHIN_HURDLE"


def _sigmoid(z: float) -> float:
    if not isfinite(z):
        raise ValueError("Nonfinite model logit")
    if z >= 0:
        return 1.0 / (1.0 + exp(-z))
    e = exp(z)
    return e / (1.0 + e)


def _features(r: dict) -> tuple[float, ...]:
    """Strict candidate-time whitelist; cannot read row['horizons']."""
    validated_setup_type(r["setup_type"], r["lane"])
    if r["direction"] not in ("long", "short"):
        raise ValueError("Invalid candidate direction")
    if r["regime"] not in ("established", "emerging"):
        raise ValueError("Invalid published trend regime")
    ext = float(Decimal(r["predecision_source_extension_atr"]))
    separation = float(Decimal(r["predecision_ema20_ema50_separation_atr"]))
    if not isfinite(ext) or not isfinite(separation):
        raise ValueError("Invalid as-of indicator")
    ext = max(-2.0, min(2.0, ext))
    separation = max(-2.0, min(2.0, separation))
    return (
        1.0,
        float(r["direction"] == "long"),
        float(r["lane"] == "15m_rescue"),
        float(r["setup_type"] in BREAKOUT_SETUP_TYPES),
        float(r["regime"] == "established"),
        ext,
        separation,
    )


def _observed_label(r: dict) -> int:
    h = r["horizons"]["60"]
    if h["status"] != "OBSERVED":
        raise ValueError("Censored or invalid forward outcome cannot be trained")
    if h["direction_classification"] not in (GOOD, BAD, NEUTRAL):
        raise ValueError("Unexpected 60m directional label")
    return int(h["direction_classification"] == GOOD)


def _prepare(rows: list[dict]) -> list[dict]:
    prepared = []
    ids = set()
    for r in rows:
        ms = r["at_ms"]
        if type(ms) is not int or not timestamp("2026-04-01") <= ms < EVAL_END:
            raise ValueError("Candidate outside frozen April–May period")
        if ms % 900_000:
            raise ValueError("Candidate publication not 15m aligned")
        identity = (r["symbol"], ms, r["lane"], r["setup_type"], r["direction"])
        if identity in ids:
            raise ValueError("Duplicate candidate identity")
        ids.add(identity)
        date = datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat()
        if date != r["utc_day"]:
            raise ValueError("Published UTC day mismatch")
        feature_vector = _features(r)
        label = _observed_label(r)
        if ms + HORIZON_MS > EVAL_END:
            raise ValueError("Unmatured May 60m observation")
        prepared.append({
            "symbol": r["symbol"], "at_ms": ms,
            "utc_day": date, "f": feature_vector, "y": label,
            "directional_outcome": r["horizons"]["60"]["direction_classification"],
        })
    return sorted(prepared, key=lambda x: (x["at_ms"], x["symbol"]))


def split_matured(rows: list[dict]) -> dict[str, list[dict]]:
    """Never let a training/calibration target extend beyond its split end."""
    prepared = _prepare(rows)
    partitions = {
        "training": [
            r for r in prepared if r["at_ms"] + HORIZON_MS <= TRAIN_END
        ],
        "calibration": [
            r for r in prepared
            if TRAIN_END <= r["at_ms"]
            and r["at_ms"] + HORIZON_MS <= CAL_END
        ],
        "may_development_evaluation": [
            r for r in prepared if CAL_END <= r["at_ms"]
        ],
    }
    if (len(partitions["training"]) < MIN_TRAIN
            or len(partitions["calibration"]) < MIN_CAL
            or len(partitions["may_development_evaluation"]) < MIN_EVAL):
        raise ValueError("Insufficient chronological training/calibration/evaluation references")
    if len({r["utc_day"] for r in partitions["training"]}) < MIN_TRAIN_DAYS:
        raise ValueError("Insufficient training UTC trading days")
    if len({r["utc_day"] for r in partitions["calibration"]}) < MIN_CAL_DAYS:
        raise ValueError("Insufficient calibration UTC trading days")
    return partitions


def _weighted_rows(rows: list[dict]) -> tuple[list[tuple[dict, float]], int]:
    multiplicities = Counter(r["at_ms"] for r in rows)
    return ([(r, 1.0 / multiplicities[r["at_ms"]]) for r in rows],
            len(multiplicities))


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def train_logistic(training: list[dict]) -> tuple[float, ...]:
    """Fixed, deterministic L2-regularized batch logistic regression."""
    weighted, n = _weighted_rows(training)
    if n == 0:
        raise ValueError("No independent publication timestamps")
    dim = len(training[0]["f"])
    if any(len(r["f"]) != dim for r in training):
        raise ValueError("Inconsistent frozen features")
    coefficients = [0.0] * dim
    for _ in range(STEPS):
        gradient = [0.0] * dim
        for row, weight in weighted:
            err = (_sigmoid(_dot(coefficients, row["f"])) - row["y"]) * weight / n
            for j, v in enumerate(row["f"]):
                gradient[j] += err * v
        for j in range(1, dim):
            gradient[j] += RIDGE * coefficients[j]
        for j in range(dim):
            coefficients[j] -= STEP_SIZE * gradient[j]
    if not all(isfinite(c) for c in coefficients):
        raise ValueError("Nonfinite model")
    return tuple(coefficients)


def calibrate_intercept(coef: tuple[float, ...], calibration: list[dict]) -> float:
    """Fixed intercept-in-the-large adjustment; not full probability calibration.

    Penalized fit only to late-April labels; May never enters this computation.
    """
    weighted, n = _weighted_rows(calibration)
    if n == 0:
        raise ValueError("No calibration publication timestamps")
    low, high = -5.0, 5.0
    for _ in range(70):
        shift = (low + high) / 2.0
        slope = sum(
            weight * (_sigmoid(_dot(coef, r["f"]) + shift) - r["y"])
            for r, weight in weighted
        ) / n + CAL_RIDGE * shift / n
        if slope > 0:
            high = shift
        else:
            low = shift
    return (low + high) / 2.0


def _summarize(scored: list[dict], total: int) -> dict:
    n = len(scored)
    wins = sum(r["y"] == 1 for r in scored)
    losses = n - wins
    opposite = sum(r["directional_outcome"] == BAD for r in scored)
    neutral = sum(r["directional_outcome"] == NEUTRAL for r in scored)
    return {
        "n": n,
        "correct": wins,
        "wrong": opposite,
        "neutral": neutral,
        "correct_fraction_all_observed": str(Decimal(wins) / n) if n else None,
        "retained_coverage": str(Decimal(n) / total) if total else None,
        "distinct_utc_days": len({r["utc_day"] for r in scored}),
        "distinct_publication_boundaries": len({r["at_ms"] for r in scored}),
        "distinct_markets": len({r["symbol"] for r in scored}),
    }


def run_chronological_pilot(labeled: list[dict]) -> dict:
    splits = split_matured(labeled)
    train = splits["training"]
    cal = splits["calibration"]
    evaluation = splits["may_development_evaluation"]
    coef = train_logistic(train)
    shift = calibrate_intercept(coef, cal)
    raw = [(r, _sigmoid(_dot(coef, r["f"]) + shift)) for r in evaluation]
    scored = [{**r, "p": p} for r, p in raw]
    base = sum(r["y"] for r in train) / len(train)
    bs_model = fmean((p - r["y"]) ** 2 for r, p in raw)
    bs_baseline = fmean((base - r["y"]) ** 2 for r in evaluation)
    def cross_entropy(p, y):
        p = min(1 - 1e-12, max(1e-12, p))
        return -(y * log(p) + (1-y)*log(1-p))
    log_model = fmean(cross_entropy(p, r["y"]) for r, p in raw)
    log_baseline = fmean(cross_entropy(base, r["y"]) for r in evaluation)
    thresholds = {}
    for threshold in PROBABILITY_CUTOFFS:
        accepted = [r for r in scored if r["p"] >= threshold]
        rejected = [r for r in scored if r["p"] < threshold]
        thresholds[str(threshold)] = {
            "retained": _summarize(accepted, len(evaluation)),
            "rejected_counterfactual": _summarize(rejected, len(evaluation)),
            "not_model_selection": True,
        }
    by_market = {
        symbol: _summarize(
            [r for r in scored if r["symbol"] == symbol], len(evaluation)
        ) for symbol in sorted({r["symbol"] for r in scored})
    }
    return {
        "status": "CHRONOLOGICAL_APRIL_TRAIN_CAL_MAY_DEVELOPMENT_EVAL_NOT_INDEPENDENT_VALIDATION",
        "training_references": len(train),
        "calibration_references": len(cal),
        "evaluation_references": len(evaluation),
        "matured_training_cutoff_utc": "2026-04-20T00:00:00Z",
        "matured_calibration_cutoff_utc": "2026-05-01T00:00:00Z",
        "may_development_evaluation_window": "2026-05-01..2026-05-31",
        "model": "FIXED_L2_LOGISTIC_CAUSAL_FEATURES_INTERCEPT_CALIBRATION",
        "features": [
            "bias", "is_long", "is_15m_rescue", "is_breakout",
            "established_trend", "1h_context_ema20_distance_atr_clipped",
            "1h_context_ema20_ema50_separation_atr_clipped",
        ],
        "fixed_ridge": RIDGE,
        "calibration": "INTERCEPT_ADJUSTMENT_ONLY_LATE_APRIL",
        "training_correct_prevalence": str(base),
        "may_correct_fraction_all_original_candidates": str(
            Decimal(sum(r["y"] for r in evaluation)) / len(evaluation)
        ),
        "may_model_brier": str(bs_model),
        "may_training_prevalence_baseline_brier": str(bs_baseline),
        "may_model_log_loss": str(log_model),
        "may_training_prevalence_baseline_log_loss": str(log_baseline),
        "thresholds_FIXED_NOT_TUNED_ON_MAY": thresholds,
        "by_market_may_60m": by_market,
        "coefficient_vector": [str(c) for c in coef],
        "late_april_intercept_shift": str(shift),
        "promotion_decision": "NO_GO_INSPECTED_DEVELOPMENT_DATA_ONLY",
        "limitations": [
            "May is chronologically later but was already inspected; NOT independent validation",
            "Only source EMA/ATR and frozen categorical indicators used at decision publication",
            "Fitted with timestamp-weighted samples; shared market moves still cause dependence",
            "Calibration is a penalized global intercept correction, NOT established reliability",
            "Coverage and rejected winning forecasts shown for every frozen probability threshold",
            "Thresholds are descriptive and cannot be chosen by maximizing May outcome accuracy",
            "No direction is flipped, no new entry is generated, no live trade signal is changed",
            "Uncorrelated external 10-market+ validation and realistic fill/cost replay are missing",
        ],
    }
