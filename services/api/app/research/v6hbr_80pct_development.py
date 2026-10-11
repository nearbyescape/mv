"""Standalone offline shadow accuracy audit (development data only).

Replays original frozen events and scores *fixed* decision-time filters.
No hindsight candidate generation, no new fills and no live activation.
Use --symbols BTCUSDT,ETHUSDT only for a smoke subset, not certification.
"""
from __future__ import annotations

import argparse
import json

from .v5_archives import load_spec, valid_research_root
from .v6hbr_directional_development import audit_symbol, select_symbols
from .v6hbr_80pct_shadow import audit_80pct_shadow_research


def run_study(root, requested_symbols=None):
    spec, spec_sha = load_spec()
    symbols = select_symbols(spec, requested_symbols)
    sources = {}
    labeled = []
    for symbol in symbols:
        result = audit_symbol(root, spec, spec_sha, symbol)
        labeled.extend(result.pop("labeled"))
        sources[symbol] = result
    return {
        "schema": 1,
        "status": "SHADOW_TARGET_STUDY_NOT_MODEL_PROMOTION",
        "period": "2026-04-01..2026-05-31 development only",
        "run_scope": "ALL_30_FROZEN_SYMBOLS" if requested_symbols is None
                     else "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE",
        "requested_symbols": symbols,
        "complete_symbol_count": len(symbols),
        "frozen_spec_sha256": spec_sha,
        "sources": sources,
        "shadow_target": audit_80pct_shadow_research(labeled),
        "production_mutation": False,
    }


def main():
    p = argparse.ArgumentParser(description="V6HBR fixed shadow target research")
    p.add_argument("--root", required=True)
    p.add_argument("--symbols", help="Comma-separated explicit smoke subset")
    args = p.parse_args()
    subset = None
    if args.symbols is not None:
        subset = tuple(x.strip() for x in args.symbols.split(","))
        if not subset or any(not s for s in subset):
            p.error("Nonempty comma-separated symbol subset required")
    print(json.dumps(
        run_study(valid_research_root(args.root), subset),
        indent=2, sort_keys=True,
    ))


if __name__ == "__main__":
    main()
