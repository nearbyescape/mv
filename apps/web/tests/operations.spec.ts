import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "./fixtures/operations-feed.json";
test.use({ timezoneId: "America/Los_Angeles" });

test.beforeEach(async ({ page }) => {
  await page.route("**/api/system", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        database: "connected",
        engine: fixture.feed.engine,
      },
    }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT"] } }),
  );
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ json: fixture.feed }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({
      status: 503,
      json: { error: "Charts omitted in operations transport tests" },
    }),
  );
});

test("paused IST session remains healthy and Telegram status is visible", async ({
  page,
  isMobile,
}) => {
  const engine = {
    ...fixture.feed.engine,
    state: "session-paused",
    session: {
      enabled: true,
      open: false,
      timezone: "Asia/Kolkata",
      hours: "09:00 AM–11:00 PM IST",
      next_open_at: 1791171000000,
    },
  };
  await page.route("**/api/signals**", (route) =>
    route.fulfill({
      json: { ...fixture.feed, engine, signals: [], slots: [] },
    }),
  );
  await page.route("**/api/system", (route) =>
    route.fulfill({
      json: {
        status: "ok",
        database: "connected",
        engine,
        telegram: "running",
        telegram_delivery: {
          state: "running",
          pending: 1,
          delivered: 2,
          failed: 0,
          unknown: 1,
        },
      },
    }),
  );
  await page.goto("/");
  await expect(page.locator(".preview-banner")).toContainText("Session paused");
  await expect(page.locator(".live-signal-panel")).toContainText("Session paused");
  await expect(page.locator(".live-signal-panel")).not.toContainText(
    "09:00 AM–11:00 PM IST",
  );
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "System & delivery", exact: false })
    .click();
  const telegram = page
    .locator(".service-card")
    .filter({
      has: page.getByRole("heading", {
        name: "Telegram delivery",
        exact: true,
      }),
    });
  await expect(telegram).toContainText(
    "1 queued · 2 delivered · 0 failed · 1 uncertain",
  );
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("cleared journal and inbox show empty states without archived examples", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/history**", (route) =>
    route.fulfill({
      json: { signals: [], next: null, server_time: fixture.feed.server_time },
    }),
  );
  await page.route("**/api/notifications**", (route) =>
    route.fulfill({
      json: {
        notifications: [],
        unread: 0,
        next: null,
        server_time: fixture.feed.server_time,
      },
    }),
  );
  await page.goto("/");
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
  await expect(page.locator(".live-signal-journal tbody tr")).toHaveCount(0);
  await page.getByRole("button", { name: "All dates", exact: true }).click();
  await expect(page.locator(".live-signal-journal tbody tr")).toHaveCount(0);
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "Notifications", exact: false })
    .click();
  await expect(
    page.getByRole("button", { name: "Mark read", exact: true }),
  ).toHaveCount(0);
});

test("complete history pages backend plans and disables operator actions in archived evidence", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/history**", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const rows = fixture.feed.signals.filter(
      (s) => !params.has("symbol") || s.symbol === params.get("symbol"),
    );
    return route.fulfill({
      json: {
        signals: params.has("before_id") ? rows.slice(1) : rows.slice(0, 1),
        next:
          params.has("before_id") || params.has("symbol")
            ? null
            : { before_time: rows[0].published_at, before_id: rows[0].id },
      },
    });
  });
  await page.goto("/");
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation", exact: true })
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
  await page.getByRole("button", { name: "All dates", exact: true }).click();
  await expect(page.locator(".live-signal-journal tbody tr")).toHaveCount(1);
  await page
    .getByRole("button", { name: "Load older signals", exact: true })
    .click();
  await expect(page.locator(".live-signal-journal tbody tr")).toHaveCount(2);
  await expect(page.getByText("End of history", { exact: true })).toBeVisible();
  const second = fixture.feed.signals[1];
  await page
    .getByRole("button", {
      name: "Inspect signal " + second.id.slice(0, 12),
      exact: true,
    })
    .click();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "Mark as held", exact: true }),
  ).toBeDisabled();
  await expect(
    page
      .getByRole("dialog")
      .getByRole("button", { name: "Download evidence", exact: true }),
  ).toBeEnabled();
  await page
    .getByRole("button", { name: "Close signal evidence", exact: true })
    .click();
  await page
    .getByLabel("History market", { exact: true })
    .selectOption("ETHUSDT");
  await expect(page.locator(".live-signal-journal tbody tr")).toHaveCount(1);
  await expect(page.locator(".live-signal-journal tbody tr")).toContainText(
    "ETH",
  );
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
});

