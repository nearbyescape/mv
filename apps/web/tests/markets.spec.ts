import { expect, test } from "@playwright/test";
import charts from "../src/lib/demo-charts.json";
import type { MarketView } from "../src/lib/market-types";

function fixture(
  symbol = "BTCUSDT",
  timeframe: "1h" | "4h" = "1h",
  status = "ready",
): MarketView {
  const data =
    charts[symbol as keyof typeof charts]?.[timeframe] ||
    charts.BTCUSDT[timeframe];
  return {
    symbol,
    timeframe,
    source: "binance-usdm",
    status,
    ready: status === "ready",
    bars: 500,
    history_origin: 1775001600000,
    last_close_time: data.candles.at(-1)!.time * 1000 + 3_599_999,
    lineage: "test-lineage",
    signal_generation: false,
    collector: {
      state: "streaming",
      live: true,
      last_event_at: Date.now(),
      error: null,
      clock_offset_ms: 0,
    },
    contract: {
      valid: true,
      reason: "Test contract",
      tick_size: "0.10",
      step_size: "0.001",
    },
    values: { ema20: "67954", ema50: "67500", sma200: "66359", atr: "230" },
    trend: "long-trend",
    series: {
      candles: data.candles.map((c) => ({
        time: c.time,
        open: String(c.open),
        high: String(c.high),
        low: String(c.low),
        close: String(c.close),
      })),
      ema20: data.ema20.map((p) => ({ time: p.time, value: String(p.value) })),
      ema50: data.ema50.map((p) => ({ time: p.time, value: String(p.value) })),
      sma200: data.sma200.map((p) => ({
        time: p.time,
        value: String(p.value),
      })),
      atr: data.atr.map((p) => ({ time: p.time, value: String(p.value) })),
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT", "SOLUSDT"] } }),
  );
  await page.route("**/api/system", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        database: "connected",
        collector: fixture().collector,
      },
    }),
  );
});

test("Binance charts are the default and chosen coins work beyond the demo fixtures", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/markets**", (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get("symbol");
    return route.fulfill({
      json: symbol
        ? fixture(
            symbol,
            url.searchParams.get("timeframe") === "4h" ? "4h" : "1h",
          )
        : { markets: [fixture(), fixture("ETHUSDT"), fixture("SOLUSDT")] },
    });
  });
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Binance data", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByText("Live · Closed candles", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("500 completed bars · Warm-up complete"),
  ).toBeVisible();
  await page
    .getByLabel("Chart market", { exact: true })
    .selectOption("SOLUSDT");
  await page.getByRole("button", { name: "4H", exact: true }).click();
  await expect(
    page.getByRole("img", {
      name: "Binance SOLUSDT 4h candlestick chart",
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Signals come from backend rules and frozen evidence.", {
      exact: false,
    }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("stale market data retains its provenance and never appears ready", async ({
  page,
}) => {
  await page.route("**/api/markets**", (route) =>
    route.fulfill({
      json: new URL(route.request().url()).searchParams.has("symbol")
        ? fixture("BTCUSDT", "1h", "stale")
        : { markets: [fixture("BTCUSDT", "1h", "stale")] },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".data-mode-row")).toContainText("stale");
  await expect(
    page.getByText("Live · Closed candles", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("img", { name: "Binance BTCUSDT", exact: false }),
  ).toBeVisible();
});

test("unavailable Binance API never silently displays demo prices", async ({
  page,
}) => {
  await page.route("**/api/markets**", (route) =>
    route.fulfill({ status: 503, json: { error: "offline" } }),
  );
  await page.goto("/");
  await expect(
    page.getByText("Feed unavailable", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Waiting for verified market data", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".chart-quote strong")).toHaveText("—");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  await expect(page.locator(".chart-quote strong")).not.toHaveText("—");
  await expect(
    page.getByText("Synthetic session", { exact: true }),
  ).toBeVisible();
});

test("long watchlists scroll independently without stretching charts", async ({
  page,
  isMobile,
}) => {
  let symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"];
  await page.route("**/api/watchlist", (route) => {
    if (route.request().method() === "PUT")
      symbols = route.request().postDataJSON().symbols;
    return route.fulfill({ json: { symbols } });
  });
  await page.route("**/api/markets**", (route) => {
    const url = new URL(route.request().url());
    const symbol = url.searchParams.get("symbol");
    return route.fulfill({
      json: symbol
        ? fixture(symbol)
        : { markets: symbols.map((s) => fixture(s)) },
    });
  });
  await page.goto("/");
  const chart = page.locator(".live-chart-wrap");
  await expect(page.locator(".watch-row")).toHaveCount(3);
  const originalHeight = (await chart.boundingBox())!.height;
  const expanded = [
    "BTCUSDT",
    "ETHUSDT",
    ...Array.from({ length: 27 }, (_, i) => `COIN${i}USDT`),
  ];
  await page
    .getByRole("button", { name: "Manage markets", exact: true })
    .click();
  await page
    .getByLabel("Chosen coins", { exact: true })
    .fill(expanded.join(", "));
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".watch-row")).toHaveCount(29);
  for (const destination of ["overview", "markets"]) {
    if (destination === "markets") {
      if (isMobile)
        await page.getByRole("button", { name: "Open navigation" }).click();
      await page
        .getByRole("button", { name: "Chosen markets", exact: false })
        .first()
        .click();
    }
    await expect
      .poll(async () => (await chart.boundingBox())!.height)
      .toBe(originalHeight);
    expect(originalHeight).toBeLessThanOrEqual(560);
    const list = page.locator(".watch-list");
    expect(
      await list.evaluate(
        (element) => element.scrollHeight > element.clientHeight,
      ),
    ).toBe(true);
    await page.screenshot({
      path: test.info().outputPath(`${destination}-29-coins.png`),
      fullPage: true,
    });
    await page.locator(".watch-row").last().focus();
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Chart market", { exact: true })).toHaveValue(
      "COIN26USDT",
    );
    expect(await list.evaluate((element) => element.scrollTop)).toBeGreaterThan(
      0,
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
