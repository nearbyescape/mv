"use client";
import { formatISTDate } from "@/lib/time";
import { useEffect, useState } from "react";
import {
  Download,
  FlaskConical,
  ShieldCheck,
  Database,
  ArrowRight,
} from "lucide-react";
import type { ResearchGroup, ResearchReport } from "@/lib/research-types";
import { ExitStudyWorkspace } from "./exit-study-workspace";
import { FilterStudyWorkspace } from "./filter-study-workspace";

const labels: Record<string, string> = {
  development: "Development · 2024",
  validation: "Validation · Jan–Jun 2025",
  final_evaluation: "Final evaluation · Jul–Dec 2025",
  baseline: "Baseline costs",
  higher_cost: "Higher costs",
  delayed_entry: "Delayed entry",
};
const label = (value: string) => labels[value] || value.replaceAll("_", " ");
const percent = (value: string | null) =>
  value === null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
const decimal = (value: string | null, digits = 2) =>
  value === null
    ? "—"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const date = formatISTDate;

function EquityChart({ group }: { group: ResearchGroup }) {
  const [hover, setHover] = useState<number | null>(null);
  const points = group.daily_curve;
  if (!points.length) return <p>Daily curve unavailable.</p>;
  const values = points.map((point) => Number(point.equity));
  const initial = Number(group.metrics.initial_capital);
  const minimum = Math.min(...values, initial),
    maximum = Math.max(...values, initial);
  const low = minimum === maximum ? minimum * 0.99 : minimum;
  const high = minimum === maximum ? maximum * 1.01 : maximum;
  const range = Math.max(high - low, 1);
  const x = (index: number) =>
    65 + (index / Math.max(points.length - 1, 1)) * 485;
  const y = (value: number) => 25 + ((high - value) / range) * 185;
  const path = values
    .map(
      (value, index) =>
        `${index ? "L" : "M"}${x(index).toFixed(2)},${y(value).toFixed(2)}`,
    )
    .join(" ");
  const index =
    hover === null ? points.length - 1 : Math.min(hover, points.length - 1);
  return (
    <figure className="research-equity">
      <figcaption>
        <span>Portfolio equity · daily marks</span>
        <strong>
          {date(points[index].time)} <b>{decimal(points[index].equity)} USDT</b>
        </strong>
      </figcaption>
      <svg
        viewBox="0 0 600 250"
        role="img"
        aria-label={`Simulated portfolio equity for ${label(group.partition)}, ${label(group.scenario)}; ending equity ${decimal(group.metrics.ending_equity)} USDT`}
        onPointerMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          setHover(
            Math.max(
              0,
              Math.min(
                points.length - 1,
                Math.round(
                  ((((event.clientX - rect.left) / rect.width) * 600 - 65) /
                    485) *
                    (points.length - 1),
                ),
              ),
            ),
          );
        }}
        onPointerLeave={() => setHover(null)}
      >
        {[high, low + range / 2, low].map((value, index) => (
          <g key={index}>
            <line
              x1="65"
              x2="550"
              y1={y(value)}
              y2={y(value)}
              className="research-grid"
            />
            <text x="55" y={y(value) + 4} textAnchor="end">
              {Math.round(value).toLocaleString("en-US")}
            </text>
          </g>
        ))}
        <line
          x1="65"
          x2="550"
          y1={y(initial)}
          y2={y(initial)}
          className="research-baseline"
        />
        <path d={path} fill="none" className="research-line" />
        {hover !== null && (
          <g>
            <line
              x1={x(index)}
              x2={x(index)}
              y1="20"
              y2="215"
              className="research-baseline"
            />
            <circle
              cx={x(index)}
              cy={y(values[index])}
              r="4"
              className="research-point"
            />
          </g>
        )}
        <text x="65" y="239">
          {date(points[0].time)}
        </text>
        <text x="550" y="239" textAnchor="end">
          {date(points.at(-1)!.time)} · IST
        </text>
      </svg>
      <p>
        Hourly marks drive drawdown statistics. Each partition starts with fresh
        capital and flat positions.
      </p>
    </figure>
  );
}

