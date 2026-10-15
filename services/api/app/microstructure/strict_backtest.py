"""V7Sonic frozen strategy historical replay on AUTHENTIC collected evidence.

This is a deterministic consistency / observational outcome audit, not an
executable-fill P&L backtest. OHLCV cannot reconstruct required historical
twenty-level depth or contemporaneous instantaneous open interest.
No market network, broker access, credentials or subscription publishing.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal as D
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory

from .core import HORIZONS_MS, POLICY_SHA, SYMBOLS
from .journal import checked, open_journal, record_snapshot, report, verify_chain


TABLES = {
    "paper_ideas": "SELECT id,symbol,decided_at_ms,payload,sha256 FROM paper_ideas ORDER BY decided_at_ms,id",
    "horizon_observations": (
        "SELECT idea_id,horizon_ms,observed_at_ms,payload,sha256 "
        "FROM horizon_observations ORDER BY idea_id,horizon_ms"
    ),
}


def _comparison_rows(db, sql):
    return [tuple(r) for r in db.execute(sql)]


def _point_mark_summary(conn, horizon):
    values = []
    for row in conn.execute(
        "SELECT payload FROM horizon_observations WHERE horizon_ms=?",
        (horizon,),
    ):
        point = json.loads(row["payload"])
        # Integrity was checked by report() after verifying replay parity.
        values.append(D(point["net_reference_R"]))
    size = len(values)
    return {
        "available_future_marks": size,
        "mean_net_reference_R": str(sum(values, D(0))/D(size)) if size else None,
        "median_net_reference_R": str(median(values)) if size else None,
        "positive_reference_fraction": str(D(sum(v>0 for v in values))/D(size)) if size else None,
        "total_reference_R_not_realized_profit": str(sum(values, D(0))) if size else None,
        "live_stop_and_target_fill_verified": False,
        "no_intrabar_stop_target_ordering": True,
        "book_point_not_executable_trade": True,
    }


def backtest_from_journal(journal_path: Path, *, max_observations=75000):
    """Verify SHA chains and replay the ORIGINAL immutable trading policy.

    Reject differences between simulated and stored paper ideas/horizon
    outcome rows; the replica lives solely in an ephemeral local directory.
    All snapshots are classified in recorded receive-time order.
    """
    if type(max_observations) is not int or not 2<=max_observations<=75000:
        raise ValueError("max_observations must be in [2,75000]")
    if not isinstance(journal_path,Path) or not journal_path.is_absolute():
        raise ValueError("Require absolute journal Path")

    with closing(open_journal(journal_path,readonly=True)) as source:
        snapshot_counts={s:verify_chain(source,s) for s in SYMBOLS}
        total=sum(snapshot_counts.values())
        if total>max_observations:
            raise ValueError(
                "Journal exceeds bounded replay size; preserve all evidence "
                "and run offline in a separately provisioned environment"
            )
        source_report=report(source)
        snapshots=[
            checked(row)
            for row in source.execute(
                "SELECT * FROM observations ORDER BY observed_at_ms,symbol"
            )
        ]
        if len(snapshots)!=total:
            raise ValueError("Verified observations do not match replay input size")

        with TemporaryDirectory(prefix="v7-strict-backtest-") as folder:
            temporary_database=Path(folder)/"ephemeral-replay.sqlite"
            with closing(open_journal(temporary_database)) as simulated:
                decisions=Counter()
                for item in snapshots:
                    outcome=record_snapshot(simulated,item)
                    if outcome["stored"] is not True:
                        raise ValueError("Duplicate or uncommitted historical observation")
                    status=outcome["decision"]["status"]
                    reason=outcome["decision"].get("reason",status)
                    decisions[reason]+=1

                sim_report=report(simulated)
                if sim_report!=source_report:
                    raise ValueError("Original report differs from historical replay")
                # Explicitly verify every source idea/outcome, not just counts.
                for table,sql in TABLES.items():
                    if _comparison_rows(source,sql)!=_comparison_rows(simulated,sql):
                        raise ValueError(
                            f"Frozen replay differs from original stored {table}"
                        )

                # No assumed fills; marks use only previously captured
                # book quotes for paper ideas issued under the frozen policy.
                horizon_marks={
                    str(h//60000)+"m":_point_mark_summary(simulated,h)
                    for h in HORIZONS_MS
                }

    timestamps=[item["observed_at_ms"] for item in snapshots]
    first=min(timestamps) if timestamps else None
    last=max(timestamps) if timestamps else None
    days=sorted({
        datetime.fromtimestamp(t/1000,timezone.utc).date().isoformat()
        for t in timestamps
    })
    ideas=source_report["paper_candidate_total"]
    status=(
        "NOT_ESTIMABLE_ZERO_PAPER_IDEAS" if not ideas
        else "INCONCLUSIVE_REFERENCE_MARKS_NOT_EXECUTED_TRADES"
    )
    return {
        "kind":"V7_FROZEN_ORIGINAL_POLICY_STRICT_REPLAY",
        "input":"HASH_CHAIN_VERIFIED_COLLECTED_PUBLIC_REST_SNAPSHOTS_ONLY",
        "policy_sha256":POLICY_SHA,
        "source_journal_unmodified":True,
        "replayed_in_ephemeral_sqlite":True,
        "replay_ledger_exact_match":True,
        "no_synthetic_or_proxy_market_inputs":True,
        "utc_first_observation":datetime.fromtimestamp(first/1000,timezone.utc).isoformat() if first else None,
        "utc_last_observation":datetime.fromtimestamp(last/1000,timezone.utc).isoformat() if last else None,
        "observed_utc_dates":days,
        "observation_count":total,
        "per_symbol_counts":snapshot_counts,
        "replay_decision_reasons":dict(sorted(decisions.items())),
        "frozen_paper_ideas":ideas,
        "frozen_paper_directions":source_report["paper_candidate_by_direction"],
        "reference_book_point_marks_by_horizon":horizon_marks,
        "profitability_validation":{
            "status":status,
            "real_trade_count":0,
            "real_trade_win_rate":None,
            "real_trade_mean_after_cost_R":None,
            "live_exchange_fill_verified":False,
            "intra_horizon_stop_target_sequence_verified":False,
            "funding_settlement_actual_cost_modeled":False,
            "historical_full_L2_microstructure_completeness_verified":False,
            "independent_holdout_profitable_edge_proven":False,
            "suitable_for_real_money_or_client_signals":False,
        },
        "warnings":[
            "One five-minute point-in-time REST snapshot is not full event-by-event historical order book.",
            "A future book-touch quote cannot establish first stop/target crossing or an executable fill.",
            "OHLCV, archived depth-band aggregates and five-minute OI aggregates are not interchangeable with the frozen V7 inputs.",
            "Costs on book-point marks are modeled, not audited live broker fills.",
            "Zero generated ideas means no win rate or trading expectancy can be estimated.",
        ],
        "external_network_requests":0,
        "exchange_orders":0,
        "telegram_messages":0,
    }
