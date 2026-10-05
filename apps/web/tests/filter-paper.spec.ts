import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import baseline from "./fixtures/research-report.json";
import filters from "./fixtures/filter-study.json";

async function open(page: Page, mobile: boolean, tab: string) {
  await page.goto("/");
  if (mobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page.getByRole("button", { name: tab, exact: true }).click();
}
test.beforeEach(async ({ page }) => {
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ status: 503, json: { error: "omitted live feed" } }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({ status: 503, json: { error: "omitted charts" } }),
  );
  await page.route("**/api/watchlist", (route) =>
    route.fulfill({ json: { symbols: ["BTCUSDT", "ETHUSDT"] } }),
  );
  await page.route("**/api/system", (route) =>
    route.fulfill({ json: { status: "ok", database: "connected" } }),
  );
  await page.route("**/api/research", (route) =>
    route.fulfill({ json: baseline }),
  );
});

test("registered filter policies retain historical losses and export exact backend payload", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/research/filters*", (route) =>
    route.fulfill({
      json: route.request().url().includes("file=") ? filters.report : filters,
    }),
  );
  await open(page, isMobile, "Entry filters");
  await expect(page.locator(".study-comparison tbody tr")).toHaveCount(3);
  await expect(page.locator(".study-comparison tbody tr").nth(1)).toContainText(
    "-23.25%",
  );
  await expect(page.locator(".study-comparison tbody tr").nth(2)).toContainText(
    "-33.57%",
  );
  await page.getByLabel("Filter period").selectOption("final_evaluation");
  await page.getByLabel("Filter scenario").selectOption("higher_cost");
  await expect(page.locator(".study-comparison tbody tr").nth(1)).toContainText(
    "-7.66%",
  );
  await page.getByText("All 27 experiments", { exact: true }).click();
  await expect(
    page
      .getByRole("region", { name: "All filter experiments" })
      .locator("tbody tr"),
  ).toHaveCount(27);
  const link = page.getByRole("link", {
    name: "Download filter study",
    exact: true,
  });
  await expect(link).toHaveAttribute(
    "href",
    "/api/research/filters?file=report.json",
  );
  expect(
    await page.evaluate(async () =>
      (await fetch("/api/research/filters?file=report.json")).json(),
    ),
  ).toEqual(filters.report);
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
  ).toBe(true);
});

test("paper observation is absent from the live workflow", async ({
  page,
  isMobile,
}) => {
  await open(page, isMobile, "Entry filters");
  await expect(
    page.getByRole("button", { name: "Forward paper", exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".paper-notice")).toHaveCount(0);
});

test("missing studies never substitute fixture performance", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/research/filters", (route) =>
    route.fulfill({ json: { available: false, report: null } }),
  );
  await open(page, isMobile, "Entry filters");
  await expect(
    page.getByText("No filter study yet", { exact: true }),
  ).toBeVisible();
  await page.route("**/api/research/filters", (route) =>
    route.fulfill({
      json: {
        ...filters,
        report: { ...filters.report, baseline_report_id: "mismatch" },
      },
    }),
  );
  await page
    .getByRole("button", { name: "Historical results", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Entry filters", exact: true })
    .click();
  await expect(page.locator("p[role='alert']")).toContainText("does not match");
});
