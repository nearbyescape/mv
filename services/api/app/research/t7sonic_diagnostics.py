"""Descriptive T7Sonic outcome attribution, never an expert trading selector.

A read-only POST-LABEL diagnostic: groups already labeled episodes by
expert-at-onset, direction and simultaneous expert consensus. Does not
modify candidate decisions, thresholds, training models, or predict future.
This report may be examined in April/May development ONLY; no holdout use.
Overlapping episode groups are descriptive and never independent samples.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D
from hashlib import sha256
import json

from .t7sonic_outcomes import HORIZONS

FAVORABLE="FAVORABLE_ABOVE_10BPS"
ADVERSE="ADVERSE_BELOW_MINUS_10BPS"
NEUTRAL="NEUTRAL_WITHIN_10BPS"
ALLOWED=frozenset((FAVORABLE,ADVERSE,NEUTRAL))
HALF_DAY_MINUTES=12*60


def _str_decimal_avg(values: list[D]) -> str | None:
    if not values:
        return None
    return format((sum(values,D(0))/len(values)).normalize(),"f")


def _describe_episode_cohort(records: list[dict], horizon: int) -> dict:
    """One cohort, no inference that observations are IID trades."""
    states=Counter()
    signed=[]
    mae=[]
    mfe=[]
    for label in records:
        observed=label["horizons_minutes"][str(horizon)]
        state=observed["classification"]
        if state not in ALLOWED:
            raise ValueError("Unknown horizon label")
        states[state]+=1
        signed.append(D(observed["signed_mark_move_bps"]))
        mae.append(D(observed["adverse_excursion_bps"]))
        mfe.append(D(observed["favorable_excursion_bps"]))
    if states.total()!=len(records):
        raise ValueError("Missing labels in cohort")
    return {
        "episode_count":len(records),
        "favorable":states[FAVORABLE],
        "adverse":states[ADVERSE],
        "neutral":states[NEUTRAL],
        "mean_signed_mark_bps":_str_decimal_avg(signed),
        "mean_max_adverse_excursion_bps":_str_decimal_avg(mae),
        "mean_max_favorable_excursion_bps":_str_decimal_avg(mfe),
        "independence_warning":"OVERLAPPING_PRICE_HORIZONS_WITHIN_SAME_DAY",
    }


def summarize_attribution(report: dict) -> dict:
    """Input must be an intact offline outcome report with episode records."""
    if not isinstance(report,dict) or report.get("engine")!="T7Sonic":
        raise ValueError("Not a T7Sonic research outcome report")
    if report.get("status")!="RETROSPECTIVE_DEVELOPMENT_DIRECTIONAL_MARK_PROXY_NOT_TRADES":
        raise ValueError("Not a research-only retrospective report")
    if report.get("scope")!="INSPECTED_APRIL_MAY_DEVELOPMENT_ONLY":
        raise ValueError("Cannot diagnose unseen validation/holdout data")
    if report.get("actionable_signals")!=0 or report.get("trading_wins_claimed") is not False:
        raise ValueError("Invalid nontrading contract")
    labels=report.get("directional_episode_labels")
    if not isinstance(labels,list):
        raise ValueError("Requires --include-episode-records")
    grouping=report["directional_grouping"]
    if len(labels)!=grouping["directional_episodes"]:
        raise ValueError("Episode list does not match grouping total")

    all_ids=[r["id"] for r in labels]
    if len(all_ids)!=len(set(all_ids)):
        raise ValueError("Duplicate directional episode in retrospective report")
    chosen_sha=sha256()
    for entry in labels:
        chosen_sha.update(
            json.dumps(entry,sort_keys=True,separators=(",",":")).encode()+b"\n"
        )
    if chosen_sha.hexdigest()!=report["label_stream_sha256"]:
        raise ValueError("Outcome evidence digest mismatch")

    by_onset_expert={}
    by_participating_expert={}
    experts=sorted({
        exp for r in labels for exp in r["participating_experts"]
    })
    by_direction={}
    by_consensus={}
    by_session={}

    for horizon in HORIZONS:
        h=str(horizon)
        by_onset_expert[h]={
            expert:_describe_episode_cohort(
                [r for r in labels if expert in r["experts_at_onset"]],horizon
            ) for expert in experts
        }
        by_participating_expert[h]={
            expert:_describe_episode_cohort(
                [r for r in labels if expert in r["participating_experts"]],horizon
            ) for expert in experts
        }
        by_direction[h]={
            d:_describe_episode_cohort([r for r in labels if r["direction"]==d],horizon)
            for d in ("LONG","SHORT")
        }
        by_consensus[h]={
            "single_expert_at_onset":_describe_episode_cohort(
                [r for r in labels if len(r["experts_at_onset"])==1],horizon
            ),
            "multiple_experts_at_onset":_describe_episode_cohort(
                [r for r in labels if len(r["experts_at_onset"])>1],horizon
            ),
        }
        by_session[h]={
            "utc_00_to_12":_describe_episode_cohort(
                [r for r in labels if ((r["first_decision_boundary_ms"]//60000) %
                                           (24*60)) < HALF_DAY_MINUTES],horizon
            ),
            "utc_12_to_24":_describe_episode_cohort(
                [r for r in labels if ((r["first_decision_boundary_ms"]//60000) %
                                           (24*60)) >= HALF_DAY_MINUTES],horizon
            ),
        }

    # Verify that all mutually exclusive strata partition total count.
    for horizon in HORIZONS:
        h=str(horizon)
        primary=report["horizon_labels"][h]
        for dimension in (by_direction[h],by_consensus[h],by_session[h]):
            if sum(x["episode_count"] for x in dimension.values())!=len(labels):
                raise ValueError("Descriptive cohort partition mismatch")
            if sum(x["favorable"] for x in dimension.values())!=primary["favorable_above_10bps"]:
                raise ValueError("Descriptive cohort success totals do not reconcile")
            if sum(x["adverse"] for x in dimension.values())!=primary["adverse_below_minus_10bps"]:
                raise ValueError("Descriptive cohort adverse totals do not reconcile")

    return {
        "schema":1,
        "engine":"T7Sonic",
        "status":"RETROSPECTIVE_ATTRIBUTION_NOT_PROSPECTIVE_EXPERT_SELECTION",
        "research_day":report["day"],
        "symbols":report["symbols"],
        "directional_episodes":len(labels),
        "primary_horizon_minutes":60,
        "decision_stream_sha256":report["decision_stream_sha256"],
        "label_stream_sha256":report["label_stream_sha256"],
        "by_onset_expert":by_onset_expert,
        "by_ever_participating_expert":by_participating_expert,
        "by_direction":by_direction,
        "by_onset_consensus":by_consensus,
        "by_utc_half_day":by_session,
        "all_episodes_with_outcomes_at_15_30_60_120_minutes":True,
        "nominal_episode_count_is_not_independent_sample_size":True,
        "limitations":[
            "This is post-outcome descriptive research; selecting experts based on one day overfits",
            "Experts may coactivate on the same episode; expert cohort totals overlap",
            "Even directional episodes can have heavily overlapping mark-price horizons",
            "Means are mark-price proxies, not executable net returns or trade expectancy",
            "Neutral is never counted favorable; no selected-trades-only denominator",
            "No independent date-cluster uncertainty is possible with a single day",
            "No rule is promoted, revised, disabled or connected to live signals",
        ],
    }
