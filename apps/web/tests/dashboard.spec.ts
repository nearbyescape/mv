import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/signals**", (route) => route.fulfill({ status: 503, json: { error: "offline test fixture" } }));
  await page.route("**/api/system", (route) =>
    route.fulfill({ json: { status: "ok", database: "connected" } }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT"] } }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({ status: 503, json: { error: "offline test fixture" } }),
  );
});

test("chart controls change symbol, timeframe and overlays without runtime errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  await expect(
    page.getByText("Charts and signal examples use synthetic data.", {
      exact: false,
    }),
  ).toBeVisible();
  await page
    .getByLabel("Chart market", { exact: true })
    .selectOption("ETHUSDT");
  await page.getByRole("button", { name: "4H", exact: true }).click();
  await expect(
    page.getByRole("img", {
      name: "Synthetic ETHUSDT 4h candlestick chart",
      exact: false,
    }),
  ).toBeVisible();
  const overlay = page.getByRole("button", { name: "EMA 20", exact: false });
  await overlay.click();
  await expect(overlay).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator(".app-shell")).toHaveAttribute(
    "data-theme",
    "dark",
  );
  expect(errors).toEqual([]);
});

test("setup dialog is honest about pending evidence and supports keyboard dismissal", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  await page
    .getByRole("button", { name: "Inspect setup", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(
    page.getByText("Rule checks have not been evaluated", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("Pending engine", { exact: true })).toHaveCount(
    5,
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("journal filtering and empty state work", async ({ page, isMobile }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  if (isMobile)
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
  await page.getByLabel("Filter direction").selectOption("Short");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText("ETH");
  await page.getByLabel("Search journal").fill("no-such-record");
  await expect(page.getByText("No examples match your filters.")).toBeVisible();
});

test("configuration save waits for API success and shows failed writes", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  await page
    .getByRole("button", { name: "Manage markets", exact: true })
    .click();
  await page
    .getByLabel("Chosen coins", { exact: true })
    .fill("BTCUSDT, SOLUSDT");
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ status: 503, json: { error: "offline" } }),
  );
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
    "Could not save",
  );
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "SOLUSDT"] } }),
  );
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("status")).toContainText("saved to the database");
  await expect(page.locator(".watch-panel")).toContainText("SOL");
  await expect(page.locator(".watch-panel")).toContainText(
    "Awaiting exchange validation",
  );
});

test("chosen coin form accepts 29 markets and rejects more than 30", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Manage markets", exact: true }).click();
  const symbols = Array.from({ length: 29 }, (_, index) => `COIN${index}USDT`);
  await page.getByLabel("Chosen coins", { exact: true }).fill([...symbols, "EXTRA1USDT", "EXTRA2USDT"].join(", "));
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("1–30");
  await page.route("**/api/watchlist", (route) => {
    if (route.request().method() === "PUT") expect(route.request().postDataJSON().symbols).toEqual(symbols);
    return route.fulfill({ json: { symbols } });
  });
  await page.getByLabel("Chosen coins", { exact: true }).fill(symbols.join(", "));
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.locator(".watch-panel .count")).toHaveText("29");
});

test("offline API does not appear live and screen has no horizontal overflow", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/system", (route) =>
    route.fulfill({
      status: 503,
      json: { status: "offline", database: "unavailable" },
    }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ status: 503, json: { error: "offline" } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Demo data", exact: true }).click();
  await expect(page.locator(".watch-panel")).toContainText(
    "Default preview list",
  );
  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scroll).toBeLessThanOrEqual(dimensions.width);
  if (isMobile)
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("button", { name: "System & delivery", exact: true })
    .click();
  await expect(page.getByText("Offline", { exact: true })).toBeVisible();
  await expect(page.getByText("Not configured", { exact: true })).toHaveCount(
    2,
  );
});