test("journal defaults to today's IST signals and date filters compose with history and CSV", async ({
  page,
  isMobile,
}) => {
  await page.clock.install({ time: new Date("2026-10-04T20:00:00Z") });
  const feed = structuredClone(fixture.feed);
  const todayMarket = feed.signals[0].symbol.replace("USDT", "");
  const previousMarket = feed.signals[1].symbol.replace("USDT", "");
  feed.server_time = Date.parse("2026-10-04T20:00:00Z");
  feed.signals[0].published_at = Date.parse("2026-10-04T18:30:00Z");
  feed.signals[1].published_at = Date.parse("2026-10-04T18:29:59.999Z");
  await page.route("**/api/signals**", (r) => r.fulfill({ json: feed }));
  let releaseOld: (() => void) | null = null;
  await page.route("**/api/history**", async (route) => {
    const params = new URL(route.request().url()).searchParams;
    if (params.get("date") === "2026-10-03")
      await new Promise<void>((resolve) => {
        releaseOld = resolve;
      });
    const rows = feed.signals.filter(
      (s) =>
        (!params.has("date") ||
          new Date(s.published_at + 330 * 60_000).toISOString().slice(0, 10) ===
            params.get("date")) &&
        (!params.has("symbol") || s.symbol === params.get("symbol")) &&
        (!params.has("direction") || s.direction === params.get("direction")),
    );
    await route.fulfill({
      json: { signals: rows, next: null, server_time: feed.server_time },
    });
  });
  await page.goto("/");
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
  const date = page.getByLabel("History date in IST", { exact: true });
  const rows = page.locator(".live-signal-journal tbody tr");
  await expect(date).toHaveValue("2026-10-05");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText(todayMarket);
  await date.fill("2026-10-04");
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText(previousMarket);
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  const fs = await import("node:fs/promises");
  const csv = await fs.readFile(
    (await (await downloadPromise).path())!,
    "utf8",
  );
  expect(csv).toContain(feed.signals[1].id);
  expect(csv).not.toContain(feed.signals[0].id);
  await page.getByRole("button", { name: "All dates", exact: true }).click();
  await expect(rows).toHaveCount(2);
  await page
    .getByLabel("History market", { exact: true })
    .selectOption(feed.signals[1].symbol);
  await expect(rows).toHaveCount(1);
  await page.getByLabel("History market", { exact: true }).selectOption("");
  await date.fill("2026-10-03");
  await expect.poll(() => releaseOld !== null).toBe(true);
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(rows).toContainText(todayMarket);
  const staleResponse = page.waitForResponse((r) =>
    r.url().includes("date=2026-10-03"),
  );
  (releaseOld as unknown as () => void)();
  await staleResponse;
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText(todayMarket);
  await date.fill("2026-10-02");
  await expect(
    page.getByText("No signals published on this date", { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page.screenshot({
    path: test.info().outputPath("journal-date-filters.png"),
    fullPage: true,
  });
});

test("Today follows IST midnight while an explicitly selected date stays fixed", async ({
  page,
  isMobile,
}) => {
  await page.clock.install({ time: new Date("2026-10-04T18:29:40Z") });
  await page.route("**/api/signals**", async (route) =>
    route.fulfill({
      json: {
        ...fixture.feed,
        server_time: await page.evaluate(() => Date.now()),
      },
    }),
  );
  const dates: string[] = [];
  await page.route("**/api/history**", (route) => {
    dates.push(new URL(route.request().url()).searchParams.get("date")!);
    return route.fulfill({ json: { signals: [], next: null } });
  });
  await page.goto("/");
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("button", { name: "Signal journal", exact: false })
    .click();
  const date = page.getByLabel("History date in IST", { exact: true });
  await expect(date).toHaveValue("2026-10-04");
  await expect.poll(() => dates.includes("2026-10-04")).toBe(true);
  await page.clock.fastForward(30_000);
  await expect(date).toHaveValue("2026-10-05");
  await expect.poll(() => dates.includes("2026-10-05")).toBe(true);
  await date.fill("2026-10-04");
  await page.clock.fastForward(86_400_000);
  await expect(date).toHaveValue("2026-10-04");
  await page.getByRole("button", { name: "Today", exact: true }).click();
  await expect(date).toHaveValue("2026-10-06");
});

test("web inbox uses committed backend events and reports unavailable delivery honestly", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/notifications*", (route) =>
    route.fulfill({
      json: { notifications: fixture.notifications, unread: 2, next: null },
    }),
  );
  await page.goto("/");
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page
    .getByRole("button", { name: "Notifications", exact: true })
    .click();
  await expect(page.locator(".inbox-item")).toHaveCount(2);
  await expect(
    page.getByRole("heading", { name: "Signal inbox 2 unread", exact: true }),
  ).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.route("**/api/notifications*", (route) =>
    route.fulfill({ status: 503, json: { error: "unavailable" } }),
  );
  await page
    .getByRole("button", { name: "Refresh inbox", exact: true })
    .click();
  await expect(page.locator(".signal-alert[role='alert']")).toContainText(
    "Notification service unavailable",
  );
});
