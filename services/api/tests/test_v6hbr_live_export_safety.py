"""Unit checks for whitelisted, transaction-level READ ONLY V4 export.

Does NOT connect to a production database.
"""
from pathlib import Path
import importlib.util
import pytest

P = Path(__file__).resolve().parents[3] / "tools/v6hbr-live-v4-readonly-export.py"
spec = importlib.util.spec_from_file_location("v6hbr_readonly_export", str(P))
assert spec and spec.loader
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)


class Records:
    def __init__(self, rows):
        self.rows = rows
    def mappings(self):
        return self
    def all(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.ops = []

    def exec_driver_sql(self, query):
        self.ops.append(("SQL", query))

    def execute(self, sql, params):
        self.ops.append(("SELECT", str(sql), dict(params)))
        return Records(self.rows)

    def rollback(self):
        self.ops.append(("ROLLBACK",))


def test_export_selects_whitelisted_fields_in_read_only_transaction():
    example = {key: None for key in export.COLUMNS}
    example.update({"strategy": "MV-TREND-DUAL-v4", "symbol": "BTCUSDT"})
    example["telegram_chat_id"] = "MUST_NOT_EXPORT"
    db = FakeConnection([example])
    items = export.read_sanitized_rows(db, start_ms=100_000, end_ms=200_000)
    assert items[0]["symbol"] == "BTCUSDT"
    assert "telegram_chat_id" not in items[0]
    assert set(items[0]) == set(export.COLUMNS)
    assert db.ops[0] == ("SQL", "BEGIN READ ONLY")
    assert db.ops[1][0] == "SELECT"
    assert "FROM signal_outcomes" in db.ops[1][1]
    assert db.ops[1][2]["strategy"] == "MV-TREND-DUAL-v4"
    assert db.ops[-1] == ("ROLLBACK",)


def test_export_rolls_back_even_when_select_fails():
    class Rejecting(FakeConnection):
        def execute(self, sql, params):
            raise RuntimeError("test query error")
    db = Rejecting([])
    with pytest.raises(RuntimeError, match="query error"):
        export.read_sanitized_rows(db, start_ms=100_000, end_ms=200_000)
    assert db.ops == [("SQL", "BEGIN READ ONLY"), ("ROLLBACK",)]


def test_rejects_implicit_or_unbounded_historical_export():
    with pytest.raises(ValueError, match="31 days"):
        export.validate_window(0, 1)
    with pytest.raises(ValueError, match="31 days"):
        export.validate_window(100_000, 32*24*60*60_000)
    with pytest.raises(ValueError, match="31 days"):
        export.validate_window(200_000, 100_000)


def test_no_write_path_or_private_fields_in_sql():
    sql = export.SQL.upper()
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TELEGRAM", "CHAT_ID",
                      "PASSWORD", "TOKEN", "USER_ID", "SIGNAL_ID"):
        assert forbidden not in sql
    assert "LIMIT 100001" in sql