test("performance analytics stay out of Overview and load only in their own section", async ({
  page,
  isMobile,
}) => {
  let requests = 0;
  await page.route("**/api/performance**", (route) => {
    requests += 1;
    if (route.request().url().includes("/outcomes"))
      return route.fulfill({
        json: {
          outcomes: [
            {
              signal_id: "a".repeat(64),
              symbol: "BTCUSDT",
              direction: "short",
              setup_type: "momentum_breakout",
              trend_regime: "established",
              published_at: 1791255000000,
              status: "target",
              terminal_at: 1791258600000,
              strategy: "MV-TREND-DUAL-v4",
              target_r: "2",
              tp1: "101",
              tp2: "101.5",
              tp3: "102",
              tp1_r: "1",
              tp2_r: "1.5",
              tp3_r: "2",
              tp1_reached: true,
              tp2_reached: true,
              tp3_reached: true,
              mfe_r: "2.1",
              mae_r: "0.2",
              one_r_before_stop: true,
              two_r_before_stop: true,
              intrabar_ambiguous: false,
              source_revised: false,
              observed_bars: 60,
              conservative_r: "2",
            },
          ],
          limit: 500,
        },
      });
    return route.fulfill({
      json: {
        strategy: "MV-TREND-DUAL-v4",
        method: "reference-plan analytics; not exchange fills or account P&L",
        minute_observation: "completed 1m candles",
        ambiguous_policy: "same-minute stop and target is conservative -1R",
        overall: {
          signals: 1,
          observed: 1,
          open: 0,
          target: 1,
          tp1_reached: 1,
          tp2_reached: 1,
          tp3_reached: 1,
          stop: 0,
          protected_be: 0,
          protected_tp1: 0,
          ambiguous: 0,
          source_revised: 0,
          resolved: 1,
          target_rate: "1",
          expectancy_r: "1.55",
          profit_factor: null,
          one_r_before_stop: 1,
          one5_r_before_stop: 1,
          two_r_before_stop: 1,
          one_r_before_stop_rate: "1",
          one5_r_before_stop_rate: "1",
          two_r_before_stop_rate: "1",
          average_mfe_r: "2.1",
          average_mae_r: "0.2",
        },
        cohorts: [
          ["pullback_continuation", "long"],
          ["pullback_continuation", "short"],
          ["momentum_breakout", "long"],
          ["momentum_breakout", "short"],
        ].map(([setup_type, direction]) => {
          const matching =
            setup_type === "momentum_breakout" && direction === "short";
          return {
            setup_type,
            direction,
            signals: matching ? 1 : 0,
            observed: matching ? 1 : 0,
            open: 0,
            target: matching ? 1 : 0,
            tp1_reached: matching ? 1 : 0,
            tp2_reached: matching ? 1 : 0,
            tp3_reached: matching ? 1 : 0,
            stop: 0,
            protected_be: 0,
            protected_tp1: 0,
            ambiguous: 0,
            source_revised: 0,
            resolved: matching ? 1 : 0,
            target_rate: matching ? "1" : null,
            expectancy_r: matching ? "1.55" : null,
            profit_factor: null,
            one_r_before_stop: matching ? 1 : 0,
            one5_r_before_stop: matching ? 1 : 0,
            two_r_before_stop: matching ? 1 : 0,
            one_r_before_stop_rate: matching ? "1" : null,
            one5_r_before_stop_rate: matching ? "1" : null,
            two_r_before_stop_rate: matching ? "1" : null,
            average_mfe_r: matching ? "2.1" : null,
            average_mae_r: matching ? "0.2" : null,
          };
        }),
        by_symbol: [
          {
            symbol: "BTCUSDT",
            signals: 1,
            observed: 1,
            open: 0,
            target: 1,
            tp1_reached: 1,
            tp2_reached: 1,
            tp3_reached: 1,
            stop: 0,
            protected_be: 0,
            protected_tp1: 0,
            ambiguous: 0,
            source_revised: 0,
            resolved: 1,
            target_rate: "1",
            expectancy_r: "1.55",
            profit_factor: null,
            one_r_before_stop: 1,
            one5_r_before_stop: 1,
            two_r_before_stop: 1,
            one_r_before_stop_rate: "1",
            one5_r_before_stop_rate: "1",
            two_r_before_stop_rate: "1",
            average_mfe_r: "2.1",
            average_mae_r: "0.2",
          },
        ],
        decision_blockers: [
          { reason: "NO_PULLBACK_OR_BREAKOUT_TRIGGER", count: 12 },
        ],
        missed_opportunities_6h: [
          {
            reason: "NO_PULLBACK_OR_BREAKOUT_TRIGGER",
            decisions: 6,
            average_max_up_atr: "0.8",
            average_max_down_atr: "2.2",
            moves_up_ge_2atr: 0,
            moves_down_ge_2atr: 3,
          },
        ],
        next_review_milestone: 25,
        completed_decision_windows: 6,
      },
    });
  });

  await page.goto("/");
  await expect(page.getByText("REFERENCE OUTCOME ANALYTICS")).toHaveCount(0);
  expect(requests).toBe(0);

  if (isMobile)
    await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("button", { name: "Performance", exact: true }).click();

  await expect(page.getByText("REFERENCE OUTCOME ANALYTICS")).toBeVisible();
  await expect(page.getByText("Four-engine performance matrix")).toBeVisible();
  await expect(page.getByText("Six-hour movement after NO_SETUP")).toBeVisible();
  await expect(page.locator(".performance-panel .table-symbol").filter({ hasText: "BTC" }).first()).toBeVisible();
  expect(requests).toBeGreaterThanOrEqual(2);
});
