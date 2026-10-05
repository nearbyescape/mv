"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  MarketChart,
  indicatorColors,
  type SignalChartPlan,
} from "./market-chart";
import {
  displayPrice,
  type ChartData,
  type MarketView,
} from "@/lib/market-types";
import type { EngineSignal } from "@/lib/signals";
import { formatIST } from "@/lib/time";
type View = {
  signal_id: string;
  plan_hash: string;
  symbol: string;
  timeframe: string;
  source: string;
  window: string;
  live: boolean;
  market_status: string;
  source_candle_in_window: boolean;
  source_revised: boolean;
  integrity_valid: boolean;
  series: MarketView["series"];
};
export function SignalChart({ signal }: { signal: EngineSignal }) {
  const [window, setWindow] = useState<"source" | "latest">("source");
  const [scale, setScale] = useState<"price" | "full">("price");
  const [reset, setReset] = useState(0);
  const [result, setResult] = useState<{
    view: View | null;
    error: string | null;
  }>({ view: null, error: null });
  const [dark, setDark] = useState(false);
  const element = useRef<HTMLElement>(null);
  useEffect(() => {
    const shell = element.current?.closest("[data-theme]");
    if (!shell) return;
    const sync = () => setDark(shell.getAttribute("data-theme") === "dark");
    sync();
    const observer = new MutationObserver(sync);
    observer.observe(shell, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const response = await fetch(
          `/api/signals/${signal.id}/chart?window=${window}`,
          { cache: "no-store", signal: abort.signal },
        );
        if (response.status === 401) location.assign("/login");
        if (!response.ok)
          throw new Error(
            "Chart feed unavailable. Retained candles are not live.",
          );
        const view = (await response.json()) as View;
        if (
          view.signal_id !== signal.id ||
          view.plan_hash !== signal.plan_hash ||
          view.symbol !== signal.symbol ||
          view.source !== "binance-usdm" ||
          view.timeframe !== "1h" ||
          view.window !== window ||
          !view.integrity_valid ||
          !(["candles", "ema20", "ema50", "sma200", "atr"] as const).every(
            (key) =>
              Array.isArray(view.series?.[key]) &&
              view.series[key].every(
                (point, index, all) =>
                  Number.isFinite(point.time) &&
                  (index === 0 || point.time > all[index - 1].time) &&
                  Object.entries(point).every(
                    ([field, value]) =>
                      field === "time" || Number.isFinite(Number(value)),
                  ),
              ),
          )
        )
          throw new Error("Chart response does not match the saved signal.");
        if (!abort.signal.aborted) setResult({ view, error: null });
      } catch (error) {
        if (!abort.signal.aborted)
          setResult((old) => ({
            ...old,
            error: error instanceof Error ? error.message : "Chart unavailable",
          }));
      }
      if (!abort.signal.aborted) timer = setTimeout(load, 10_000);
    }
    void load();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, [signal.id, signal.plan_hash, signal.symbol, window]);
  const view = result.view?.window === window ? result.view : null;
  const data = useMemo<ChartData>(
    () =>
      ({
        candles: (view?.series.candles || []).map((c) => ({
          time: c.time,
          open: Number(c.open),
          high: Number(c.high),
          low: Number(c.low),
          close: Number(c.close),
        })),
        ...Object.fromEntries(
          (["ema20", "ema50", "sma200", "atr"] as const).map((key) => [
            key,
            (view?.series[key] || []).map((p) => ({
              time: p.time,
              value: Number(p.value),
            })),
          ]),
        ),
      }) as ChartData,
    [view],
  );
  const plan = useMemo<SignalChartPlan>(
    () => ({
      id: signal.id,
      entry: signal.entry,
      stop: signal.stop,
      target: signal.target,
      startTime: signal.source_open_time / 1000,
      direction: signal.direction,
    }),
    [
      signal.id,
      signal.entry,
      signal.stop,
      signal.target,
      signal.source_open_time,
      signal.direction,
    ],
  );
  const [indicators, setIndicators] = useState(["ema20", "ema50", "sma200"]);
  return (
    <section
      className="signal-chart"
      ref={element}
      aria-label="Signal price chart"
    >
      <div className="signal-chart-head">
        <div>
          <h3>Signal chart · {signal.symbol} · 1H</h3>
          <p>Source close: {formatIST(signal.source_close_boundary)}</p>
        </div>
        <div className="segmented" aria-label="Signal chart window">
          <button
            aria-pressed={window === "source"}
            onClick={() => setWindow("source")}
          >
            Signal start
          </button>
          <button
            aria-pressed={window === "latest"}
            onClick={() => setWindow("latest")}
          >
            Latest candles
          </button>
        </div>
      </div>
      <div className="signal-chart-levels">
        {(
          [
            ["entry", "Entry", "#2875ac"],
            ["stop", "SL", "#b95350"],
            ["target", "Target", "#17836b"],
          ] as const
        ).map(([key, title, color]) => (
          <span key={key} style={{ borderColor: color }}>
            {title}{" "}
            <b>${displayPrice(Number(signal[key]), signal.tick_size)}</b>
          </span>
        ))}
        {data.candles.length > 0 && (
          <span style={{ borderColor: "var(--secondary)" }}>
            Last close{" "}
            <b>
              $
              {displayPrice(
                data.candles[data.candles.length - 1].close,
                signal.tick_size,
              )}
            </b>
          </span>
        )}
      </div>
      <div className="signal-chart-controls">
        <div className="segmented" aria-label="Signal chart scale">
          <button
            aria-pressed={scale === "price"}
            onClick={() => setScale("price")}
          >
            Price focus
          </button>
          <button
            aria-pressed={scale === "full"}
            onClick={() => setScale("full")}
          >
            Full indicator range
          </button>
        </div>
        <button
          className="signal-chart-reset"
          onClick={() => setReset((old) => old + 1)}
        >
          Reset view
        </button>
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
            aria-label={label}
            aria-pressed={indicators.includes(key)}
            onClick={() =>
              setIndicators((old) =>
                old.includes(key)
                  ? old.filter((k) => k !== key)
                  : [...old, key],
              )
            }
          >
            <i style={{ background: indicatorColors[key] }} />
            {label}
            {data[key].length > 0 && (
              <span className="signal-indicator-value">
                {displayPrice(
                  data[key][data[key].length - 1].value,
                  signal.tick_size,
                )}
              </span>
            )}
          </button>
        ))}
        <span className="atr-legend">ATR 14 · IST</span>
      </div>
      <div className="signal-chart-canvas">
        {data.candles.length ? (
          <MarketChart
            key={`${window}:${reset}`}
            symbol={signal.symbol}
            timeframe="1h"
            indicators={indicators}
            dark={dark}
            data={data}
            synthetic={false}
            tickSize={signal.tick_size}
            signalPlan={plan}
            signalWindow={window}
            signalScale={scale}
          />
        ) : (
          <p className="signal-chart-empty">
            {result.error || "Loading completed Binance candles…"}
          </p>
        )}
      </div>
      <p className="signal-chart-caption" role="status">
        {result.error ||
          (!view
            ? "Waiting for market data"
            : window === "latest"
              ? view.live
                ? "Live feed · completed candles · refreshes every 10 seconds"
                : `Retained candles · ${view.market_status}`
              : "Signal source context · completed candles · refreshes every 10 seconds")}
        . Original signal levels stay fixed.
      </p>
      {scale === "price" && (
        <p className="signal-chart-scale-note">
          Price focus fits candles and signal levels. Distant indicators may be
          outside the view; choose Full indicator range to see every selected
          line.
        </p>
      )}
      {view && !view.source_candle_in_window && (
        <p className="signal-chart-caption">
          Source candle is outside this window.{" "}
          {window === "latest"
            ? "Choose Signal start to inspect its original context."
            : "The original candle is not retained; no start marker is fabricated."}
        </p>
      )}
      {(signal.source_revised || view?.source_revised) && (
        <p className="signal-alert">
          Withdrawn source: current candles may differ from the saved evidence.
          Lines show the original historical plan.
        </p>
      )}
    </section>
  );
}
