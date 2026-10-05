"""Versioned operating hours, separate from immutable financial strategy v1."""
import json
from pathlib import Path
from mv_strategy.signals import canonical_hash
from app.config import get_settings

POLICY = json.loads((Path(__file__).resolve().parents[4] / "packages/contracts/signal-session-v1.json").read_text(encoding="utf-8"))
POLICY_HASH = canonical_hash(POLICY)
DAY = 86_400_000
OFFSET = 330 * 60_000
OPEN = 9 * 3_600_000
CLOSE = 23 * 3_600_000


def inside(timestamp):
    return OPEN <= (timestamp + OFFSET) % DAY < CLOSE


def allowed(source_close, publication):
    return not get_settings().signal_session_enabled or (inside(source_close) and inside(publication))


def session_view(now):
    enabled = get_settings().signal_session_enabled
    today = (now + OFFSET) // DAY * DAY - OFFSET
    is_open = not enabled or inside(now)
    return {"enabled": enabled, "open": is_open, "timezone": "Asia/Kolkata",
            "hours": "09:00 AM–11:00 PM IST", "policy": POLICY["id"],
            "next_open_at": None if is_open else today + OPEN + (DAY if now >= today + CLOSE else 0)}


def policy_evidence():
    return {"id": POLICY["id"], "hash": POLICY_HASH, "timezone": POLICY["timezone"],
            "open": POLICY["open"], "close_exclusive": POLICY["close_exclusive"]}


def check_policy():
    expected = {"id": "IST-DAY-v1", "version": 1, "timezone": "Asia/Kolkata", "utc_offset_minutes": 330,
                "open": "09:00", "close_exclusive": "23:00", "require_source_close_and_publication_inside": True,
                "replay_off_session_signals": False, "market_collection": "continuous"}
    if POLICY != expected:
        raise ValueError("Operating policy changed; register a new session version")
