# MV-TREND-DUAL-v3

Release candidate: **0.13.0**  
Strategy ID: **MV-TREND-DUAL-v3**  
Risk policy: **RISK-ATR14-SCALED-TP-v3**

V3 is a versioned production candidate derived from the live V2 engine. V2 source, contract and historical analytics remain preserved. V3 changes only entry selectivity, same-session re-entry policy and reference exit management; it does not place exchange orders.

## Entry architecture

V3 retains completed 1H source candles, exact completed 4H confirmation, EMA20/EMA50/SMA200, Wilder ATR14, 500-bar warmup, established/emerging trend regimes, pullback continuation, 12-bar momentum breakout, BTC contradiction veto, 10 bps maximum spread, five-minute entry window and a two-ATR initial stop.

The anti-chase limits are:

| Guard | Pullback | Breakout |
| --- | ---: | ---: |
| Maximum source extension from EMA20 | 1.00 ATR | 1.50 ATR |
| Maximum live-entry drift from source close | 0.50 ATR | 0.75 ATR |
| Maximum live-entry extension from EMA20 | 1.00 ATR | 1.50 ATR |
| Maximum directional run from the extreme of the preceding six completed 1H bars | 2.50 ATR | 2.50 ATR |

The recent-run guard is evaluated twice: first on the completed source close and again on the fresh live reference entry. A setup that becomes extended during the quote phase is rejected as `RECENT_RUN_OVEREXTENDED`.

V3 also allows at most one published signal in the **same direction** for the same symbol during an IST operating session. A later opposite-direction setup can still qualify if all V3 rules pass. Existing held-position/active-slot protection remains independent and can block either direction.

## Scaled reference targets

The initial stop remains two frozen ATR from the reference entry. Profit management is:

| Level | Nominal R | Allocation | After level is reached |
| --- | ---: | ---: | --- |
| TP1 | +1.0R | 30% | Move remaining reference stop to entry |
| TP2 | +1.5R | 30% | Move remaining reference stop to TP1 |
| TP3 | +2.0R | 40% | Reference plan complete |

Targets and the stop are rounded conservatively to the Binance price tick. Therefore exact stored `tp1_r`, `tp2_r` and `tp3_r` can differ minutely from the nominal values. `target` remains an API compatibility alias for TP3.

If all three targets are reached, the nominal weighted reference result is **+1.55R**. If TP1 is reached and the remaining reference position later returns to entry, the conservative scaled result is approximately **+0.30R**. If TP2 is reached and the remaining runner later returns to TP1, the nominal result is approximately **+1.15R**.

These are reference-plan measurements only. MV does not submit orders, verify fills, account for user-specific execution, or claim realized P&L.

## Conservative analytics ordering

V3 analytics starts from the first full completed Binance 1-minute candle at or after publication. A protective-stop change caused by TP1 or TP2 becomes effective from the **next** completed 1-minute observation. If the previously active stop and a newly reached target both occur in the same 1-minute candle, ordering is unknowable, so analytics records an ambiguous terminal result using the previously active stop first.

V2 outcomes remain queryable separately. V3 is the default Performance view after 0.13.0.

## Delivery and UI

Every V3 plan exposes Entry, SL, TP1, TP2 and TP3 in the web signal panel, signal detail view, journal and chart. Telegram messages contain all three target levels, their 30/30/40 allocations and the TP1/TP2 protective-stop guidance.

Performance analytics remain isolated in the dedicated **Performance** section and are not loaded on Overview.
