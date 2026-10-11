"""Offline May probability diagnostics; never selects a new live strategy.

Model is fit on early April, intercept adjusted on late April. May labels
are consulted only after predictions and April-fixed thresholds are computed.
Accuracy excludes no observed neutral; publication-day grouped uncertainty
is exploratory and does not license strategy changes.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal as D
from math import log
from random import Random
from statistics import fmean

from .v6hbr_chronological_probability import (
    GOOD, BAD, NEUTRAL, _dot, _sigmoid, split_matured,
    train_logistic, calibrate_intercept,
)

PROBABILITY_BINS = ((0.0, 0.2), (0.2, 0.3), (0.3, 0.4),
                    (0.4, 0.5), (0.5, 0.6), (0.6, 0.8), (0.8, 1.0))
CALIBRATION_TOP_FRACTIONS = (0.20, 0.40, 0.60)
RESAMPLES = 1024
SEED = 20261011


def _logloss(p, y):
    p = max(1e-12, min(1 - 1e-12, p))
    return -(y * log(p) + (1 - y) * log(1 - p))


def _metrics(rows, cutoff_base=None):
    n = len(rows)
    right = sum(r["y"] for r in rows)
    wrong = sum(r["directional_outcome"] == BAD for r in rows)
    neutral = sum(r["directional_outcome"] == NEUTRAL for r in rows)
    if n != right + wrong + neutral:
        raise ValueError("Unreconciled 60-minute outcomes")
    return {
        "n": n,
        "correct": right,
        "wrong": wrong,
        "neutral": neutral,
        "correct_fraction_including_neutral": str(D(right) / n) if n else None,
        "mean_predicted_correct_probability": str(fmean(r["p"] for r in rows)) if n else None,
        "brier": str(fmean((r["p"]-r["y"])**2 for r in rows)) if n else None,
        "days_utc": len({r["utc_day"] for r in rows}),
        "distinct_publication_boundaries": len({r["at_ms"] for r in rows}),
        "symbols": len({r["symbol"] for r in rows}),
        "coverage_fraction_may_candidates": (
            str(D(n) / cutoff_base) if cutoff_base else None
        ),
    }


def _auroc(rows):
    """Pairwise AUC with ties half-credit; measures ranking, NOT calibration."""
    good = sorted(r["p"] for r in rows if r["y"] == 1)
    other = sorted(r["p"] for r in rows if r["y"] == 0)
    if not good or not other:
        return None
    # Small isolated research sets, bounded pairwise calculation.
    if len(good)*len(other) > 2_000_000:
        raise ValueError("AUC study requires bounded research size")
    wins = sum(1 if p > q else 0.5 if p == q else 0
               for p in good for q in other)
    return str(wins/(len(good)*len(other)))


def _fixed_april_quantile(cal_probs, top_fraction):
    if not cal_probs:
        raise ValueError("No April calibration probabilities")
    if not 0 < top_fraction < 1:
        raise ValueError("Invalid fixed calibration coverage")
    ordered = sorted(cal_probs, reverse=True)
    # At least 1 calibration example; no percentage derived from May.
    index = max(0, (int(len(ordered)*top_fraction + 0.999999999999) - 1))
    return ordered[index]


def _baseline_rate(cal):
    """Cal-only Laplace-smoothed constant, decision-available by May 1."""
    multiplicities = Counter(r["at_ms"] for r in cal)
    effective_n = len(multiplicities)
    effective_wins = sum(r["y"]/multiplicities[r["at_ms"]] for r in cal)
    return (effective_wins+1)/(effective_n+2)


def _loss_summary(rows, rate):
    return {
        "constant_probability": str(rate),
        "brier": str(fmean((rate-r["y"])**2 for r in rows)),
        "log_loss": str(fmean(_logloss(rate,r["y"]) for r in rows)),
    }


def _day_block_brier_delta(rows, calibrated_constant):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["utc_day"]].append(
            (row["p"]-row["y"])**2 - (calibrated_constant-row["y"])**2
        )
    days = [grouped[d] for d in sorted(grouped)]
    if len(days) < 10:
        return {"distinct_utc_days":len(days),"status":"INSUFFICIENT_DAYS"}
    rng = Random(SEED)
    m = len(days)
    estimates = []
    for _ in range(RESAMPLES):
        resampled = [days[rng.randrange(m)] for _ in range(m)]
        values = [v for day in resampled for v in day]
        estimates.append(fmean(values))
    estimates.sort()
    return {
        "distinct_utc_days": m,
        "bootstrap_repetitions": RESAMPLES,
        "mean_model_minus_late_april_constant_brier": str(
            fmean(v for day in days for v in day)
        ),
        "approx_p2p5": str(estimates[int(.025*RESAMPLES)]),
        "approx_p97p5": str(estimates[int(.975*RESAMPLES)]),
        "note": "UTC-day resampling is exploratory; interday/crosscoin dependence and reused development labels remain"
    }


def diagnostic_study(labeled):
    splits = split_matured(labeled)
    train, cal, may = (splits[x] for x in (
        "training", "calibration", "may_development_evaluation"))
    coef = train_logistic(train)
    shift = calibrate_intercept(coef, cal)
    score = lambda r: _sigmoid(_dot(coef,r["f"])+shift)
    apr_cal_p = [score(r) for r in cal]
    may_scored = [{**r, "p":score(r)} for r in may]
    may_probs = sorted(x["p"] for x in may_scored)
    apr_only_base = sum(x["y"] for x in train)/len(train)
    late_april_rate = _baseline_rate(cal)
    thresholds = {}
    for fraction in CALIBRATION_TOP_FRACTIONS:
        cutoff = _fixed_april_quantile(apr_cal_p,fraction)
        retained = [r for r in may_scored if r["p"]>=cutoff]
        rejected = [r for r in may_scored if r["p"]<cutoff]
        thresholds[str(fraction)] = {
            "minimum_probability_selected_using_april_only":str(cutoff),
            "retained_may":_metrics(retained,len(may)),
            "rejected_may":_metrics(rejected,len(may)),
            "not_independently_validated":True,
        }
    bins = {}
    for lo, hi in PROBABILITY_BINS:
        part = [r for r in may_scored
                if (lo <= r["p"] < hi) or (hi == 1.0 and r["p"] == 1.0)]
        bins[f"{lo:.2f}..{hi:.2f}"] = _metrics(part,len(may))
    rank = {
        "may_AUROC_predicting_correct_including_neutral_as_negative":_auroc(may_scored),
        "may_all_candidate":_metrics(may_scored,len(may)),
        "minimum_probability":str(may_probs[0]),
        "maximum_probability":str(may_probs[-1]),
        "median_probability":str(may_probs[len(may_probs)//2]),
        "may_probabilities_ge_60pct":sum(p>=.6 for p in may_probs),
    }
    return {
        "status":"EXPLORATORY_APRIL_FIXED_MAY_RANKING_AND_RELIABILITY_ONLY",
        "split":"APRIL_EARLY_TRAIN_LATE_CAL_MAY_DEVELOPMENT_EVAL",
        "training_n":len(train),"calibration_n":len(cal),"may_n":len(may),
        "rank_and_prediction_spread":rank,
        "fixed_probability_bins_may":bins,
        "fixed_april_calibration_coverage_thresholds_on_may":thresholds,
        "brier_and_log_loss_comparators":{
            "model":{
                "brier":str(fmean((r["p"]-r["y"])**2 for r in may_scored)),
                "log_loss":str(fmean(_logloss(r["p"],r["y"]) for r in may_scored))
            },
            "early_april_constant":_loss_summary(may,apr_only_base),
            "late_april_smoothed_constant":_loss_summary(may,late_april_rate),
        },
        "day_grouped_model_minus_late_april_constant_brier":_day_block_brier_delta(
            may_scored,late_april_rate
        ),
        "coefficient_vector":[str(x) for x in coef],
        "late_april_intercept_shift":str(shift),
        "promotion_decision":"NO_GO_MAY_ALREADY_INSPECTED_AND_SIX_MARKETS_ONLY",
        "limitations":[
            "April quantile cutoffs chosen without May prices or May outcome labels",
            "Fixed bins and cutoffs are diagnostics, never new production entry rules",
            "May was previously inspected; May cannot validate candidate selection or calibration",
            "Model may show Brier improvement simply by predicting the updated base rate",
            "AUROC tests ranking, not realized trade profitability or calibrated risk",
            "Coincident BTC/ETH/SOL/XRP/DOGE/BNB observations are not independent",
            "Positive trades need execution, funding and liquidity evidence on intended exchange",
        ],
    }
