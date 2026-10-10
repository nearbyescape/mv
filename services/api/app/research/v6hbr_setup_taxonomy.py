"""Frozen V4/V5 research setup taxonomy.

Do not silently strip the V5 15-minute suffix: V4 hourly and rescue
15-minute setups must remain separately identifiable for evidence matching.
Only these exact four setup identifiers are emitted by the inherited V4
strategy_v3 / V5 evaluate_trigger_v5 rule contracts.
"""
from __future__ import annotations

HOURLY_SETUP_TYPES = frozenset((
    "momentum_breakout", "pullback_continuation",
))
RESCUE_SETUP_TYPES = frozenset((
    "momentum_breakout_15m", "pullback_continuation_15m",
))
ALL_SETUP_TYPES = HOURLY_SETUP_TYPES | RESCUE_SETUP_TYPES
BREAKOUT_SETUP_TYPES = frozenset((
    "momentum_breakout", "momentum_breakout_15m",
))


def validated_setup_type(setup_type: str, lane: str | None = None) -> str:
    """Fail closed on unseen strategy contract values and lane mismatches."""
    if not isinstance(setup_type, str) or setup_type not in ALL_SETUP_TYPES:
        raise ValueError("Unsupported frozen V4/V5 setup_type")
    if lane == "v4_base":
        if setup_type not in HOURLY_SETUP_TYPES:
            raise ValueError("15m rescue setup cannot be a V4 hourly base")
    elif lane == "15m_rescue":
        if setup_type not in RESCUE_SETUP_TYPES:
            raise ValueError("V4 hourly setup cannot be a 15m rescue")
    elif lane is not None:
        raise ValueError("Unsupported research candidate lane")
    return setup_type
