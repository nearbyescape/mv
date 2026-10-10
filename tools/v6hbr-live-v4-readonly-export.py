"""Operator-invoked, read-only production V4 outcome export.

Run from the ALREADY running MV API container, using a reviewed script piped
over stdin (no installation). Opens one PostgreSQL READ ONLY transaction and
exports only whitelisted, existing SignalOutcome research fields to stdout.
Never modifies models, strategy decisions, Telegram or the production DB.

No SSH credentials / database URLs / auth tokens / Signal IDs are printed.
The explicit UTC millisecond window is bounded to 31 days. This is an opt-in
operator command; the automatic V6HBR research agent NEVER uses it.
"""
from __future__ import annotations

import argparse
import json
import sys
from sqlalchemy import text

COLUMNS = (
    "strategy", "symbol", "direction", "setup_type", "trend_regime",
    "published_at", "first_observed_minute", "status", "observed_bars",
    "source_revised", "intrabar_ambiguous",
    "favorable_050_at", "adverse_050_at",
    "mfe_r", "mae_r", "conservative_r",
)

SQL = """
SELECT
    strategy, symbol, direction, setup_type, trend_regime,
    published_at, first_observed_minute, status, observed_bars,
    source_revised, intrabar_ambiguous,
    favorable_050_at, adverse_050_at, mfe_r, mae_r, conservative_r
FROM signal_outcomes
WHERE strategy = :strategy
  AND published_at >= :start_ms
  AND published_at < :end_ms
ORDER BY published_at, symbol
LIMIT 100001
"""


def validate_window(start_ms: int, end_ms: int) -> None:
    if (type(start_ms) is not int or type(end_ms) is not int
        or not 0 < start_ms < end_ms
        or end_ms - start_ms > 31 * 24 * 60 * 60_000):
        raise ValueError("Explicit nonempty UTC interval <=31 days required")


def read_sanitized_rows(conn, *, start_ms: int, end_ms: int) -> list[dict]:
    """PostgreSQL transaction-level read-only guard, even with an RW user."""
    validate_window(start_ms, end_ms)
    conn.exec_driver_sql("BEGIN READ ONLY")
    try:
        rows = conn.execute(
            text(SQL),
            {
                "strategy": "MV-TREND-DUAL-v4",
                "start_ms": start_ms,
                "end_ms": end_ms,
            },
        ).mappings().all()
        if len(rows) > 100_000:
            raise ValueError("Unexpectedly large outcome extraction; stop")
        return [{key: row[key] for key in COLUMNS} for row in rows]
    finally:
        # Even a read-only SQL transaction is always explicitly rolled back.
        conn.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description="Operator-approved read-only V4 outcome export")
    parser.add_argument("--start-ms", type=int, required=True)
    parser.add_argument("--end-ms", type=int, required=True)
    args = parser.parse_args()
    validate_window(args.start_ms, args.end_ms)
    from app.database import engine
    if engine.dialect.name != "postgresql":
        raise SystemExit("STOP: only production PostgreSQL read-only export permitted")
    with engine.connect() as connection:
        rows = read_sanitized_rows(
            connection, start_ms=args.start_ms, end_ms=args.end_ms
        )
    json.dump(rows, sys.stdout, separators=(",", ":"), sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
