import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile } from "node:fs/promises";
import fixture from "./fixtures/engine-feed.json";
import type { SignalFeed } from "../src/lib/signals";
test.use({ timezoneId: "America/Los_Angeles" });

function feed() {
  return structuredClone(fixture) as SignalFeed;
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/history**", async (route) => {
    const current = await page.evaluate(() =>
      fetch("/api/signals").then((r) => r.json()),
    );
    return route.fulfill({
      json: {
        signals: current.signals || [],
        next: null,
        server_time: current.server_time,
      },
    });
  });
  await page.route("**/api/system", (route) =>
    route.fulfill({
      json: { status: "ok", database: "connected", engine: fixture.engine },
    }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT"] } }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({
      status: 503,
      json: { error: "chart omitted in signal tests" },
    }),
  );
});

async function openJournal(page: Page, mobile: boolean) {
  if (mobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
}

test("live mode has an honest empty state and never shows synthetic entries", async ({
  page,
}) => {
  const data = feed();
  data.signals = [];
  data.slots = [];
  data.decisions = [];
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await expect(
    page.getByText("Waiting for a qualifying setup", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("No signals published yet", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("DEMO-001", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Inspect setup", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Binance signals · Engine running", { exact: true }),
  ).toBeVisible();
});

test("Market Safety Mode is visible when a direction is circuit-broken", async ({
  page,
}) => {
  const data = feed();
  data.safety = {
    status: "guarded",
    publication_enabled: true,
    analytics: { ready: true, max_age_ms: 45000, age_ms: 1000 },
    paused_directions: ["long"],
    direction_details: {
      long: {
        paused: true,
        triggered_signals: ["a".repeat(64), "b".repeat(64)],
        pause_until: data.server_time + 60 * 60 * 1000,
        threshold_r: "0.50",
      },
    },
    max_same_direction_signals_per_source_close: 2,
    btc_15m_timing_veto: true,
    message:
      "Market Safety Mode: LONG opportunities are temporarily paused after correlated deterioration.",
  };
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Market Safety Mode");
  await expect(page.getByRole("alert")).toContainText(
    "LONG opportunities are temporarily paused",
  );
});

test("backend-generated plan displays exact evidence, downloads intact and passes accessibility checks", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: feed() }),
  );
  await page.goto("/");
  await expect(page.locator(".live-signal-panel")).toContainText("$200.10");
  await expect(page.locator(".live-signal-panel")).toContainText("$193.00");
  await expect(page.locator(".live-signal-panel")).toContainText("$214.30");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  const bounds = await dialog.boundingBox();
  expect(bounds).not.toBeNull();
  expect(bounds!.x).toBeGreaterThanOrEqual(0);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(
    page.viewportSize()!.width,
  );
  expect(
    await dialog.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
  await expect(dialog.getByText("Passed", { exact: true })).toHaveCount(6);
  await expect(
    dialog.getByText(fixture.signals[0].evidence.source.atr, { exact: true }),
  ).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Mark as held", exact: true }),
  ).toBeEnabled();
  const downloadPromise = page.waitForEvent("download");
  await dialog
    .getByRole("button", { name: "Download evidence", exact: true })
    .click();
  const download = await downloadPromise;
  const exported = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(exported.evidence).toEqual(fixture.signals[0].evidence);
  expect(exported.frozen_atr).toBe(fixture.signals[0].frozen_atr);
  expect(exported.evidence_hash).toBe(fixture.signals[0].evidence_hash);
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("AI commentary appears beside frozen backend levels and is hidden for withdrawn evidence", async ({
  page,
}) => {
  const data = feed();
  data.signals[0].ai = "complete";
  data.signals[0].ai_review = {
    status: "complete",
    model: "deepseek/deepseek-v4-pro-0813",
    summary:
      "The saved completed candle checks agree with the recorded direction.",
    limitations: ["Reference quotes are not assured fills."],
  };
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByText(data.signals[0].ai_review.summary!, { exact: true }),
  ).toBeVisible();
  await expect(dialog.locator(".signal-levels")).toContainText("$200.10");
  await expect(dialog.locator(".signal-levels")).toContainText("$193.00");
  await expect(dialog.locator(".signal-levels")).toContainText("$214.30");
  await page.keyboard.press("Escape");
  data.signals[0].source_revised = true;
  data.signals[0].status = "withdrawn";
  data.signals[0].entry_actionable = false;
  await page.reload();
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  await expect(
    dialog.getByText(data.signals[0].ai_review.summary!, { exact: true }),
  ).toHaveCount(0);
});

