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
