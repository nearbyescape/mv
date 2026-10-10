# V6HBR — adverse-direction failure investigation and live-reference evidence

**Reason for this work:** On 10 October 2026 the operator reported that recent MV Signal alerts moved against the published trade direction. This is a serious practical concern. The V6HBR development-only BTC April–May cost proxy already yielded negative modeled net R for all four cohorts, and no claim of dependable signal accuracy, positive expectancy or edge is justified.

The important distinction is between:
- **Immediate entry adversity:** the market moves at least 0.5 times the plan's initial risk toward the stop, before an equally sized favorable move, especially in the first 60 minutes. A one-minute candle crossing both directions is conservatively ordered adverse-first.
- **Terminal stop-out:** the frozen plan eventually ends at stop or protective exit, regardless of early price path.
- **Actual manual trading P&L:** the operator's Lighter entry/exit, leverage, fees, spread and funding; not captured by the Binance-based signal-reference analytics.

These outcomes are related, but **none is a substitute for another**. A historical BTC Apr–May proxy cannot establish what happened to the live published signals around October 7–10.

## Added research diagnostics

- `services/api/app/research/v6hbr_entry_adversity.py`: for the frozen BTC development pilot, post hoc first-15/30/60-minute MFE/MAE in original risk units, 0.5R adverse versus favorable first event, explicit same-candle adverse-first tie rule, and censoring if a position closed or the data ended before each window. Outputs separate V4, Hybrid, Balanced, Reserved; lane and long/short splits.
- `services/api/tests/test_v6hbr_entry_adversity.py`: future-leakage, missing minute, early-close, unresolved, short-direction and same-minute ambiguity coverage. Two smoke checks are also appended to `test_v6hbr_btc_pricing_pilot.py` because the **already installed root-owned VPS agent's test-file list is intentionally pinned**.
- `services/api/app/research/v6hbr_live_v4_forensics.py`: separate offline analytic of genuine V4 `signal_outcomes` fields for an explicit UTC interval of up to 31 days. It reports sample denominators and adverse-first rates by day, symbol, direction, setup and regime, conservative reference R for resolved non-revised records, and treats open/source-revised entries separately. It does NOT connect to any DB itself.
- `tools/v6hbr-live-v4-readonly-export.py`: optional **operator-approved** PostgreSQL `BEGIN READ ONLY` bounded extraction of only whitelisted existing V4 `signal_outcomes` columns. Its only output is sanitized JSON, excluding `signal_id`, chat IDs, users, tokens, database credentials and private execution details. This file is NOT part of the pinned automated VPS service and **must not be run against production without a deliberate separate authorization**.
- Regression modules `test_v6hbr_live_v4_forensics.py` and `test_v6hbr_live_export_safety.py` check production candle-end timestamp conventions, revised/resolved exclusions, finite denominators, SQL allowlists, read-only transaction and rollback.

## Decision rules

1. **Do not promote V6HBR** merely because it produces more signals, has a higher gross TP ratio or catches a favorable price swing before its stop. Net after costs and missed V4 opportunities matter.
2. If real alerts have shown persistent adverse-first moves, the safer operational posture is to **pause following new alerts with real capital** until the last several days' published-reference data are reconciled. No automatic kill switch, service restart, order or trading-account change has been authorized.
3. Source-revised records, missing minute evidence, unresolved plans, stop/target same-candle ambiguity and actual Lighter fills must remain separate categories. Don't silently count an open trade as a winner or attribute a Binance reference stop to an actual user execution.
4. Analyze the recent V4 outcomes **before** selecting extra filters. Avoid retroactively overfitting the same data: pre-register any new gate using development history, verify on June–July historical validation, and only afterwards open the August–September holdout.
5. Present confidence/uncertainty and sample size. A dozen trades cannot establish a 'super accurate' strategy or a reliable high win rate.

## Execution and security limitations

The hourly VPS research agent has read-only historical archives but no production DB mounts or credentials. It can run the BTC **development** entry-adversity diagnostics automatically after fetching the new research head; it cannot collect real recent V4 signal outcomes unattended. GitHub-connected tools can edit the repository and inspect resulting public GitHub checks, but do not provide VPS SSH or a read-only live database connector. An operator-selected and reviewed production export is still necessary to audit the actual latest alerts; no passwords or SSH keys should be pasted into chat.

**Nothing above alters live V4 0.14.0, engine cadence, BTC market protection, risk allocations, Telegram, database state, or production orders.** The accuracy work is measurement, not a promise of profit.
