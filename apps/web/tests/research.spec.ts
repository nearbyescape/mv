import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fixture from "./fixtures/research-report.json";

async function openResearch(page: Page, mobile: boolean) {
  await page.goto("/");
  if (mobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page.getByRole("button", { name: "Research", exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/signals**", (route) =>
    route.fulfill({
      status: 503,
      json: { error: "live feed omitted in research tests" },
    }),
  );
  await page.route("**/api/system", (route) =>
    route.fulfill({ json: { status: "ok", database: "connected" } }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT"] } }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({ status: 503, json: { error: "live charts omitted" } }),
  );
});

test("registered historical results default to final evaluation and preserve negative sensitivity", async ({
  page,
  isMobile,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    // The unrelated live endpoints above intentionally return 503 in this fixture.
    if (
      message.type() === "error" &&
      message.text() !==
        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    )
      errors.push(message.text());
  });
  await page.route("**/api/research**", (route) =>
    route.fulfill({ json: fixture }),
  );
  await openResearch(page, isMobile);
  await expect(
    page.getByText("Historical simulation · research only", { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Research period")).toHaveValue(
    "final_evaluation",
  );
  await expect(page.locator(".research-metric").first()).toContainText("1.76%");
  await page.getByLabel("Research scenario").selectOption("higher_cost");
  await expect(page.locator(".research-metric").first()).toContainText(
    "-7.03%",
  );
  await page.getByLabel("Research period").selectOption("development");
  await expect(page.locator(".research-metric").first()).toContainText(
    "-41.97%",
  );
  await page.getByLabel("Research scenario").selectOption("baseline");
  await expect(page.locator(".research-metric").first()).toContainText(
    "-27.68%",
  );
  await expect(page.locator(".research-comparison tbody tr")).toHaveCount(9);
  await expect(
    page.getByRole("img", { name: "Simulated portfolio equity", exact: false }),
  ).toBeVisible();
  await expect(
    page.getByText("20 native source discrepancies recorded.", {
      exact: false,
    }),
  ).toBeVisible();
  await page
    .getByText("Report identity and limitations", { exact: true })
    .click();
  await expect(
    page.getByText(fixture.report.dataset_hash, { exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  expect(errors).toEqual([]);
});

test("missing and failed research never show demo performance or a invented report", async ({
  page,
  isMobile,
}) => {
  let fail = false;
  await page.route("**/api/research**", (route) =>
    route.fulfill(
      fail
        ? { status: 503, json: { error: "Research integrity unavailable" } }
        : { json: { available: false, report: null } },
    ),
  );
  await openResearch(page, isMobile);
  await expect(
    page.getByRole("heading", { name: "No backtest report yet", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".research-metrics")).toHaveCount(0);
  fail = true;
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  if (isMobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(
    page.locator(".research-empty").getByRole("alert"),
  ).toContainText("Research integrity unavailable");
  await expect(page.locator(".research-metrics")).toHaveCount(0);
});

test("research exports use server-side report endpoint and preserve exact decimal strings", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/research**", (route) => {
    const file = new URL(route.request().url()).searchParams.get("file");
    return file
      ? route.fulfill({
          body: JSON.stringify(fixture.report),
          headers: {
            "content-type": "application/json",
            "content-disposition":
              'attachment; filename="mv-research-report.json"',
          },
        })
      : route.fulfill({ json: fixture });
  });
  await openResearch(page, isMobile);
  // Native downloads bypass browser route mocks; capture-research.mjs exercises
  // the actual download. Here, verify the link and isolated transport payload.
  await expect(
    page.getByRole("link", { name: "Download report", exact: true }),
  ).toHaveAttribute("href", "/api/research?file=report.json");
  const exported = await page.evaluate(async () =>
    (await fetch("/api/research?file=report.json")).json(),
  );
  expect(exported).toEqual(fixture.report);
  expect(exported.groups[6].metrics.net_pnl).toBe(
    fixture.report.groups[6].metrics.net_pnl,
  );
  expect(exported.dataset_hash).toBe(fixture.report.dataset_hash);
  await expect(
    page.getByRole("link", { name: "Trade CSV", exact: true }),
  ).toHaveAttribute("href", "/api/research?file=trades.csv");
  await expect(
    page.getByRole("link", { name: "Full trade evidence", exact: true }),
  ).toHaveAttribute("href", "/api/research?file=trades.jsonl");
});
