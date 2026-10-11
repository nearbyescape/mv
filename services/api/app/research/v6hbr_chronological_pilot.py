"""Networkless, development-only probabilistic reference pilot.

A separate CLI isolates the baseline experimental model from the fixed
directional and trade-cost studies. No order execution or production writes.
"""
from __future__ import annotations

import argparse
import json

from .v5_archives import load_spec, valid_research_root
from .v6hbr_directional_development import audit_symbol, select_symbols
from .v6hbr_chronological_probability import run_chronological_pilot


def study(root, symbols=None):
    spec, spec_sha = load_spec()
    selected = select_symbols(spec, symbols)
    labeled, provenance = [], {}
    for symbol in selected:
        audited = audit_symbol(root, spec, spec_sha, symbol)
        labeled.extend(audited.pop("labeled"))
        provenance[symbol] = audited
    return {
        "schema": 1,
        "run_scope": "ALL_30_FROZEN_SYMBOLS" if symbols is None
                     else "EXPLICIT_SMOKE_SUBSET_NOT_FULL_UNIVERSE",
        "requested_symbols": selected,
        "complete_symbol_count": len(selected),
        "source_spec_sha256": spec_sha,
        "source_provenance": provenance,
        "pilot": run_chronological_pilot(labeled),
        "production_mutation": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Research-only chronological probability pilot")
    parser.add_argument("--root", required=True)
    parser.add_argument("--symbols", help="Optional explicit comma-separated smoke subset")
    args = parser.parse_args()
    chosen = None
    if args.symbols is not None:
        chosen = tuple(x.strip() for x in args.symbols.split(","))
        if not chosen or any(not x for x in chosen):
            parser.error("Nonempty unique symbol subset required")
    print(json.dumps(
        study(valid_research_root(args.root), chosen), indent=2, sort_keys=True
    ))


if __name__ == "__main__":
    main()