export function ResearchWorkspace() {
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [partition, setPartition] = useState("final_evaluation");
  const [scenario, setScenario] = useState("baseline");
  const [view, setView] = useState("historical");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/research", {
          signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok)
          throw new Error(
            data.detail || data.error || "Research report unavailable",
          );
        if (!controller.signal.aborted)
          setReport(data.available ? data.report : null);
      } catch (failure) {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Research report unavailable",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, []);
  if (loading || !report)
    return (
      <section className="panel research-empty">
        <FlaskConical size={32} />
        <h2>
          {loading
            ? "Loading research report"
            : error
              ? "Research report unavailable"
              : "No backtest report yet"}
        </h2>
        <p role={error ? "alert" : undefined}>
          {error ||
            "Completed, verified historical experiments appear here. Live signals and Demo examples are separate."}
        </p>
      </section>
    );
  const group = report.groups.find(
    (row) => row.partition === partition && row.scenario === scenario,
  );
  if (!group)
    return (
      <p role="alert">This report does not include the selected experiment.</p>
    );
  const costs = report.research.scenarios.find((row) => row.id === scenario)!;
  const m = group.metrics;
  return (
    <div className="research-workspace">
      <nav className="research-view-switch" aria-label="Research views">
        <button
          aria-pressed={view === "historical"}
          onClick={() => setView("historical")}
        >
          Historical results
        </button>
        <button
          aria-pressed={view === "diagnostics"}
          onClick={() => setView("diagnostics")}
        >
          Trade diagnostics & exits
        </button>
        <button
          aria-pressed={view === "filters"}
          onClick={() => setView("filters")}
        >
          Entry filters
        </button>
      </nav>
      {view === "diagnostics" ? (
        <ExitStudyWorkspace baselineId={report.id} />
      ) : view === "filters" ? (
        <FilterStudyWorkspace baselineId={report.id} />
      ) : (
        <>
          <section className="research-notice">
            <FlaskConical size={22} />
            <div>
              <strong>Historical simulation · research only</strong>
              <p>
                Performance depends on modeled execution and the recorded source
                policy. A positive partition does not establish a reliable
                trading edge.
              </p>
            </div>
            <span className="tag">{report.strategy}</span>
          </section>
          <div className="research-toolbar">
            <div className="research-selects">
              <label>
                Evaluation period
                <select
                  aria-label="Research period"
                  value={partition}
                  onChange={(event) => setPartition(event.target.value)}
                >
                  {report.research.partitions.map((row) => (
                    <option key={row.name} value={row.name}>
                      {label(row.name)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Execution scenario
                <select
                  aria-label="Research scenario"
                  value={scenario}
                  onChange={(event) => setScenario(event.target.value)}
                >
                  {report.research.scenarios.map((row) => (
                    <option key={row.id} value={row.id}>
                      {label(row.id)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <a
              className="secondary-button"
              href="/api/research?file=report.json"
              download
            >
              <Download size={15} />
              Download report
            </a>
          </div>
          <div className="research-metrics">
            {[
              {
                title: "Net portfolio return",
                value: percent(m.return),
                note: `${decimal(m.net_pnl)} USDT · after costs`,
                signed: Number(m.return),
              },
              {
                title: "Maximum drawdown",
                value: percent(m.max_drawdown),
                note: "Hourly equity marks",
              },
              {
                title: "Closed simulated trades",
                value: m.trades.toLocaleString(),
                note: `${percent(m.win_rate)} net winning trades`,
              },
              {
                title: "Profit factor",
                value: decimal(m.profit_factor),
                note: `${decimal(m.expectancy_r, 3)} R · mean net expectancy`,
              },
            ].map((row) => (
              <section className="panel research-metric" key={row.title}>
                <span>{row.title}</span>
                <strong
                  className={
                    row.signed === undefined
                      ? ""
                      : row.signed < 0
                        ? "negative"
                        : "positive"
                  }
                >
                  {row.value}
                </strong>
                <small>{row.note}</small>
              </section>
            ))}
          </div>
          <div className="research-main-grid">
            <section className="panel">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">CAPITAL-NORMALIZED REPLAY</span>
                  <h2>{label(partition)}</h2>
                </div>
                <span className="tag">
                  {report.research.symbols.join(" + ")}
                </span>
              </div>
              <EquityChart key={`${partition}-${scenario}`} group={group} />
            </section>
            <section className="panel research-costs">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">EXPLICIT ASSUMPTIONS</span>
                  <h2>{label(scenario)}</h2>
                </div>
              </div>
              <dl>
                <div>
                  <dt>Taker fee · each side</dt>
                  <dd>{costs.fee_bps} bps</dd>
                </div>
                <div>
                  <dt>Full spread</dt>
                  <dd>{costs.spread_bps} bps</dd>
                </div>
                <div>
                  <dt>Adverse slippage · each fill</dt>
                  <dd>{costs.slippage_bps} bps</dd>
                </div>
                <div>
                  <dt>Publication availability</dt>
                  <dd>{costs.latency_ms / 1000}s modeled</dd>
                </div>
                <div>
                  <dt>Paid fees</dt>
                  <dd>{decimal(m.fees)} USDT</dd>
                </div>
                <div>
                  <dt>Funding contribution</dt>
                  <dd>{decimal(m.funding_pnl)} USDT</dd>
                </div>
              </dl>
              <p>
                Entry uses the next eligible minute open. The source candle
                close is never an assured fill. Funding uses actual rates, times
                and associated mark prices.
              </p>
            </section>
          </div>
          <section className="panel research-comparison">
            <div className="panel-head">
              <div>
                <span className="eyebrow">ALL REGISTERED EXPERIMENTS</span>
                <h2>Chronological results</h2>
              </div>
              <span className="tag">No winner selected</span>
            </div>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Historical experiment comparison"
            >
              <table>
                <thead>
                  <tr>
                    <th>Partition / scenario</th>
                    <th>Net return</th>
                    <th>Drawdown</th>
                    <th>Trades</th>
                    <th>Profit factor</th>
                    <th>Cash</th>
                    <th>Passive long</th>
                    <th>
                      <span className="sr-only">Inspect experiment</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {report.groups.map((row) => (
                    <tr
                      key={`${row.partition}-${row.scenario}`}
                      className={row === group ? "research-selected-row" : ""}
                    >
                      <td>
                        <strong>{label(row.partition)}</strong>
                        <small>{label(row.scenario)}</small>
                      </td>
                      <td
                        className={
                          Number(row.metrics.return) < 0
                            ? "negative"
                            : "positive"
                        }
                      >
                        {percent(row.metrics.return)}
                      </td>
                      <td>{percent(row.metrics.max_drawdown)}</td>
                      <td>{row.metrics.trades}</td>
                      <td>{decimal(row.metrics.profit_factor)}</td>
                      <td>{percent(row.benchmarks.cash_return)}</td>
                      <td>{percent(row.benchmarks.passive_long_return)}</td>
                      <td>
                        <button
                          className="icon-button"
                          aria-label={`Inspect ${label(row.partition)}, ${label(row.scenario)}`}
                          onClick={() => {
                            setPartition(row.partition);
                            setScenario(row.scenario);
                          }}
                        >
                          <ArrowRight size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="research-footnote">
              Passive long is a costed futures exposure including actual
              funding. Experiments restart capital independently; these rows are
              not additive account returns.
            </p>
          </section>
          <div className="research-detail-grid">
            <section className="panel research-breakdown">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">PER-COIN SLEEVES</span>
                  <h2>Exposure and uncertainty</h2>
                </div>
              </div>
              {group.symbols.map((row) => (
                <div className="research-symbol" key={row.symbol}>
                  <strong>{row.symbol}</strong>
                  <span>{row.trades} trades</span>
                  <b
                    className={Number(row.return) < 0 ? "negative" : "positive"}
                  >
                    {percent(row.return)}
                  </b>
                </div>
              ))}
              <dl>
                <div>
                  <dt>Time exposed</dt>
                  <dd>{percent(m.time_exposure)}</dd>
                </div>
                <div>
                  <dt>Average holding period</dt>
                  <dd>{decimal(m.average_holding_hours)}h</dd>
                </div>
                <div>
                  <dt>Ambiguous stop-first exits</dt>
                  <dd>{m.ambiguous_stop_first}</dd>
                </div>
                <div>
                  <dt>Forced partition exits</dt>
                  <dd>{m.forced_partition_exits}</dd>
                </div>
                <div>
                  <dt>95% monthly mean interval</dt>
                  <dd>
                    {group.uncertainty.lower === null
                      ? "Insufficient sample"
                      : `${percent(group.uncertainty.lower)} to ${percent(group.uncertainty.upper)}`}
                  </dd>
                </div>
              </dl>
              <p>
                Calendar block bootstrap · {group.uncertainty.months} months.
                This small-sample interval is exploratory. Daily chart rendering
                never calculates financial results.
              </p>
            </section>
            <section className="panel research-provenance">
              <div className="panel-head">
                <div>
                  <span className="eyebrow">REPRODUCIBLE SOURCE RECORD</span>
                  <h2>Dataset and execution limits</h2>
                </div>
                <Database size={18} />
              </div>
              <p>
                <b>{report.provenance.archives} checksum-pinned archives</b> ·{" "}
                {report.provenance.source_audit.rows.toLocaleString()}{" "}
                one-minute candles ·{" "}
                {Object.values(report.provenance.funding_events)
                  .reduce((sum, value) => sum + value, 0)
                  .toLocaleString()}{" "}
                actual funding events.
              </p>
              <p>
                {report.provenance.source_audit.native_discrepancies} native
                source discrepancies recorded. Completed UTC candles use
                validated minute aggregation. Current dated tick filters
                approximate historical rules.
              </p>
              <p>
                Warm-up origin: {report.research.history_start} · cutoff:{" "}
                {report.research.cutoff_exclusive} (exclusive). No trade crosses
                an evaluation partition.
              </p>
              <div className="research-export-links">
                <a href="/api/research?file=trades.csv" download>
                  <Download size={14} />
                  Trade CSV
                </a>
                <a href="/api/research?file=trades.jsonl" download>
                  <Download size={14} />
                  Full trade evidence
                </a>
                <a href="/api/research?file=dataset-manifest.json" download>
                  <Download size={14} />
                  Dataset manifest
                </a>
                <a href="/api/research?file=source-audit.json" download>
                  <Download size={14} />
                  Source audit
                </a>
              </div>
              <details>
                <summary>
                  <ShieldCheck size={14} />
                  Report identity and limitations
                </summary>
                <p>
                  Report ID <code>{report.id}</code>
                </p>
                <p>
                  Report SHA-256 <code>{report.report_hash}</code>
                </p>
                <p>
                  Dataset SHA-256 <code>{report.dataset_hash}</code>
                </p>
                <p>
                  Code SHA-256 <code>{report.code_hash}</code>
                </p>
                <ul>
                  {Array.from(new Set(report.limitations)).map((value) => (
                    <li key={value}>{value}</li>
                  ))}
                </ul>
              </details>
            </section>
          </div>
        </>
      )}
    </div>
  );
}
