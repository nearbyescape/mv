"use client";
import { formatIST } from "@/lib/time";
import { useEffect, useState } from "react";
import { Activity } from "lucide-react";
type Sleeve = {
  symbol: string;
  policy: string;
  cursor: number;
  closed_trades: number;
  last_hourly_equity: string;
  net_pnl_closed: string;
  mean_r_closed: string | null;
  position: unknown;
  pending: boolean;
  fees_closed: string;
  funding_closed: string;
};
type Run = {
  id: string;
  state: string;
  heartbeat: number;
  error: string | null;
  start: number;
  end_exclusive: number;
  observed_minutes: number;
  sleeves: Sleeve[];
  assessment: string;
  filter_report_id: string;
  spec: {
    execution: string;
    evaluation: string;
    costs: { fee_bps: string; spread_bps: string; slippage_bps: string };
  };
};
const labels: Record<string, string> = {
  baseline: "Original baseline",
  slope: "EMA50 slope ≥ 0.05 ATR",
  separation: "EMA separation ≥ 0.5 ATR",
};
const date = formatIST;
const money = (value: string) =>
  Number(value).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export function ForwardPaperWorkspace() {
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [previous, setPrevious] = useState<
    { id: string; state: string; error: string; observed_minutes: number }[]
  >([]);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/paper", {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Forward paper API unavailable");
        const feed = await response.json();
        setRun(feed.run);
        setPrevious(feed.previous_samples || []);
        setError(null);
      } catch (e) {
        if (!controller.signal.aborted)
          setError(
            e instanceof Error ? e.message : "Forward journal unavailable",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, []);
  if (!run)
    return (
      <section className="panel study-empty">
        <Activity size={30} />
        <h2>
          {loading
            ? "Loading forward paper journal"
            : error
              ? "Forward paper unavailable"
              : "No forward sample registered"}
        </h2>
        <p role={error ? "alert" : undefined}>
          {error ||
            "A new sample starts flat with frozen policies and newly observed public data."}
        </p>
      </section>
    );
  return (
    <div className="exit-study-workspace">
      <section className="research-notice paper-notice">
        <Activity size={23} />
        <div>
          <strong>Forward shadow paper validation</strong>
          <p>
            New observations · three frozen policies · modeled fills and costs.
            Paper results do not represent exchange execution.
          </p>
        </div>
        <span className="tag">{error ? "API unavailable" : run.state}</span>
      </section>
      {error && (
        <p role="alert">
          {error}. Displayed journal is the last successful response.
        </p>
      )}
      {run.error && (
        <p role="alert" className="research-notice">
          {run.error}. Retained open positions remain unresolved while
          observations are blocked.
        </p>
      )}
      {previous.map((sample) => (
        <section className="research-notice" key={sample.id}>
          <div>
            <strong>Earlier sample · {sample.state}</strong>
            <p>
              {sample.observed_minutes} observed symbol-minutes. {sample.error}.
              Preserved separately; excluded from this sample.
            </p>
            <details>
              <summary>Earlier sample identity</summary>
              <code>{sample.id}</code>
            </details>
          </div>
        </section>
      ))}
      <div className="research-metrics study-metrics">
        <div className="panel research-metric">
          <span>Observed symbol-minutes</span>
          <strong>{run.observed_minutes}</strong>
          <small>Not independent trades</small>
        </div>
        <div className="panel research-metric">
          <span>Closed paper trades</span>
          <strong>
            {run.sleeves.reduce((n, s) => n + s.closed_trades, 0)}
          </strong>
          <small>Overlapping policies</small>
        </div>
        <div className="panel research-metric">
          <span>Start</span>
          <strong className="paper-time">{date(run.start)}</strong>
          <small>Flat, no old entries</small>
        </div>
        <div className="panel research-metric">
          <span>Observer heartbeat</span>
          <strong className="paper-time">{date(run.heartbeat)}</strong>
          <small>{run.state}</small>
        </div>
      </div>
      <section className="panel study-comparison-panel">
        <div className="study-section-head">
          <div>
            <span className="eyebrow">
              Independent sleeves · 5,000 USDT each
            </span>
            <h2>Forward policy journal</h2>
            <p>
              Equity is the last completed hourly contract-price mark. Closed
              P&amp;L omits unresolved positions.
            </p>
          </div>
        </div>
        <div
          className="study-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Forward paper sleeves"
        >
          <table className="study-comparison">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Coin</th>
                <th>Position</th>
                <th>Closed trades</th>
                <th>Hourly equity</th>
                <th>Closed net P&amp;L</th>
                <th>Closed mean R</th>
                <th>Fees / funding</th>
              </tr>
            </thead>
            <tbody>
              {run.sleeves.map((s) => (
                <tr key={`${s.policy}-${s.symbol}`}>
                  <td>{labels[s.policy]}</td>
                  <td>{s.symbol}</td>
                  <td>
                    {s.position
                      ? "Open paper position"
                      : s.pending
                        ? "Pending model entry"
                        : "Flat"}
                  </td>
                  <td>{s.closed_trades}</td>
                  <td>{money(s.last_hourly_equity)}</td>
                  <td>{money(s.net_pnl_closed)}</td>
                  <td>
                    {s.mean_r_closed === null
                      ? "—"
                      : Number(s.mean_r_closed).toFixed(3)}
                  </td>
                  <td>
                    {money(s.fees_closed)} / {money(s.funding_closed)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel research-method">
        <h2>Observation & assessment gate</h2>
        <p>{run.assessment}</p>
        <p>{run.spec.evaluation}</p>
        <p>{run.spec.execution}</p>
        <p>
          Assumptions: {run.spec.costs.fee_bps} bps fee per side,{" "}
          {run.spec.costs.spread_bps} bps full spread,{" "}
          {run.spec.costs.slippage_bps} bps adverse slippage per side.
          Fractional, capital-capped quantities; no leverage or liquidation
          model.
        </p>
        <p>
          Late observations, changed source evidence or missing due funding
          freeze the sample. Frozen positions retain their recorded state; no
          retroactive closing price is invented. The local observer must remain
          running.
        </p>
        <details>
          <summary>Frozen sample identity</summary>
          <p>
            Sample <code>{run.id}</code>
          </p>
          <p>
            Filter report <code>{run.filter_report_id}</code>
          </p>
          <p>Window ends {date(run.end_exclusive)}</p>
          <p>
            Live seeded indicator history differs from the historical dataset
            origin.
          </p>
        </details>
      </section>
    </div>
  );
}
