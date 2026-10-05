import type { ResearchGroup, ResearchReport } from "./research-types";

export type DiagnosticSummary = {
  trades: number;
  net_pnl: string;
  gross_pnl: string;
  fees: string;
  funding_pnl: string;
  win_rate: string | null;
  expectancy_r: string | null;
  expectancy_usdt: string | null;
  profit_factor: string | null;
  average_mae_r_observed: string | null;
  average_mfe_r_observed: string | null;
  observed_at_least_1r: number;
  losers_observed_at_least_1r: number;
};
export type DiagnosticGroup = {
  partition: string;
  scenario: string;
  exit_policy: string;
  summary: DiagnosticSummary;
  dimensions: Record<string, (DiagnosticSummary & { cohort: string })[]>;
};
export type ExitStudyReport = {
  id: string;
  report_hash: string;
  code_hash: string;
  dataset_hash: string;
  baseline_report_id: string;
  baseline_report_hash: string;
  baseline_control_parity: string;
  assessment: string;
  limitations: string[];
  research: ResearchReport["research"];
  study: {
    id: string;
    registered_on: string;
    policies: {
      id: string;
      strategy: string;
      target: boolean;
      ema50_exit: boolean;
    }[];
    diagnostics: Record<string, string[]>;
    entry_parity: string;
    diagnostic_features: string;
    excursions: string;
    evaluation: string;
    assessment: string;
  };
  groups: (ResearchGroup & {
    exit_policy: string;
    strategy: string;
    return_delta_vs_baseline: string;
  })[];
  diagnostics: DiagnosticGroup[];
};
