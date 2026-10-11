"""T7Sonic Phase 2M: immutable *plan only* for external validation.

This module intentionally has no archive access and NO validation replay.
It cannot load, inspect or label June-August observations. A separate
audited loader, contamination declaration and source authentication are
required before validation data may be opened.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from hashlib import sha256
import json

STRATEGY_SHA = "384d08906a8cf9b0ed3e471ee126af680b90fc71"
EXPERT = "failed_breakout_reversal"
MARKETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT")
MONTHS = ("2026-06", "2026-07", "2026-08")
FRAMES = ("1m", "15m", "1h", "4h")
START = date(2026, 6, 12)
END = date(2026, 8, 25)
HORIZON_MINUTES = 60
HURDLE_BPS = 10
BOOTSTRAP_DAYS = 7
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 20261011


def frozen_plan() -> dict:
    """Declare protocol without accepting archive roots, data or parameters."""
    days = (END - START).days + 1
    assert days == 75
    payload = {
        "schema": 1,
        "engine": "T7Sonic",
        "action": "PLAN_ONLY_NO_ARCHIVE_ACCESS",
        "status": "BLOCKED_UNTIL_CONTAMINATION_AUDIT_AND_SEPARATE_LOADER",
        "immutable_model_source_revision": STRATEGY_SHA,
        "candidate_expert": EXPERT,
        "expert_version_policy": "UNCHANGED_DEVELOPMENT_RULES",
        "markets": list(MARKETS),
        "replay_type": "SINGLE_SYMBOL_INDEPENDENT_CAUSAL_WATCH",
        "start_day_utc": START.isoformat(),
        "end_day_utc": END.isoformat(),
        "utc_calendar_days": days,
        "market_days": len(MARKETS) * days,
        "source_months": list(MONTHS),
        "monthly_source_pairs_required": len(MARKETS) * len(FRAMES) * len(MONTHS),
        "source_timeframes": list(FRAMES),
        "historical_input_policy": "BINANCE_USDM_FULL_MONTH_CHECKSUM_AND_1M_RECONCILIATION_REQUIRED",
        "primary_horizon_minutes": HORIZON_MINUTES,
        "strict_favorable_threshold_bps": HURDLE_BPS,
        "strict_adverse_threshold_bps": -HURDLE_BPS,
        "baselines": ["MATCHED_ALWAYS_LONG", "MATCHED_ALWAYS_SHORT"],
        "paired_comparison_policy": "ALL_EXPERT_ONSETS_INCLUDING_NEUTRAL",
        "uncertainty": {
            "blocking_unit": "SIX_MARKET_UTC_CALENDAR_DAY",
            "chronological_moving_block_days": BOOTSTRAP_DAYS,
            "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "two_sided_percentile_confidence": "95%",
        },
        "directional_research_gate": {
            "require_positive_vs_both_baselines": True,
            "require_both_bootstrap_95pct_lower_bounds_positive": True,
            "monthly_groups_positive_vs_both_required": 2,
            "total_monthly_groups": 3,
            "markets_positive_vs_both_required": 4,
            "total_markets": 6,
            "not_permission_to_trade_or_signal": True,
        },
        "secondary_horizons_minutes": [15, 30, 120],
        "not_before_data_access": [
            "Auditor documents whether candidate/dates were previously inspected or tuned in other projects",
            "If contaminated, choose and freeze later contiguous dates BEFORE inspecting any replacement data",
            "Separate research-only validation reader passes no-lookahead and source-chain tests",
            "All source monthly ZIPs and manifests authenticated against publisher SHA256",
            "Reserve a still-later sealed final chronological test interval",
        ],
        "archive_files_opened": 0,
        "validation_market_records_read": 0,
        "historical_result_labels_computed": 0,
        "trade_simulation_performed": False,
        "training_performed": False,
        "signals_published": False,
        "orders_sent": False,
        "production_mutation": False,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {
        **payload,
        "frozen_plan_sha256": sha256(encoded).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="T7Sonic pre-validation frozen plan, without accessing data"
    )
    parser.add_argument("action", choices=("plan",))
    args = parser.parse_args()
    if args.action != "plan":
        raise ValueError("Unsupported validation operation")
    print(json.dumps(frozen_plan(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
