export type ResearchMetrics = {
  initial_capital: string;
  ending_equity: string;
  net_pnl: string;
  return: string;
  gross_pnl: string;
  fees: string;
  funding_pnl: string;
  trades: number;
  win_rate: string | null;
  expectancy_usdt: string | null;
  expectancy_r: string | null;
  profit_factor: string | null;
  max_drawdown: string;
  time_exposure: string;
  average_holding_hours: string | null;
  ambiguous_stop_first: number;
  forced_partition_exits: number;
  max_time_underwater_hours: string;
  turnover: string;
  directions: Record<string, { trades: number; net_pnl: string }>;
  exit_reasons: Record<string, number>;
  blocked: Record<string, number>;
};
export type ResearchGroup = {
  partition: string;
  scenario: string;
  start: number;
  end_exclusive: number;
  metrics: ResearchMetrics;
  symbols: (ResearchMetrics & { symbol: string })[];
  daily_curve: { time: number; equity: string; exposure: string }[];
  uncertainty: {
    lower: string | null;
    upper: string | null;
    months: number;
    method: string;
  };
  benchmarks: {
    cash_return: string;
    passive_long_return: string;
    passive_fees: string;
    passive_funding_pnl: string;
  };
};
export type ResearchReport = {
  id: string;
  report_hash: string;
  dataset_hash: string;
  code_hash: string;
  strategy: string;
  strategy_hash: string;
  dataset_retrieved_at: string;
  assessment: string;
  limitations: string[];
  files: Record<string, string>;
  provenance: {
    archives: number;
    rows: number;
    venue: string;
    source_policy: string;
    source_audit: {
      rows: number;
      all_groups_complete: boolean;
      native_discrepancies: number;
    };
    funding_events: Record<string, number>;
    history_origins: Record<string, Record<string, number>>;
    filters: Record<string, { as_of: string; historical: boolean }>;
  };
  research: {
    id: string;
    symbols: string[];
    history_start: string;
    cutoff_exclusive: string;
    initial_capital_usdt: string;
    partitions: { name: string; start: string; end: string }[];
    scenarios: {
      id: string;
      fee_bps: string;
      spread_bps: string;
      slippage_bps: string;
      latency_ms: number;
    }[];
    execution: string;
    sizing: string;
    partition_boundary: string;
  };
  groups: ResearchGroup[];
};
