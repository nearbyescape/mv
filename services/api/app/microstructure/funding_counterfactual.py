"""Offline funding-horizon sensitivity report (research only; no orders)."""
from collections import Counter
from .core import SYMBOLS, HORIZONS_MS, classify, classify_research_horizon
from .journal import checked, verify_chain

def compare_horizons(db, n=288):
    if type(n) is not int or not 2 <= n <= 2880:
        raise ValueError("Invalid window")
    results = {h: {"pairs": 0, "candidates": 0, "reasons": Counter()} for h in HORIZONS_MS}
    for symbol in SYMBOLS:
        verify_chain(db, symbol)
        rows = db.execute(
            "SELECT * FROM observations WHERE symbol=? ORDER BY observed_at_ms DESC LIMIT ?",
            (symbol, n),
        ).fetchall()
        items = [checked(r) for r in reversed(rows)]
        for previous, current in zip(items, items[1:]):
            baseline = classify(previous, current)
            for h in HORIZONS_MS:
                decision = classify_research_horizon(previous, current, h)
                if h == max(HORIZONS_MS) and decision != baseline:
                    raise ValueError("Frozen strategy parity violation")
                result = results[h]
                result["pairs"] += 1
                if decision["status"] == "PAPER_CANDIDATE":
                    result["candidates"] += 1
                else:
                    result["reasons"][decision["reason"]] += 1
    return {
        "research_only": True,
        "changes_to_paper_collector": False,
        "strategy_candidate_model_unchanged": True,
        "not_out_of_sample": True,
        "profitability_demonstrated": False,
        "comparison": {
            str(h // 60000) + "m": {
                "pairs": result["pairs"],
                "preportfolio_candidates": result["candidates"],
                "first_failure_reasons": dict(sorted(result["reasons"].items())),
            }
            for h, result in results.items()
        },
    }
