"use client";
import { formatIST, formatISTDate } from "@/lib/time";
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, Clock3, ExternalLink, Database } from "lucide-react";
import charts from "@/lib/demo-charts.json";
import {
  displayPrice,
  emptyChart,
  marketName,
  type ChartData,
  type MarketView,
  type Timeframe,
} from "@/lib/market-types";
import { MarketChart, indicatorColors, type DemoSymbol } from "./market-chart";

export function LiveMarketPanel({
  symbol,
  setSymbol,
  timeframe,
  setTimeframe,
  indicators,
  toggleIndicator,
  dark,
  watchlist,
  mode,
  setMode,
}: {
  symbol: string;
  setSymbol: (symbol: string) => void;
  timeframe: Timeframe;
  setTimeframe: (timeframe: Timeframe) => void;
  indicators: string[];
  toggleIndicator: (key: string) => void;
  dark: boolean;
  watchlist: string[];
  mode: "binance" | "demo";
  setMode: (mode: "binance" | "demo") => void;
}) {
  const [result, setResult] = useState<{
    view: MarketView | null;
    error: string | null;
  }>({ view: null, error: null });
  useEffect(() => {
    if (mode !== "binance") return;
    let active = true;
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const response = await fetch(
          `/api/markets?symbol=${encodeURIComponent(symbol)}&timeframe=${timeframe}`,
          { cache: "no-store", signal: abort.signal },
        );
        if (!response.ok)
          throw new Error(
            "Market API unavailable. Start the API and collector.",
          );
        const view = (await response.json()) as MarketView;
        if (
          view.source !== "binance-usdm" ||
          view.symbol !== symbol ||
          view.timeframe !== timeframe
        )
          throw new Error(
            "Market response does not match the requested chart.",
          );
        if (active) setResult({ view, error: null });
      } catch (error) {
        if (active)
          setResult((previous) => ({
            view: previous.view,
            error:
              error instanceof Error
                ? error.message
                : "Market feed unavailable",
          }));
      }
      if (active) timer = setTimeout(load, 10_000);
    }
    void load();
    return () => {
      active = false;
      abort.abort();
      clearTimeout(timer);
    };
  }, [symbol, timeframe, mode]);
  const view =
    result.view?.symbol === symbol && result.view.timeframe === timeframe
      ? result.view
      : null;
  const synthetic = mode === "demo";
  const demo = charts[symbol as DemoSymbol]?.[timeframe];
  const data = useMemo<ChartData>(() => {
    if (synthetic) return demo || emptyChart;
    if (!view) return emptyChart;
    return {
      candles: view.series.candles.map((c) => ({
        time: c.time,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
      ema20: view.series.ema20.map((p) => ({
        time: p.time,
        value: Number(p.value),
      })),
      ema50: view.series.ema50.map((p) => ({
        time: p.time,
        value: Number(p.value),
      })),
      sma200: view.series.sma200.map((p) => ({
        time: p.time,
        value: Number(p.value),
      })),
      atr: view.series.atr.map((p) => ({
        time: p.time,
        value: Number(p.value),
      })),
    };
  }, [synthetic, demo, view]);
  const last = data.candles.at(-1),
    previous = data.candles.at(-2);
  const change =
    last && previous
      ? ((last.close - previous.close) / previous.close) * 100
      : null;
  const price = (value: number) =>
    displayPrice(value, synthetic ? null : view?.contract.tick_size);
  const freshness = synthetic
    ? "Synthetic session"
    : result.error
      ? "Feed unavailable"
      : view?.status === "ready"
        ? "Live · Closed candles"
        : view
          ? view.status.replaceAll("-", " ")
          : "Connecting";
  return (
    <section className="panel market-panel">
      <div className="panel-head market-head">
        <div className="market-title">
          <span className={`coin-icon ${symbol === "BTCUSDT" ? "btc" : "eth"}`}>
            {symbol === "BTCUSDT"
              ? "₿"
              : symbol === "ETHUSDT"
                ? "Ξ"
                : symbol.slice(0, 1)}
          </span>
          <div>
            <label className="sr-only" htmlFor="chart-symbol">
              Chart market
            </label>
            <div className="select-wrap">
              <select
                id="chart-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
              >
                {watchlist.map((s) => (
                  <option key={s} value={s}>
                    {s.replace("USDT", "")} / USDT
                  </option>
                ))}
              </select>
              <ChevronDown size={15} />
            </div>
            <span className="muted small-text">
              {marketName(symbol)} · Perpetual ·{" "}
              {synthetic ? "Synthetic" : "Binance"}
            </span>
          </div>
        </div>
        <div className="segmented" aria-label="Chart timeframe">
          {(["1h", "4h"] as const).map((t) => (
            <button
              key={t}
              aria-pressed={timeframe === t}
              className={timeframe === t ? "selected" : ""}
              onClick={() => setTimeframe(t)}
            >
              {t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="data-mode-row">
        <div className="segmented" aria-label="Data source">
          <button
            className={!synthetic ? "selected" : ""}
            aria-pressed={!synthetic}
            onClick={() => setMode("binance")}
          >
            Binance data
          </button>
          <button
            className={synthetic ? "selected" : ""}
            aria-pressed={synthetic}
            onClick={() => setMode("demo")}
          >
            Demo data
          </button>
        </div>
        <span
          className={`status-badge ${!synthetic && view?.ready && !result.error ? "connected" : "expired"}`}
        >
          <i />
          {freshness}
        </span>
      </div>
      <div className="chart-quote">
        <strong>{last ? `$${price(last.close)}` : "—"}</strong>
        {change !== null && (
          <span className={change >= 0 ? "positive" : "negative"}>
            {change >= 0 ? "+" : ""}
            {change.toFixed(2)}%{" "}
            <span className="muted">last completed candle</span>
          </span>
        )}
        <span className="chart-date">
          {synthetic
            ? "29 Sep 2026 · Synthetic"
            : view?.last_close_time
              ? formatIST(view.last_close_time + 1)
              : "No completed candles yet"}
        </span>
      </div>
      <div className="chart-legend">
        {(
          [
            ["ema20", "EMA 20"],
            ["ema50", "EMA 50"],
            ["sma200", "SMA 200"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            aria-pressed={indicators.includes(key)}
            onClick={() => toggleIndicator(key)}
            className={!indicators.includes(key) ? "disabled-indicator" : ""}
          >
            <i style={{ background: indicatorColors[key] }} />
            {label}
            <span>
              {data[key].length ? price(data[key].at(-1)!.value) : "—"}
            </span>
          </button>
        ))}
        <span className="atr-legend">
          <i style={{ background: indicatorColors.atr }} />
          ATR 14 <b>{data.atr.length ? price(data.atr.at(-1)!.value) : "—"}</b>
        </span>
      </div>
      <div className="live-chart-wrap">
        <MarketChart
          symbol={symbol}
          timeframe={timeframe}
          indicators={indicators}
          dark={dark}
          data={data}
          synthetic={synthetic}
          tickSize={synthetic ? null : view?.contract.tick_size}
        />
        {!data.candles.length && (
          <div className="market-empty">
            <Database size={24} />
            <strong>
              {synthetic
                ? "No demo chart for this coin"
                : "Waiting for verified market data"}
            </strong>
            <p>
              {synthetic
                ? "BTC and ETH have synthetic chart fixtures."
                : result.error ||
                  view?.contract.reason ||
                  "The collector validates chosen contracts and warms up both timeframes."}
            </p>
          </div>
        )}
      </div>
      {!synthetic && (
        <div
          className={`data-integrity ${result.error || !view?.ready ? "data-pending" : ""}`}
        >
          <span>
            {result.error ||
              `${view?.bars || 0} completed bars · ${view?.bars && view.bars >= 500 ? "Warm-up complete" : "500-bar warm-up required"}`}
          </span>
          <span>
            {view?.history_origin
              ? `Seed origin: ${formatISTDate(view.history_origin)}`
              : "Awaiting history"}
          </span>
        </div>
      )}
      <div className="chart-foot">
        <span>
          <Clock3 size={12} />
          {synthetic
            ? "Synthetic fixtures"
            : "Backend-calculated EMA / SMA / Wilder ATR"}{" "}
          · IST
        </span>
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          Charts by TradingView
          <ExternalLink size={11} />
        </a>
      </div>
    </section>
  );
}
