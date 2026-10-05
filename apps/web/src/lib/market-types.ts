export type Timeframe = "1h" | "4h";
export type ChartData = {
  candles: {
    time: number;
    open: number;
    high: number;
    low: number;
    close: number;
  }[];
  ema20: { time: number; value: number }[];
  ema50: { time: number; value: number }[];
  sma200: { time: number; value: number }[];
  atr: { time: number; value: number }[];
};
export type CollectorHealth = {
  state: string;
  live: boolean;
  last_event_at: number | null;
  error: string | null;
  clock_offset_ms: number;
};
export type MarketView = {
  symbol: string;
  timeframe: Timeframe;
  source: "binance-usdm";
  status: string;
  ready: boolean;
  bars: number;
  history_origin: number | null;
  last_close_time: number | null;
  lineage: string | null;
  signal_generation: boolean;
  collector: CollectorHealth;
  contract: {
    valid: boolean;
    reason: string;
    tick_size: string | null;
    step_size: string | null;
  };
  values: Record<"ema20" | "ema50" | "sma200" | "atr", string | null>;
  trend: string | null;
  series: {
    candles: {
      time: number;
      open: string;
      high: string;
      low: string;
      close: string;
    }[];
    ema20: { time: number; value: string }[];
    ema50: { time: number; value: string }[];
    sma200: { time: number; value: string }[];
    atr: { time: number; value: string }[];
  };
};
export const emptyChart: ChartData = {
  candles: [],
  ema20: [],
  ema50: [],
  sma200: [],
  atr: [],
};
export const marketName = (symbol: string) =>
  ({
    BTCUSDT: "Bitcoin",
    ETHUSDT: "Ethereum",
    SOLUSDT: "Solana",
    BNBUSDT: "BNB",
    XRPUSDT: "XRP",
  })[symbol] || symbol.replace("USDT", "");
export function displayPrice(value: number, tickSize?: string | null) {
  const precision = Math.min(
    12,
    Math.max(2, tickSize?.split(".")[1]?.replace(/0+$/, "").length || 2),
  );
  return value.toLocaleString("en-US", {
    minimumFractionDigits: precision,
    maximumFractionDigits: precision,
  });
}
