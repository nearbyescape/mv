"use client";

import { Activity, Download, RefreshCw, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { formatIST } from "@/lib/time";

type Summary = {
  signals: number;
  observed: number;
  open: number;
  target: number;
  stop: number;
  ambiguous: number;
  source_revised: number;
  resolved: number;
  target_rate: string | null;
  expectancy_r: string | null;
  profit_factor: string | null;
  one_r_before_stop: number;
  two_r_before_stop: number;
  one_r_before_stop_rate: string | null;
  two_r_before_stop_rate: string | null;
  average_mfe_r: string | null;
  average_mae_r: string | null;
};

type Performance = {
  strategy: string;
  method: string;
  minute_observation: string;
  ambiguous_policy: string;
  overall: Summary;
  cohorts: Array<Summary & { setup_type: string; direction: string }>;
  by_symbol: Array<Summary & { symbol: string }>;
  decision_blockers: Array<{ reason: string; count: number }>;
  missed_opportunities_6h: Array<{
    reason: string;
    decisions: number;
    average_max_up_atr: string;
    average_max_down_atr: string;
    moves_up_ge_2atr: number;
    moves_down_ge_2atr: number;
  }>;
  next_review_milestone: number | null;
  completed_decision_windows: number;
};

type Outcome = {
  signal_id: string;
  symbol: string;
  direction: "long" | "short";
  setup_type: "pullback_continuation" | "momentum_breakout";
  trend_regime: "established" | "emerging";
  published_at: number;
  status: string;
  terminal_at: number | null;
  target_r: string;
  mfe_r: string;
  mae_r: string;
  one_r_before_stop: boolean;
  two_r_before_stop: boolean;
  intrabar_ambiguous: boolean;
  source_revised: boolean;
  observed_bars: number;
  conservative_r: string | null;
};

const percent = (value: string | null) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
const rValue = (value: string | null) =>
  value == null ? "—" : `${Number(value).toFixed(3)}R`;
const setupLabel = (value: string) =>
  value === "momentum_breakout" ? "Breakout" : "Pullback";
const reasonLabel = (value: string) =>
  value.toLowerCase().replaceAll("_", " ");

function downloadCsv(outcomes: Outcome[]) {
  const columns = [
    "signal_id",
    "symbol",
    "direction",
    "setup_type",
    "trend_regime",
    "published_at",
    "status",
    "terminal_at",
    "target_r",
    "conservative_r",
    "mfe_r",
    "mae_r",
    "one_r_before_stop",
    "two_r_before_stop",
    "intrabar_ambiguous",
    "source_revised",
    "observed_bars",
  ] as const;
  const escape = (value: unknown) => {
    const text = String(value ?? "");
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const rows = outcomes.map((row) =>
    columns.map((column) => escape(row[column])).join(","),
  );
  const blob = new Blob([[columns.join(","), ...rows].join("\r\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "mv-v2-reference-outcomes.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export function PerformanceWorkspace() {
  const [performance, setPerformance] = useState<Performance | null>(null);
  const [outcomes, setOutcomes] = useState<Outcome[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [summaryResponse, outcomesResponse] = await Promise.all([
        fetch("/api/performance", { cache: "no-store" }),
        fetch("/api/performance/outcomes?limit=500", { cache: "no-store" }),
      ]);
      if (summaryResponse.status === 401 || outcomesResponse.status === 401)
        location.assign("/login");
      if (!summaryResponse.ok || !outcomesResponse.ok)
        throw new Error("Performance analytics are temporarily unavailable");
      const summary = (await summaryResponse.json()) as Performance;
      const outcomeData = (await outcomesResponse.json()) as {
        outcomes: Outcome[];
      };
      setPerformance(summary);
      setOutcomes(outcomeData.outcomes);
      setError("");
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Performance analytics are unavailable",
      );
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 30_000);
    return () => clearInterval(timer);
  }, [load]);

  if (!performance) {
    return (
      <section className="panel performance-empty">
        <Activity size={28} />
        <h2>{busy ? "Loading V2 performance…" : "Performance unavailable"}</h2>
        <p>{error || "Waiting for observational analytics."}</p>
        <button className="secondary-button" onClick={() => void load()}>
          <RefreshCw size={15} /> Retry
        </button>
      </section>
    );
  }

  const overall = performance.overall;
  return (
    <div className="performance-workspace">
      <section className="panel performance-intro">
        <div>
          <span className="eyebrow">V2 REFERENCE OUTCOME ANALYTICS</span>
          <h2>{performance.strategy}</h2>
          <p>
            Observational measurements only. These are published reference-plan
            outcomes, not exchange fills, realized P&amp;L or account returns.
          </p>
        </div>
        <div className="performance-actions">
          <button
            className="secondary-button"
            disabled={busy}
            onClick={() => void load()}
          >
            <RefreshCw size={15} /> {busy ? "Refreshing…" : "Refresh"}
          </button>
          <button
            className="secondary-button"
            disabled={!outcomes.length}
            onClick={() => downloadCsv(outcomes)}
          >
            <Download size={15} /> Export outcomes
          </button>
        </div>
      </section>

      <div className="summary-grid performance-summary">
        <div className="summary-card">
          <span className="summary-icon"><Activity size={20} /></span>
          <div>
            <span>V2 signals observed</span>
            <strong>{overall.signals}<small>{overall.resolved} resolved</small></strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon"><ShieldCheck size={20} /></span>
          <div>
            <span>Conservative expectancy</span>
            <strong>{rValue(overall.expectancy_r)}<small>reference R · resolved only</small></strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon"><Activity size={20} /></span>
          <div>
            <span>+1R before -1R</span>
            <strong>{percent(overall.one_r_before_stop_rate)}<small>{overall.one_r_before_stop} observed signals</small></strong>
          </div>
        </div>
        <div className="summary-card">
          <span className="summary-icon"><Activity size={20} /></span>
          <div>
            <span>Next formal review</span>
            <strong>{performance.next_review_milestone ?? "300+"}<small>published V2 signals</small></strong>
          </div>
        </div>
      </div>

      <section className="panel performance-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">SETUP × DIRECTION</span>
            <h2>Four-engine performance matrix</h2>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Setup</th><th>Direction</th><th>Signals</th><th>Resolved</th>
                <th>Target rate</th><th>Expectancy</th><th>Profit factor</th>
                <th>+1R first</th><th>+2R first</th><th>Avg MFE</th><th>Avg MAE</th>
              </tr>
            </thead>
            <tbody>
              {performance.cohorts.map((row) => (
                <tr key={`${row.setup_type}-${row.direction}`}>
                  <td>{setupLabel(row.setup_type)}</td>
                  <td className={row.direction === "long" ? "positive" : "negative"}>{row.direction}</td>
                  <td>{row.signals}</td><td>{row.resolved}</td>
                  <td>{percent(row.target_rate)}</td><td>{rValue(row.expectancy_r)}</td>
                  <td>{row.profit_factor == null ? "—" : Number(row.profit_factor).toFixed(2)}</td>
                  <td>{percent(row.one_r_before_stop_rate)}</td>
                  <td>{percent(row.two_r_before_stop_rate)}</td>
                  <td>{rValue(row.average_mfe_r)}</td><td>{rValue(row.average_mae_r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel performance-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">MARKET BREAKDOWN</span>
            <h2>Per-coin reference performance</h2>
          </div>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Market</th><th>Signals</th><th>Resolved</th><th>Target rate</th>
                <th>Expectancy</th><th>Profit factor</th><th>+1R first</th>
                <th>+2R first</th><th>Avg MFE</th><th>Avg MAE</th>
              </tr>
            </thead>
            <tbody>
              {performance.by_symbol.length ? performance.by_symbol.map((row) => (
                <tr key={row.symbol}>
                  <td><strong className="table-symbol">{row.symbol.replace("USDT", "")}<span>/ USDT</span></strong></td>
                  <td>{row.signals}</td><td>{row.resolved}</td><td>{percent(row.target_rate)}</td>
                  <td>{rValue(row.expectancy_r)}</td>
                  <td>{row.profit_factor == null ? "—" : Number(row.profit_factor).toFixed(2)}</td>
                  <td>{percent(row.one_r_before_stop_rate)}</td>
                  <td>{percent(row.two_r_before_stop_rate)}</td>
                  <td>{rValue(row.average_mfe_r)}</td><td>{rValue(row.average_mae_r)}</td>
                </tr>
              )) : (
                <tr><td colSpan={10}>No V2 signals have been published yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <div className="performance-two-column">
        <section className="panel performance-panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">DECISION BLOCKERS</span>
              <h2>Why opportunities were rejected</h2>
            </div>
          </div>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Reason</th><th>Decisions</th></tr></thead>
              <tbody>
                {performance.decision_blockers.slice(0, 15).map((row) => (
                  <tr key={row.reason}><td>{reasonLabel(row.reason)}</td><td>{row.count}</td></tr>
                ))}
                {!performance.decision_blockers.length && (
                  <tr><td colSpan={2}>No post-baseline decisions yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="panel performance-panel">
          <div className="panel-head">
            <div>
              <span className="eyebrow">MISSED-MOVE DIAGNOSTIC</span>
              <h2>Six-hour movement after NO_SETUP</h2>
            </div>
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Reason</th><th>Windows</th><th>Avg up</th><th>Avg down</th><th>≥2 ATR up/down</th></tr>
              </thead>
              <tbody>
                {performance.missed_opportunities_6h.slice(0, 15).map((row) => (
                  <tr key={row.reason}>
                    <td>{reasonLabel(row.reason)}</td><td>{row.decisions}</td>
                    <td>{Number(row.average_max_up_atr).toFixed(2)} ATR</td>
                    <td>{Number(row.average_max_down_atr).toFixed(2)} ATR</td>
                    <td>{row.moves_up_ge_2atr} / {row.moves_down_ge_2atr}</td>
                  </tr>
                ))}
                {!performance.missed_opportunities_6h.length && (
                  <tr><td colSpan={5}>No completed six-hour windows yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel performance-panel">
        <div className="panel-head">
          <div>
            <span className="eyebrow">REFERENCE OUTCOME JOURNAL</span>
            <h2>Recent V2 outcome observations</h2>
          </div>
          <span className="tag">{outcomes.length} loaded</span>
        </div>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Market</th><th>Setup</th><th>Direction</th><th>Published</th>
                <th>Status</th><th>Reference R</th><th>MFE</th><th>MAE</th>
                <th>+1R first</th><th>+2R first</th>
              </tr>
            </thead>
            <tbody>
              {outcomes.map((row) => (
                <tr key={row.signal_id}>
                  <td><strong className="table-symbol">{row.symbol.replace("USDT", "")}<span>/ USDT</span></strong></td>
                  <td>{setupLabel(row.setup_type)} · {row.trend_regime}</td>
                  <td className={row.direction === "long" ? "positive" : "negative"}>{row.direction}</td>
                  <td>{formatIST(row.published_at)}</td>
                  <td>{row.status.replaceAll("_", " ")}</td>
                  <td>{rValue(row.conservative_r)}</td>
                  <td>{rValue(row.mfe_r)}</td><td>{rValue(row.mae_r)}</td>
                  <td>{row.one_r_before_stop ? "Yes" : "No"}</td>
                  <td>{row.two_r_before_stop ? "Yes" : "No"}</td>
                </tr>
              ))}
              {!outcomes.length && (
                <tr><td colSpan={10}>No V2 published signals to analyze yet.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="performance-method">
        <strong>Measurement contract</strong>
        <p>{performance.minute_observation}</p>
        <p>{performance.ambiguous_policy}</p>
        <p>
          Six-hour NO_SETUP diagnostics measure future completed-candle movement
          in ATR units only. They are diagnostic evidence, not hypothetical
          entries or profit claims.
        </p>
      </section>

      {error && <p className="signal-alert">{error}</p>}
    </div>
  );
}
