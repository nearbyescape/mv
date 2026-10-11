"""Isolated source-audited probability diagnostic for V6HBR development.

Runs the published V4/V5 source replay with read-only validated archives,
then tests fixed April-only selectivity and a competitive base-rate forecast.
This does not change any live model or signal.
"""
from __future__ import annotations

import argparse
import json

from .v5_archives import load_spec, valid_research_root
from .v6hbr_directional_development import audit_symbol, select_symbols
from .v6hbr_probability_diagnostics import diagnostic_study


def study(root, requested_symbols=None):
    spec, sha = load_spec()
    chosen = select_symbols(spec, requested_symbols)
    labeled, sources = [], {}
    for symbol in chosen:
        audited = audit_symbol(root, spec, sha, symbol)
        labeled.extend(audited.pop("labeled"))
        sources[symbol] = audited
    return {
        "schema":1,
        "run_scope":"ALL_30_FROZEN_SYMBOLS" if requested_symbols is None
                  else "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE",
        "requested_symbols":chosen,
        "complete_symbol_count":len(chosen),
        "frozen_source_spec_sha256":sha,
        "per_symbol_source_provenance":sources,
        "diagnostics":diagnostic_study(labeled),
        "production_mutation":False,
    }


def main():
    parser = argparse.ArgumentParser(description="V6HBR read-only probability diagnostic")
    parser.add_argument("--root",required=True)
    parser.add_argument("--symbols",help="Explicit comma-separated market smoke subset")
    args = parser.parse_args()
    selected = None
    if args.symbols is not None:
        selected = tuple(s.strip() for s in args.symbols.split(","))
        if not selected or any(not s for s in selected):
            parser.error("Nonempty comma-separated markets required")
    root = valid_research_root(args.root)
    print(json.dumps(study(root,selected),indent=2,sort_keys=True))


if __name__ == "__main__":
    main()
