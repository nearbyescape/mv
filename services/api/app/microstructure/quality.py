"""Read-only V7Sonic public market data quality and abstention audit.

Recompute classifier reasons from COMMITTED, HASH-CHECKED observations,
without modifying the journal or any trading/Telegram service.

First-failure reasons are ordered by the frozen classifier. Separately
reported blockers can overlap, so their counts must NOT be summed.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal as D

from .core import SYMBOLS, HORIZONS_MS, classify
from .journal import checked, verify_chain


def quality_report(conn, *, last_samples_per_symbol: int = 288, verify=True):
    if type(last_samples_per_symbol) is not int or not 2 <= last_samples_per_symbol <= 2880:
        raise ValueError("last_samples_per_symbol must be an integer in [2,2880]")
    symbols = {}
    total_decisions = Counter()
    total_independent_blockers = Counter()
    total_preportfolio = 0
    total_pairs = 0
    for symbol in SYMBOLS:
        # Protect against accidental modification and corrupted stored
        # inputs before replaying even the most recent subset of samples.
        verified_samples = verify_chain(conn, symbol) if verify else None
        rows = conn.execute(
            "SELECT * FROM observations WHERE symbol=? "
            "ORDER BY observed_at_ms DESC LIMIT ?",
            (symbol, last_samples_per_symbol),
        ).fetchall()
        observations = [checked(row) for row in reversed(rows)]
        failures = Counter()
        independent = Counter()
        valid_timing = 0
        preportfolio = 0
        taker_period_advances = 0
        max_gap = None
        min_gap = None
        lag_samples = []
        funding_mins = []
        for row in observations:
            if row["symbol"] != symbol:
                raise ValueError("Observation mismatched its journal symbol")
            # Historical taker period lag is observable at receive time;
            # no future publication or later candle is consulted.
            lag = row["observed_at_ms"] - (
                row["taker_period_start_ms"] + 300_000
            )
            lag_samples.append(lag)
            funding_mins.append(
                (row["next_funding_ms"]-row["observed_at_ms"]) / 60_000
            )
        for previous,current in zip(observations,observations[1:]):
            total_pairs += 1
            delta = current["observed_at_ms"] - previous["observed_at_ms"]
            min_gap = delta if min_gap is None else min(min_gap,delta)
            max_gap = delta if max_gap is None else max(max_gap,delta)
            if 300_000 <= delta <= 1_200_000:
                valid_timing += 1
            else:
                independent["INVALID_TIMING"] += 1
            if current["taker_period_start_ms"] <= previous["taker_period_start_ms"]:
                independent["TAKER_NOT_ADVANCED"] += 1
            else:
                taker_period_advances += 1
            if current["next_funding_ms"] <= current["observed_at_ms"] + max(HORIZONS_MS):
                independent["FUNDING_WITHIN_120M"] += 1
            decision = classify(previous,current)
            if decision["status"] == "PAPER_CANDIDATE":
                preportfolio += 1
                total_preportfolio += 1
                failures["PRE_PORTFOLIO_CANDIDATE"] += 1
            else:
                failures[decision["reason"]] += 1
        total_decisions.update(failures)
        total_independent_blockers.update(independent)
        symbols[symbol] = {
            "observations_in_window":len(observations),
            "fully_verified_chain_records":verified_samples,
            "first_utc_ms":observations[0]["observed_at_ms"] if observations else None,
            "last_utc_ms":observations[-1]["observed_at_ms"] if observations else None,
            "adjacent_pairs":max(0,len(observations)-1),
            "valid_timing_pairs":valid_timing,
            "minimum_gap_ms":min_gap,
            "maximum_gap_ms":max_gap,
            "taker_period_advanced_pairs":taker_period_advances,
            "minimum_taker_period_lag_ms":min(lag_samples) if lag_samples else None,
            "maximum_taker_period_lag_ms":max(lag_samples) if lag_samples else None,
            "minimum_minutes_until_funding":min(funding_mins) if funding_mins else None,
            "maximum_minutes_until_funding":max(funding_mins) if funding_mins else None,
            "first_failure_classifier_counts":dict(sorted(failures.items())),
            "independent_blockers_overlapping":dict(sorted(independent.items())),
            "preportfolio_candidates":preportfolio,
        }
    return {
        "kind":"V7_MICROSTRUCTURE_CAUSAL_OFFLINE_QUALITY_AUDIT",
        "research_only":True,
        "source":"COMMITTED_POINT_IN_TIME_OBSERVATIONS_ONLY",
        "verification":"FULL_SHA256_CHAIN" if verify else "PAYLOAD_HASHES_ONLY",
        "window":"LATEST_SAMPLES_PER_MARKET",
        "samples_per_market_limit":last_samples_per_symbol,
        "total_adjacent_pairs":total_pairs,
        "first_failure_classifier_totals":dict(sorted(total_decisions.items())),
        "independent_blockers_overlapping_totals":dict(sorted(total_independent_blockers.items())),
        "preportfolio_candidates_not_actual_published_signals":total_preportfolio,
        "actual_execution_or_intrabar_fill_verified":False,
        "rules_or_thresholds_changed":False,
        "client_publication_authorized":False,
        "symbols":symbols,
    }