test("operator state waits for successful persistence and held state keeps levels frozen", async ({
  page,
}) => {
  const data = feed();
  let reject = true;
  await page.route("**/api/signals**", async (route) => {
    if (route.request().method() !== "POST")
      return route.fulfill({ json: data });
    const action = route.request().postDataJSON();
    expect(action.id).toBe(data.signals[0].id);
    if (reject)
      return route.fulfill({
        status: 409,
        json: { detail: "Signal slot changed; reload" },
      });
    data.signals[0].status = action.action === "hold" ? "held" : "released";
    data.signals[0].slot = action.action === "hold" ? "held" : null;
    data.signals[0].entry_actionable = false;
    data.slots =
      action.action === "hold"
        ? [{ symbol: "BTCUSDT", signal_id: data.signals[0].id, state: "held" }]
        : [];
    return route.fulfill({ json: data.signals[0] });
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("State note", { exact: true })
    .fill("Private group operator report");
  await dialog
    .getByRole("button", { name: "Mark as held", exact: true })
    .click();
  await expect(dialog.getByRole("alert")).toContainText("Signal slot changed");
  await expect(
    dialog.getByRole("button", { name: "Mark as held", exact: true }),
  ).toBeVisible();
  reject = false;
  await dialog
    .getByRole("button", { name: "Mark as held", exact: true })
    .click();
  await expect(dialog.locator(".signal-detail-status")).toContainText("held");
  await expect(
    dialog.getByRole("button", { name: "Mark as held", exact: true }),
  ).toHaveCount(0);
  await expect(dialog.locator(".signal-levels")).toContainText("$193.00");
  await dialog
    .getByRole("button", { name: "Release signal slot", exact: true })
    .click();
  await expect(dialog.locator(".signal-detail-status")).toContainText(
    "released",
  );
  await expect(dialog.locator(".signal-levels")).toContainText("$214.30");
});

test("V3 signal shows TP1 TP2 TP3 and scaled management in web views", async ({
  page,
  isMobile,
}) => {
  const data = feed();
  const signal = data.signals[0];
  signal.strategy = "MV-TREND-DUAL-v3";
  signal.tp1 = "207.20";
  signal.tp2 = "210.75";
  signal.tp3 = signal.target;
  signal.tp1_r = "1";
  signal.tp2_r = "1.5";
  signal.tp3_r = "2";
  signal.exit_management = {
    tp1_allocation: "0.30",
    tp2_allocation: "0.30",
    tp3_allocation: "0.40",
    after_tp1: "move_remaining_stop_to_entry",
    after_tp2: "move_remaining_stop_to_tp1",
    maximum_realized_r: "1.55",
    reference_only: true,
  };
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");

  const panel = page.locator(".live-signal-panel");
  await expect(panel).toContainText("TP1 · 30%");
  await expect(panel).toContainText("TP2 · 30%");
  await expect(panel).toContainText("TP3 · 40%");

  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("TP1 · 30% · +1R");
  await expect(dialog).toContainText("TP2 · 30% · +1.5R");
  await expect(dialog).toContainText("TP3 · 40% · +2R");
  await expect(dialog).toContainText(
    "After TP1, move the remaining stop to entry",
  );
  await page.keyboard.press("Escape");

  await openJournal(page, isMobile);
  await expect(page.locator(".signal-journal-prices").first()).toContainText(
    "T1",
  );
  await expect(page.locator(".signal-journal-prices").first()).toContainText(
    "T2",
  );
  await expect(page.locator(".signal-journal-prices").first()).toContainText(
    "T3",
  );
});


test("signal charts preserve frozen levels, refresh only while open and display IST", async ({
  page,
}) => {
  await page.clock.install();
  const data = feed();
  const signal = data.signals[0];
  let requests = 0;
  await page.route("**/api/signals", (route) => route.fulfill({ json: data }));
  await page.route("**/api/signals/*/chart?**", (route) => {
    requests++;
    const window = new URL(route.request().url()).searchParams.get("window");
    const snapshots = [signal.evidence.previous, signal.evidence.source];
    const points = snapshots.map((s) => ({
      time: s.open_time / 1000,
      ...s.ohlcv,
    }));
    const series = {
      candles: points,
      ...Object.fromEntries(
        (["ema20", "ema50", "sma200", "atr"] as const).map((key) => [
          key,
          snapshots.map((s) => ({ time: s.open_time / 1000, value: s[key] })),
        ]),
      ),
    };
    return route.fulfill({
      json: {
        signal_id: signal.id,
        plan_hash: signal.plan_hash,
        symbol: signal.symbol,
        timeframe: "1h",
        source: "binance-usdm",
        window,
        series,
        live: true,
        market_status: "ready",
        source_candle_in_window: true,
        integrity_valid: true,
        source_revised: false,
      },
    });
  });
  await page.goto("/");
  expect(requests).toBe(0);
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("img", { name: /signal start, entry, SL and target/ }),
  ).toBeVisible();
  const expected = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  }).format(signal.source_close_boundary);
  await expect(dialog.locator(".signal-timestamps")).toContainText(
    `${expected} IST`,
  );
  await expect(dialog.locator(".signal-chart-levels")).toContainText(
    "Entry $200.10",
  );
  await expect(dialog.locator(".signal-chart-levels")).toContainText(
    "SL $193.00",
  );
  await expect(dialog.locator(".signal-chart-levels")).toContainText(
    "Target $214.30",
  );
  await expect(
    dialog
      .locator(".signal-chart")
      .getByRole("button", { name: "EMA 20", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await dialog.locator(".signal-chart").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: test.info().outputPath("signal-chart-ist.png"),
    fullPage: true,
  });
  const before = requests;
  await page.clock.fastForward(11_000);
  await expect.poll(() => requests).toBeGreaterThan(before);
  await dialog
    .getByRole("button", { name: "Latest candles", exact: true })
    .click();
  await expect(dialog.locator(".signal-chart-caption").first()).toContainText(
    "Live feed",
  );
  await expect(dialog.locator(".signal-chart-levels")).toContainText(
    "Target $214.30",
  );
  await page.keyboard.press("Escape");
  await expect(page.locator(".signal-chart")).toHaveCount(0);
  const closedRequests = requests;
  await page.clock.fastForward(20_000);
  expect(requests).toBe(closedRequests);
});

