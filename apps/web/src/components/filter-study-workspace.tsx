"use client";
import { useEffect, useState } from "react";
import { Activity, Download, ShieldCheck } from "lucide-react";
import type { ResearchGroup, ResearchReport } from "@/lib/research-types";

type FilterReport = {
  id: string;
  baseline_report_id: string;
  baseline_control_parity: string;
  code_hash: string;
  dataset_hash: string;
  report_hash: string;
  assessment: string;
  limitations: string[];
  research: ResearchReport["research"];
  study: {
    id: string;
    policies: {
      id: string;
      strategy: string;
      feature: string | null;
      minimum: string | null;
    }[];
  };
  groups: (ResearchGroup & {
    entry_policy: string;
    return_delta_vs_baseline: string;
  })[];
};
const policies: Record<string, string> = {
  baseline: "Original baseline",
  slope: "EMA50 slope ≥ 0.05 ATR",
  separation: "EMA separation ≥ 0.5 ATR",
};
const periods: Record<string, string> = {
  development: "2024 · previously viewed",
  validation: "Jan–Jun 2025 · previously viewed",
  final_evaluation: "Jul–Dec 2025 · previously viewed",
};
const costs: Record<string, string> = {
  baseline: "Baseline costs",
  higher_cost: "Higher costs",
  delayed_entry: "Delayed entry",
};
const percent = (value: string) => `${(Number(value) * 100).toFixed(2)}%`;
const number = (value: string | null) =>
  value === null ? "—" : Number(value).toFixed(3);

export function FilterStudyWorkspace({ baselineId }: { baselineId: string }) {
  const [report, setReport] = useState<FilterReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState("development");
  const [scenario, setScenario] = useState("baseline");
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/research/filters", {
      signal: controller.signal,
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Filter study API unavailable");
        const feed = await response.json();
        if (feed.report && feed.report.baseline_report_id !== baselineId)
          throw new Error("Filter study does not match the original baseline");
        setReport(feed.report);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [baselineId]);
  if (!report)
    return (
      <section className="panel study-empty">
        <Activity size={30} />
        <h2>
          {loading
            ? "Loading entry filter research"
            : error
              ? "Filter study unavailable"
              : "No filter study yet"}
        </h2>
        <p role={error ? "alert" : undefined}>
          {error || "Results appear after a checksum-verified backend replay."}
        </p>
      </section>
    );
  const groups = report.groups.filter(
    (g) => g.partition === period && g.scenario === scenario,
  );
  return (
    <div className="exit-study-workspace">
      <section className="research-notice">
        <Activity size={23} />
        <div>
          <strong>Independent entry filter research</strong>
          <p>
            Fixed thresholds, original exits. All historical periods were
            previously viewed. No combined filter or live promotion.
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
              aria-label="Filter period"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
            >
              {report.research.partitions.map((p) => (
                <option key={p.name} value={p.name}>
                  {periods[p.name]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Execution scenario
            <select
              aria-label="Filter scenario"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
            >
              {report.research.scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {costs[s.id]}
                </option>
              ))}
            </select>
          </label>
        </div>
        <a
          className="secondary-button"
          href="/api/research/filters?file=report.json"
          download
        >
          <Download size={15} />
          Download filter study
        </a>
      </div>
      <section className="panel study-comparison-panel">
        <div className="study-section-head">
          <div>
            <span className="eyebrow">One change at a time</span>
            <h2>Entry policy comparison</h2>
            <p>
              Holding time and later entry eligibility can change; these are
              complete policy replays.
            </p>
          </div>
        </div>
        <div
          className="study-table-scroll"
          tabIndex={0}
          role="region"
          aria-label="Entry filter comparison"
        >
          <table className="study-comparison">
            <thead>
              <tr>
                <th>Policy</th>
                <th>Net return</th>
                <th>Change vs baseline</th>
                <th>Drawdown</th>
                <th>Trades</th>
                <th>Mean R</th>
                <th>Profit factor</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => (
                <tr key={g.entry_policy}>
                  <td>{policies[g.entry_policy]}</td>
                  <td
                    className={
                      Number(g.metrics.return) < 0 ? "negative" : "positive"
                    }
                  >
                    {percent(g.metrics.return)}
                  </td>
                  <td>
                    {(Number(g.return_delta_vs_baseline) * 100).toFixed(2)} pp
                  </td>
                  <td>{percent(g.metrics.max_drawdown)}</td>
                  <td>{g.metrics.trades}</td>
                  <td>{number(g.metrics.expectancy_r)}</td>
                  <td>{number(g.metrics.profit_factor)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel research-method">
        <h2>Frozen rules & evaluation</h2>
        <p>
          Slope uses direction × (current EMA50 − previous completed 1H EMA50) /
          Wilder ATR14. Separation uses |EMA20 − EMA50| / ATR14. Equality
          passes. Each policy retains the 2 ATR stop, 2R target and EMA50 exit.
        </p>
        <p>{report.assessment}</p>
        <details>
          <summary>All 27 experiments</summary>
          <div
            className="study-table-scroll"
            tabIndex={0}
            role="region"
            aria-label="All filter experiments"
          >
            <table>
              <thead>
                <tr>
                  <th>Period</th>
                  <th>Costs</th>
                  <th>Policy</th>
                  <th>Return</th>
                  <th>Drawdown</th>
                  <th>Trades</th>
                  <th>Mean R</th>
                </tr>
              </thead>
              <tbody>
                {report.groups.map((g) => (
                  <tr key={`${g.partition}-${g.scenario}-${g.entry_policy}`}>
                    <td>{periods[g.partition]}</td>
                    <td>{costs[g.scenario]}</td>
                    <td>{policies[g.entry_policy]}</td>
                    <td>{percent(g.metrics.return)}</td>
                    <td>{percent(g.metrics.max_drawdown)}</td>
                    <td>{g.metrics.trades}</td>
                    <td>{number(g.metrics.expectancy_r)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
      <section className="panel research-method">
        <h2>Evidence & limitations</h2>
        <ul>
          {Array.from(new Set(report.limitations)).map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
        <div className="research-downloads">
          {[
            "trades.csv",
            "trades.jsonl",
            "diagnostics.json",
            "dataset-manifest.json",
            "source-audit.json",
          ].map((file) => (
            <a key={file} href={`/api/research/filters?file=${file}`} download>
              {file}
            </a>
          ))}
        </div>
        <details>
          <summary>Report identity</summary>
          <p>
            Report <code>{report.id}</code>
          </p>
          <p>
            Dataset <code>{report.dataset_hash}</code>
          </p>
          <p>
            Code <code>{report.code_hash}</code>
          </p>
        </details>
      </section>
    </div>
  );
}
