"use client";
import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  createChart,
  LineSeries,
  LineStyle,
  TickMarkType,
  createSeriesMarkers,
  type Time,
  type IChartApi,
  type AutoscaleInfo,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type UTCTimestamp,
} from "lightweight-charts";
import charts from "@/lib/demo-charts.json";
import type { ChartData, Timeframe } from "@/lib/market-types";
import { formatIST, formatISTClock, formatISTDate } from "@/lib/time";
export type SignalChartPlan = {
  id: string;
  entry: string;
  stop: string;
  target: string;
  tp1?: string;
  tp2?: string;
  tp3?: string;
  startTime: number;
  direction: "long" | "short";
};
const milliseconds = (time: Time) =>
  typeof time === "number"
    ? time * 1000
    : typeof time === "string"
      ? Date.parse(time)
      : Date.UTC(time.year, time.month - 1, time.day);
export type DemoSymbol = keyof typeof charts;
export type { Timeframe } from "@/lib/market-types";
export const indicatorColors = {
  ema20: "#209b83",
  ema50: "#ba8c39",
  sma200: "#8670bf",
  atr: "#7894aa",
};
type ChartBundle = {
  chart: IChartApi;
  candles: ISeriesApi<"Candlestick">;
  lines: Record<"ema20" | "ema50" | "sma200" | "atr", ISeriesApi<"Line">>;
  fitted: boolean;
  markers: ISeriesMarkersPluginApi<Time>;
};