test("signal chart latest view shows broad history and price focus prevents distant SMA compression", async ({
  page,
}) => {
  const data = feed();
  const signal = data.signals[0];
  // Controlled presentation bars only: no signal generation or financial arithmetic.
  const candles = Array.from({ length: 120 }, (_, i) => ({
    time: signal.source_open_time / 1000 - (119 - i) * 3600,
    open: "201",
    high: "202",
    low: "198",
    close: i % 2 ? "199" : "201.5",
  }));
  const series = {
    candles,
    ...Object.fromEntries(
      (["ema20", "ema50", "sma200", "atr"] as const).map((key) => [
        key,
        candles.map((c) => ({
          time: c.time,
          value: key === "sma200" ? "100" : key === "atr" ? "3.5" : "200",
        })),
      ]),
    ),
  };
  await page.route("**/api/signals", (route) => route.fulfill({ json: data }));
  await page.route("**/api/signals/*/chart?**", (route) =>
    route.fulfill({
      json: {
        signal_id: signal.id,
        plan_hash: signal.plan_hash,
        symbol: signal.symbol,
        timeframe: "1h",
        source: "binance-usdm",
        window: new URL(route.request().url()).searchParams.get("window"),
        series,
        live: true,
        market_status: "ready",
        source_candle_in_window: true,
        integrity_valid: true,
        source_revised: false,
      },
    }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const chart = page.getByRole("dialog").locator(".signal-chart");
  await expect(chart.getByRole("img")).toBeVisible();
  await chart
    .getByRole("button", { name: "Latest candles", exact: true })
    .click();
  await expect(
    chart.getByRole("button", { name: "Latest candles", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    chart.getByRole("button", { name: "Price focus", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    chart.getByRole("button", { name: "SMA 200", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await chart.scrollIntoViewIfNeeded();
  // Inspect rendered red candle bodies, independent of chart configuration.
  // Exclude axis canvases; neither the stop line nor markers use this color.
  const bodies = () =>
    chart.locator(".signal-chart-canvas").evaluate((element) => {
      const measurements = [...element.querySelectorAll("canvas")].map(
        (canvas) => {
          const context = canvas.getContext("2d");
          if (!context || canvas.getBoundingClientRect().width < 120)
            return { count: 0, average: 0 };
          const pixels = context.getImageData(
            0,
            0,
            canvas.width,
            canvas.height,
          ).data;
          const ratio = canvas.width / canvas.getBoundingClientRect().width;
          const heights: number[] = [];
          let body = 0;
          for (let x = 0; x < canvas.width - 10 * ratio; x++) {
            let red = 0;
            for (let y = 0; y < canvas.height; y++) {
              const offset = (y * canvas.width + x) * 4;
              if (
                Math.abs(pixels[offset] - 212) < 3 &&
                Math.abs(pixels[offset + 1] - 117) < 3 &&
                Math.abs(pixels[offset + 2] - 112) < 3 &&
                pixels[offset + 3] > 200
              )
                red++;
            }
            if (red >= 2 * ratio) body = Math.max(body, red / ratio);
            else if (body) {
              heights.push(body);
              body = 0;
            }
          }
          if (body) heights.push(body);
          return {
            count: heights.length,
            average: heights.reduce((a, b) => a + b, 0) / (heights.length || 1),
          };
        },
      );
      return measurements.sort((a, b) => b.count - a.count)[0];
    });
  await expect
    .poll(async () => (await bodies()).count)
    .toBeGreaterThanOrEqual(30);
  const focused = await bodies();
  await chart.screenshot({
    path: test.info().outputPath("signal-price-focus.png"),
  });
  await chart
    .getByRole("button", { name: "Full indicator range", exact: true })
    .click();
  await expect(
    chart.getByRole("button", { name: "Full indicator range", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(async () => (await bodies()).average)
    .toBeLessThan(focused.average / 2);
  await chart.screenshot({
    path: test.info().outputPath("signal-full-indicator-range.png"),
  });
  await chart.getByRole("button", { name: "Reset view", exact: true }).click();
  await expect
    .poll(async () => (await bodies()).count)
    .toBeGreaterThanOrEqual(30);
  await expect(chart.locator(".signal-chart-levels")).toContainText(
    "Entry $200.10",
  );
  await expect(chart.locator(".signal-chart-levels")).toContainText(
    "SL $193.00",
  );
  await expect(chart.locator(".signal-chart-levels")).toContainText(
    "Target $214.30",
  );
  expect(
    await chart.evaluate(
      (element) => element.scrollWidth <= element.clientWidth,
    ),
  ).toBe(true);
});

test("IST formatting handles midnight rollover and is independent of browser timezone", async ({
  page,
}) => {
  await page.route("**/api/signals", (route) =>
    route.fulfill({ json: feed() }),
  );
  await page.goto("/");
  const formats = await page.evaluate(async () => {
    // Verify the interface through saved source timestamps, never shift source epochs.
    return { browserZone: Intl.DateTimeFormat().resolvedOptions().timeZone };
  });
  expect(formats.browserZone).toBe("America/Los_Angeles");
  const data = feed();
  data.signals[0].published_at = Date.parse("2026-10-04T20:00:00Z");
  data.signals[0].quote_time = Date.parse("2026-10-04T06:30:00Z");
  await page.route("**/api/signals", (route) => route.fulfill({ json: data }));
  await page.reload();
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const times = page.getByRole("dialog").locator(".signal-timestamps");
  await expect(times).toContainText("05 Oct 2026, 01:30 AM IST");
  await expect(times).toContainText("04 Oct 2026, 12:00 PM IST");
  await expect(times).not.toContainText("UTC");
});

test("entry expiry disables holding even before the next API poll", async ({
  page,
}) => {
  const data = feed();
  data.signals[0].expires_at = data.server_time + 700;
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "Mark as held", exact: true }),
  ).toBeDisabled({ timeout: 4000 });
  await expect(dialog.locator(".signal-detail-status")).toContainText(
    "expired",
  );
});

test("withdrawn signals preserve evidence and cannot be marked held", async ({
  page,
}) => {
  const data = feed();
  data.signals[0].source_revised = true;
  data.signals[0].status = "withdrawn";
  data.signals[0].entry_actionable = false;
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: data }),
  );
  await page.goto("/");
  await page
    .getByRole("button", { name: "Inspect signal", exact: true })
    .click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("alert")).toContainText(
    "Source data changed after publication",
  );
  await expect(
    dialog.getByRole("button", { name: "Mark as held", exact: true }),
  ).toBeDisabled();
  await expect(dialog.locator(".signal-levels")).toContainText("$193.00");
});

test("engine journal filters and CSV preserve backend decimal strings", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: feed() }),
  );
  await page.goto("/");
  await openJournal(page, isMobile);
  await expect(
    page.getByRole("heading", { name: "Evaluation log", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Filter engine direction").selectOption("short");
  await expect(
    page.getByText("No signals match your filters", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Filter engine direction").selectOption("long");
  const promise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  const csv = await readFile((await (await promise).path())!, "utf8");
  expect(csv).toContain(fixture.signals[0].frozen_atr);
  expect(csv).toContain(",200.1,193.0,214.3,");
  expect(csv).toContain(fixture.signals[0].evidence_hash);
  await page.getByLabel("Search engine journal").fill("unknown");
  await expect(
    page.getByText("No signals match your filters", { exact: true }),
  ).toBeVisible();
});
