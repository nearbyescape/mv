"use client";
import { useCallback, useEffect, useState } from "react";

export type EngineHealth = {
  session?: {
    enabled: boolean;
    open: boolean;
    timezone: string;
    hours: string;
    next_open_at: number | null;
  };
  state: string;
  running: boolean;
  ready: boolean;
  last_decision_at: number | null;
  error: string | null;
};
export type SnapshotEvidence = {
  timeframe: string;
  open_time: number;
  close_boundary: number;
  ohlcv: Record<"open" | "high" | "low" | "close" | "volume", string>;
  ema20: string;
  ema50: string;
  sma200: string;
  atr: string;
  bars: number;
  history_origin: number;
  lineage: string;
  source_hash: string;
};
export type EngineSignal = {
  id: string;
  symbol: string;
  direction: "long" | "short";
  strategy: string;
  risk_policy: string;
  setup_type?: "pullback_continuation" | "momentum_breakout";
  trend_regime?: "established" | "emerging";
  entry: string;
  stop: string;
  target: string;
  tp1?: string;
  tp2?: string;
  tp3?: string;
  tp1_r?: string;
  tp2_r?: string;
  tp3_r?: string;
  frozen_atr: string;
  risk_distance: string;
  reward_risk: string;
  tick_size: string;
  entry_side: string;
  spread: string;
  spread_bps?: string;
  entry_drift: string;
  entry_drift_limit_atr?: string;
  entry_extension_atr?: string;
  recent_run_entry_atr?: string;
  recent_run_anchor?: string;
  exit_management?: {
    tp1_allocation: string;
    tp2_allocation: string;
    tp3_allocation: string;
    after_tp1: string;
    after_tp2: string;
    maximum_realized_r: string;
    reference_only: boolean;
  };
  source_open_time: number;
  source_close_boundary: number;
  confirmation_open_time: number;
  published_at: number;
  expires_at: number;
  quote_time: number;
  quote_received_at: number;
  evidence_hash: string;
  plan_hash: string;
  integrity_valid: boolean;
  execution: string;
  status: string;
  slot: "reserved" | "held" | null;
  entry_actionable: boolean;
  source_revised: boolean;
  evidence: {
    source: SnapshotEvidence;
    previous: SnapshotEvidence;
    confirmation: SnapshotEvidence;
    structure?: SnapshotEvidence[];
    setup?: {
      type: "pullback_continuation" | "momentum_breakout" | null;
      regime: "established" | "emerging" | null;
      structure_level: string | null;
    };
    btc_regime?: { state: string; passed: boolean };
    checks: { id: string; passed: boolean; value?: string; minimum?: string; maximum?: string }[];
    guards: Record<string, boolean>;
    quote: { bid: string; ask: string; time: number; received_at: number };
    contract_hash: string;
    decimal_precision: number;
  };
  events: { type: string; time: number; detail: Record<string, unknown> }[];
  ai: string;
  ai_review?: {
    status: string;
    model?: string;
    summary: string | null;
    assessment?: "consistent" | "concern" | "insufficient";
    limitations?: string[];
    check_ids?: string[];
    completed_at?: number | null;
    evidence_hash?: string;
    error_code?: string | null;
  };
  telegram: string;
};
export type SignalFeed = {
  server_time: number;
  engine: EngineHealth;
  signals: EngineSignal[];
  decisions: {
    id: string;
    symbol: string;
    source_open_time: number;
    outcome: string;
    reason: string;
    direction: string | null;
    updated_at: number;
    attempts: number;
  }[];
  slots: { symbol: string; signal_id: string; state: "reserved" | "held" }[];
};

export function useSignalFeed(enabled: boolean) {
  const [state, setState] = useState<{
    data: SignalFeed | null;
    error: string | null;
    offset: number;
  }>({ data: null, error: null, offset: 0 });
  const [clock, setClock] = useState(() => Date.now());
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch("/api/signals", {
        cache: "no-store",
        signal,
      });
      if (response.status === 401) location.assign("/login");
      if (!response.ok)
        throw new Error(
          "Signal API unavailable. Retained plans are historical; entry actions are paused.",
        );
      const data = (await response.json()) as SignalFeed;
      if (
        !Array.isArray(data.signals) ||
        !Array.isArray(data.decisions) ||
        !data.engine ||
        !Number.isFinite(data.server_time)
      )
        throw new Error("Invalid signal feed response");
      if (!signal?.aborted)
        setState({ data, error: null, offset: data.server_time - Date.now() });
    } catch (error) {
      if (!signal?.aborted)
        setState((old) => ({
          ...old,
          error:
            error instanceof Error ? error.message : "Signal feed unavailable",
        }));
    }
  }, []);
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      await refresh(abort.signal);
      if (!abort.signal.aborted) timer = setTimeout(load, 8000);
    }
    void load();
    const clockTimer = setInterval(() => setClock(Date.now()), 1000);
    return () => {
      abort.abort();
      clearTimeout(timer);
      clearInterval(clockTimer);
    };
  }, [enabled, refresh]);
  return { ...state, now: clock + state.offset, refresh };
}

export type SignalFeedState = ReturnType<typeof useSignalFeed>;
export function statusAt(signal: EngineSignal, now: number) {
  return signal.status === "active" && now >= signal.expires_at
    ? "expired"
    : signal.status;
}
export function canHold(signal: EngineSignal, feed: SignalFeedState) {
  return (
    !feed.error &&
    !!feed.data?.engine.ready &&
    signal.entry_actionable &&
    !signal.source_revised &&
    signal.integrity_valid &&
    statusAt(signal, feed.now) === "active"
  );
}
export const reasonLabel = (reason: string) =>
  (
    ({
      STARTUP_BASELINE_NO_RETROACTIVE_ENTRY:
        "Startup baseline · waiting for the next closed candle",
      NO_FRESH_RECLAIM_OR_LOSS: "No fresh EMA20 reclaim or loss",
      TREND_REGIME_NOT_READY: "No qualified 1H trend regime",
      NO_PULLBACK_OR_BREAKOUT_TRIGGER:
        "No qualified pullback continuation or structural breakout",
      "4H_TREND_NOT_ALIGNED": "Completed 4H trend is not aligned",
      BTC_REGIME_CONTRADICTION: "BTC regime strongly contradicts this alt setup",
      BTC_REGIME_UNAVAILABLE: "Waiting for BTC regime evidence",
      SPREAD_TOO_WIDE: "Live spread is too wide for publication",
      ENTRY_OVEREXTENDED: "Entry moved too far from EMA20",
      RECENT_RUN_OVEREXTENDED: "Entry arrived after an excessive recent directional run",
      SAME_DIRECTION_SIGNAL_THIS_SESSION:
        "Same-direction signal already published for this coin this IST session",
      RULES_AND_GUARDS_PASSED: "Published · all rules and guards passed",
      WAITING_EXPECTED_4H: "Waiting for the required completed 4H candle",
      "4H_CONFIRMATION_FAILED": "4H trend confirmation failed",
      ACTIVE_SIGNAL_OR_HELD_POSITION:
        "Blocked by an active setup or held position",
      EXPIRED_ENTRY_WINDOW: "Entry window expired",
      MISSED_ENTRY_PRICE_DRIFT: "Entry moved beyond 0.5 ATR",
      COLLECTOR_NOT_LIVE: "Collector is unavailable or stale",
      STALE_OR_FUTURE_QUOTE: "Waiting for a valid fresh quote",
      AWAITING_FRESH_QUOTE: "Fetching an entry quote",
    }) as Record<string, string>
  )[reason] || reason.toLowerCase().replaceAll("_", " ");
