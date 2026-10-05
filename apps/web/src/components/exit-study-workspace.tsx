"use client";
import { useEffect, useState } from "react";
import { Activity, Download, ShieldCheck } from "lucide-react";
import type { ExitStudyReport } from "@/lib/exit-study-types";

const policyLabels: Record<string, string> = {
  baseline: "Baseline · stop / target / EMA50",
  stop_target: "Stop / target · EMA50 exit disabled",
  stop_ema50: "Stop / EMA50 · target disabled",
};
const periodLabels: Record<string, string> = {
  development: "2024 · previously viewed",
  validation: "Jan–Jun 2025 · previously viewed",
  final_evaluation: "Jul–Dec 2025 · previously viewed",
};
const scenarioLabels: Record<string, string> = {
  baseline: "Baseline costs",
  higher_cost: "Higher costs",
  delayed_entry: "Delayed entry",
};
const dimensionLabels: Record<string, string> = {
  symbol: "Coin",
  direction: "Direction",
  exit_reason: "Exit reason (outcome)",
  atr_fraction: "ATR volatility at entry",
  ema_gap_atr: "EMA separation at entry",
  aligned_ema50_slope_atr: "EMA50 slope at entry",
};
const exitLabels: Record<string, string> = {
  ema50_exit: "EMA50 exit",
  target: "Target",
  stop: "Stop",
  stop_gap: "Adverse stop gap",
  target_gap: "Target gap",
  partition_end: "Forced period end",
};
const format = (value: string | null, digits = 2) =>
  value === null
    ? "—"
    : Number(value).toLocaleString("en-US", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
const percent = (value: string | null) =>
  value === null ? "—" : `${format(String(Number(value) * 100))}%`;
const tone = (value: string | null) =>
  value !== null && Number(value) < 0
    ? "negative"
    : value !== null && Number(value) > 0
      ? "positive"
      : "";

function cohortLabel(
  dimension: string,
  cohort: string,
  report: ExitStudyReport,
) {
  const edges = report.study.diagnostics[`${dimension}_edges`];
  if (!edges) return exitLabels[cohort] || cohort;
  const index = Number(cohort);
  const label = (value: string) =>
    dimension === "atr_fraction" ? percent(value) : `${format(value)} ATR`;
  return index === 0
    ? `< ${label(edges[0])}`
    : index === edges.length
      ? `≥ ${label(edges.at(-1)!)}`
      : `${label(edges[index - 1])} to < ${label(edges[index])}`;
}

export function ExitStudyWorkspace({ baselineId }: { baselineId: string }) {
  const [report, setReport] = useState<ExitStudyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState("development");
  const [scenario, setScenario] = useState("baseline");
  const [policy, setPolicy] = useState("baseline");
  const [dimension, setDimension] = useState("exit_reason");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/research/study", {
          signal: controller.signal,
        });
        const data = await response.json();
        if (!response.ok)
          throw new Error(
            data.detail || data.error || "Exit study unavailable",
          );
        if (data.available && data.report.baseline_report_id !== baselineId)
          throw new Error(
            "This exit study references a different baseline. Regenerate the registered comparison before using it here.",
          );
        if (!controller.signal.aborted)
          setReport(data.available ? data.report : null);
      } catch (failure) {
        if (!controller.signal.aborted)
          setError(
            failure instanceof Error
              ? failure.message
              : "Exit study unavailable",
          );
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [baselineId]);
  if (loading || !report)
    return (
      <section className="panel study-empty">
        <Activity size={30} />
        <h2>
          {loading
            ? "Loading trade diagnostics"
            : error
              ? "Exit study unavailable"
              : "No exit study yet"}
        </h2>
        <p role={error ? "alert" : undefined}>
          {error ||
            "Registered comparisons appear after a verified offline replay. No illustrative performance replaces missing results."}
        </p>
      </section>
    );
  const group = report.diagnostics.find(
    (g) =>
      g.partition === period &&
      g.scenario === scenario &&
      g.exit_policy === policy,
  );
  if (!group)
    return <p role="alert">The selected diagnostic experiment is missing.</p>;
  const selected = report.groups.filter(
    (g) => g.partition === period && g.scenario === scenario,
  );
  const summary = group.summary;
  return (
    <div className="exit-study-workspace">
      <section className="research-notice study-notice">
        <Activity size={23} />
        <div>
          <strong>Trade diagnostics & controlled exit comparisons</strong>
          <p>
            All periods were previously viewed. Cohorts describe trades; they
            are not validated entry filters. No policy has been promoted to live
            signals.
          </p>
        </div>
        <span className="tag">{report.study.id}</span>
      </section>
      <div className="study-control-proof">
        <ShieldCheck size={17} />
        <span>{report.baseline_control_parity}</span>
        <b>{report.groups.length} registered experiments</b>
      </div>
      <div className="research-toolbar">
        <div className="research-selects">
          <label>
            Previously viewed period
            <select
              aria-label="Diagnostic period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              {report.research.partitions.map((p) => (
                <option key={p.name} value={p.name}>
                  {periodLabels[p.name] || p.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Execution scenario
            <select
              aria-label="Diagnostic scenario"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              {report.research.scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {scenarioLabels[s.id] || s.id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <a
          className="secondary-button"
          href="/api/research/study?file=report.json"
          download
        >
          <Download size={15} />
          Download exit study
        </a>
      </div>
      <section className="panel study-comparison-panel">
        <div className="study-section-head">
          <div>
            <span className="eyebrow">SAME ENTRY RULES · CHANGED EXITS</span>
            <h2>Compare full exit policies</h2>
          </div>
          <span className="tag">No winner selected</span>
        </div>
        <div
          className="study-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Exit policy comparison"
        >
          <table className="study-comparison">
            <thead>
              <tr>
                <th>Exit policy</th>
                <th>Net return</th>
                <th>Δ vs baseline</th>
                <th>Drawdown</th>
                <th>Trades</th>
                <th>Mean net R</th>
                <th>Profit factor</th>
              </tr>
            </thead>
            <tbody>
              {selected.map((g) => (
                <tr
                  key={g.exit_policy}
                  className={g.exit_policy === policy ? "study-selected" : ""}
                >
                  <td>
                    <button
                      onClick={() => setPolicy(g.exit_policy)}
                      aria-pressed={g.exit_policy === policy}
                    >
                      {policyLabels[g.exit_policy]}
                      <small>{g.strategy}</small>
                    </button>
                  </td>
                  <td className={tone(g.metrics.return)}>
                    {percent(g.metrics.return)}
                  </td>
                  <td>
                    {format(String(Number(g.return_delta_vs_baseline) * 100))}{" "}
                    pp
                  </td>
                  <td>{percent(g.metrics.max_drawdown)}</td>
                  <td>{g.metrics.trades}</td>
                  <td className={tone(g.metrics.expectancy_r)}>
                    {format(g.metrics.expectancy_r, 3)}
                  </td>
                  <td>{format(g.metrics.profit_factor, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="study-caption">
          Changed holding times alter later signal availability and cash sizes.
          These are complete policy replays, not isolated replacements of each
          baseline exit. Δ is percentage points for this same period and cost
          scenario.
        </p>
      </section>
      <div className="research-toolbar study-diagnostic-toolbar">
        <div className="research-selects">
          <label>
            Diagnostic policy
            <select
              aria-label="Diagnostic policy"
              value={policy}
              onChange={(e) => setPolicy(e.target.value)}
            >
              {report.study.policies.map((p) => (
                <option key={p.id} value={p.id}>
                  {policyLabels[p.id]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Group completed trades by
            <select
              aria-label="Diagnostic grouping"
              value={dimension}
              onChange={(e) => setDimension(e.target.value)}
            >
              {Object.entries(dimensionLabels).map(([key, name]) => (
                <option key={key} value={key}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="research-metrics study-metrics">
        {[
          [
            "Completed trades",
            String(summary.trades),
            "Selected policy / period / costs",
          ],
          [
            "Mean net expectancy",
            `${format(summary.expectancy_r, 3)} R`,
            "Includes both fees and actual funding",
          ],
          [
            "Observed favorable move ≥ 1R",
            String(summary.observed_at_least_1r),
            "Lower-bound count · exit minute censored",
          ],
          [
            "Losing trades observed ≥ 1R",
            String(summary.losers_observed_at_least_1r),
            "Diagnostic only · no achievable-fill claim",
          ],
        ].map(([title, value, note]) => (
          <section className="panel research-metric" key={title}>
            <span>{title}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </section>
        ))}
      </div>
      <section className="panel study-cohort-panel">
        <div className="study-section-head">
          <div>
            <span className="eyebrow">
              DESCRIPTIVE COHORTS · NO SIGNIFICANCE CLAIM
            </span>
            <h2>{dimensionLabels[dimension]}</h2>
          </div>
        </div>
        <div
          className="study-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Trade diagnostic cohorts"
        >
          <table className="study-cohorts">
            <thead>
              <tr>
                <th>Cohort</th>
                <th>Trades</th>
                <th>Net P&L · USDT</th>
                <th>Mean net R</th>
                <th>Win rate</th>
                <th>Fees · USDT</th>
                <th>Observed MFE · R</th>
                <th>Observed MAE · R</th>
              </tr>
            </thead>
            <tbody>
              {group.dimensions[dimension].map((row) => (
                <tr key={row.cohort}>
                  <td>{cohortLabel(dimension, row.cohort, report)}</td>
                  <td>{row.trades}</td>
                  <td className={tone(row.net_pnl)}>{format(row.net_pnl)}</td>
                  <td className={tone(row.expectancy_r)}>
                    {format(row.expectancy_r, 3)}
                  </td>
                  <td>{percent(row.win_rate)}</td>
                  <td>{format(row.fees)}</td>
                  <td>{format(row.average_mfe_r_observed, 3)}</td>
                  <td>{format(row.average_mae_r_observed, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {group.summary.trades === 0 && (
            <p className="study-caption">
              No completed trades for this experiment.
            </p>
          )}
        </div>
        <p className="study-caption">
          {dimension === "exit_reason"
            ? "Exit reason is a future outcome. Its cohorts cannot establish that removing an exit would improve performance."
            : "Entry features use only completed source and previous candles. Thresholds were registered before these cohort results, after the original overall results were viewed."}{" "}
          Sample counts matter; descriptive differences are hypotheses for new
          experiments. Excursions omit unknown exit-minute extremes.
        </p>
      </section>
      <div className="research-detail-grid study-detail-grid">
        <section className="panel">
          <span className="eyebrow">EVIDENCE BEFORE CHANGES</span>
          <h2>What these diagnostics can establish</h2>
          <p>
            Coin and direction identify concentration. ATR/close measures
            volatility; EMA gap/ATR measures separation; signed EMA50 change/ATR
            measures alignment with the trade direction. These are
            classifications, not new signal rules.
          </p>
          <p>{report.study.entry_parity}</p>
          <p>{report.study.excursions}</p>
        </section>
        <section className="panel">
          <span className="eyebrow">
            FROZEN STUDY · ORIGINAL BASELINE PRESERVED
          </span>
          <h2>Review and reproduce</h2>
          <p>{report.study.evaluation}</p>
          <div className="research-export-links">
            {[
              ["diagnostics.json", "Diagnostic JSON"],
              ["trades.csv", "Study trade CSV"],
              ["trades.jsonl", "Study full evidence"],
              ["source-audit.json", "Source audit"],
            ].map(([file, text]) => (
              <a key={file} href={`/api/research/study?file=${file}`} download>
                <Download size={14} />
                {text}
              </a>
            ))}
          </div>
          <details className="study-provenance">
            <summary>Study identity and limitations</summary>
            <p>
              Study ID <code>{report.id}</code>
            </p>
            <p>
              Report SHA-256 <code>{report.report_hash}</code>
            </p>
            <p>
              Original baseline <code>{report.baseline_report_id}</code>
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
      <details className="panel study-all-experiments">
        <summary>
          Inspect all {report.groups.length} registered experiments
        </summary>
        <div
          className="study-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="All exit study experiments"
        >
          <table>
            <thead>
              <tr>
                <th>Period / costs</th>
                <th>Exit policy</th>
                <th>Net return</th>
                <th>Drawdown</th>
                <th>Trades</th>
                <th>Mean net R</th>
              </tr>
            </thead>
            <tbody>
              {report.groups.map((g) => (
                <tr key={`${g.partition}:${g.scenario}:${g.exit_policy}`}>
                  <td>
                    {periodLabels[g.partition]}
                    <small>{scenarioLabels[g.scenario]}</small>
                  </td>
                  <td>{policyLabels[g.exit_policy]}</td>
                  <td className={tone(g.metrics.return)}>
                    {percent(g.metrics.return)}
                  </td>
                  <td>{percent(g.metrics.max_drawdown)}</td>
                  <td>{g.metrics.trades}</td>
                  <td>{format(g.metrics.expectancy_r, 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