export function MarketChart({
  symbol,
  timeframe,
  indicators,
  dark,
  data,
  synthetic,
  tickSize,
  signalPlan,
  signalWindow = "source",
  signalScale = "full",
}: {
  symbol: string;
  timeframe: Timeframe;
  indicators: string[];
  dark: boolean;
  data: ChartData;
  synthetic: boolean;
  tickSize?: string | null;
  signalPlan?: SignalChartPlan;
  signalWindow?: "source" | "latest";
  signalScale?: "price" | "full";
}) {
  const container = useRef<HTMLDivElement>(null);
  const bundle = useRef<ChartBundle | null>(null);
  useEffect(() => {
    if (!container.current) return;
    const muted = dark ? "#a3b5a8" : "#626e65";
    const grid = dark ? "#233834" : "#edf1ee";
    const chart = createChart(container.current, {
      autoSize: true,
      localization: {
        timeFormatter: (time: Time) => formatIST(milliseconds(time)),
      },
      layout: {
        background: {
          type: ColorType.Solid,
          color: dark ? "#142622" : "#ffffff",
        },
        textColor: muted,
        fontFamily: "Inter Variable, sans-serif",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: muted, labelBackgroundColor: "#183b32" },
        horzLine: { color: muted, labelBackgroundColor: "#183b32" },
      },
      rightPriceScale: {
        borderColor: grid,
        scaleMargins: { top: 0.14, bottom: 0.1 },
      },
      timeScale: {
        borderColor: grid,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        tickMarkFormatter: (time: Time, type: TickMarkType) =>
          type === TickMarkType.Time || type === TickMarkType.TimeWithSeconds
            ? formatISTClock(milliseconds(time))
            : formatISTDate(milliseconds(time)),
      },
      handleScroll: {
        mouseWheel: false,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        mouseWheel: false,
        pinch: true,
        axisPressedMouseMove: true,
      },
    });
    const precision = Math.min(
      12,
      Math.max(2, tickSize?.split(".")[1]?.replace(/0+$/, "").length || 2),
    );
    const candles = chart.addSeries(CandlestickSeries, {
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const range = original();
        if (range?.priceRange && signalPlan) {
          const levels = [
            signalPlan.entry,
            signalPlan.stop,
            signalPlan.tp1,
            signalPlan.tp2,
            signalPlan.tp3,
            signalPlan.target,
          ]
            .filter((value): value is string => value != null)
            .map(Number)
            .filter(Number.isFinite);
          range.priceRange.minValue = Math.min(
            range.priceRange.minValue,
            ...levels,
          );
          range.priceRange.maxValue = Math.max(
            range.priceRange.maxValue,
            ...levels,
          );
        }
        return range;
      },
      upColor: "#229881",
      downColor: "#d47570",
      borderVisible: false,
      lastValueVisible: !signalPlan,
      priceLineVisible: !signalPlan,
      wickUpColor: "#229881",
      wickDownColor: "#d47570",
      priceFormat: {
        type: "price",
        precision,
        minMove: tickSize ? Number(tickSize) : 0.01,
      },
    });
    const lines = {} as ChartBundle["lines"];
    for (const key of ["ema20", "ema50", "sma200", "atr"] as const) {
      lines[key] = chart.addSeries(
        LineSeries,
        {
          color: indicatorColors[key],
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          // Keep every overlay plotted. Price focus only excludes overlays
          // from scale calculation; candles and frozen risk levels set its bounds.
          autoscaleInfoProvider: (original: () => AutoscaleInfo | null) =>
            signalPlan && signalScale === "price" && key !== "atr"
              ? null
              : original(),
          title: key === "atr" ? "ATR14" : "",
          priceFormat: { type: "price", precision, minMove: 0.00000001 },
        },
        key === "atr" ? 1 : 0,
      );
    }
    chart.panes()[1].setHeight(80);
    if (signalPlan) {
      const levels: Array<[string, string, string]> = [
        [signalPlan.entry, "Entry", "#2875ac"],
        [signalPlan.stop, "SL", "#b95350"],
      ];
      if (signalPlan.tp1 && signalPlan.tp2 && signalPlan.tp3) {
        levels.push(
          [signalPlan.tp1, "TP1", "#17836b"],
          [signalPlan.tp2, "TP2", "#17836b"],
          [signalPlan.tp3, "TP3", "#17836b"],
        );
      } else {
        levels.push([signalPlan.target, "Target", "#17836b"]);
      }
      for (const [value, title, color] of levels) {
        candles.createPriceLine({
          price: Number(value),
          color,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title,
        });
      }
    }
    const markers = createSeriesMarkers(candles);
    bundle.current = { chart, candles, lines, fitted: false, markers };
    return () => {
      bundle.current = null;
      markers.detach();
      chart.remove();
    };
  }, [symbol, timeframe, dark, tickSize, signalPlan, signalScale]);
  useEffect(() => {
    const current = bundle.current;
    if (!current) return;
    current.candles.setData(
      data.candles.map((c) => ({ ...c, time: c.time as UTCTimestamp })),
    );
    current.markers.setMarkers(
      signalPlan && data.candles.some((c) => c.time === signalPlan.startTime)
        ? [
            {
              time: signalPlan.startTime as UTCTimestamp,
              position:
                signalPlan.direction === "long" ? "belowBar" : "aboveBar",
              shape: signalPlan.direction === "long" ? "arrowUp" : "arrowDown",
              color: "#2875ac",
              text: "Start",
            },
          ]
        : [],
    );
    for (const key of ["ema20", "ema50", "sma200", "atr"] as const) {
      current.lines[key].setData(
        data[key].map((p) => ({ ...p, time: p.time as UTCTimestamp })),
      );
      current.lines[key].applyOptions({
        visible: key === "atr" || indicators.includes(key),
      });
    }
    if (data.candles.length && !current.fitted) {
      const sourceIndex = signalPlan
        ? data.candles.findIndex((c) => c.time === signalPlan.startTime)
        : -1;
      const focusSource = signalWindow === "source" && sourceIndex >= 0;
      const from = Math.max(
        0,
        focusSource ? sourceIndex - 72 : data.candles.length - 96,
      );
      const end = focusSource
        ? Math.min(data.candles.length, sourceIndex + 49)
        : data.candles.length;
      // Reserve room for the source marker text, including on narrow screens.
      const rightSpace = signalPlan
        ? Math.max(
            6,
            Math.ceil(
              (42 * (end - from)) /
                Math.max(1, current.chart.timeScale().width() - 42),
            ),
          )
        : 3;
      current.chart.timeScale().setVisibleLogicalRange({
        from,
        to: end + rightSpace,
      });
      current.fitted = true;
    }
  }, [
    data,
    indicators,
    symbol,
    timeframe,
    dark,
    tickSize,
    signalPlan,
    signalWindow,
    signalScale,
  ]);
  return (
    <div
      className="chart-canvas"
      role="img"
      aria-label={`${synthetic ? "Synthetic" : "Binance"} ${symbol} ${timeframe} candlestick chart with selected EMA and SMA overlays and ATR14 pane${signalPlan ? " and signal start, entry, SL and target levels" : ""}`}
    >
      <div className="chart-renderer" ref={container} />
    </div>
  );
}
