import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import baseline from "./fixtures/research-report.json";
import study from "./fixtures/exit-study.json";

async function open(page: Page, mobile: boolean) {
  await page.goto("/");
  if (mobile)
    await page
      .getByRole("button", { name: "Open navigation", exact: true })
      .click();
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page
    .getByRole("button", { name: "Trade diagnostics & exits", exact: true })
    .click();
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/signals**", (route) =>
    route.fulfill({ status: 503, json: { error: "omitted live feed" } }),
  );
  await page.route("**/api/markets**", (route) =>
    route.fulfill({ status: 503, json: { error: "omitted live charts" } }),
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

test("diagnostics compare policies, preserve cost losses and expose registered cohorts accessibly", async ({
  page,
  isMobile,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      message.text() !==
        "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    )
      errors.push(message.text());
  });
  await page.route("**/api/research/study", (route) =>
    route.fulfill({ json: study }),
  );
  await open(page, isMobile);
  await expect(
    page.getByText("27 registered experiments", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".study-comparison tbody tr")).toHaveCount(3);
  await expect(page.getByLabel("Diagnostic period")).toHaveValue("development");
  await expect(page.locator(".study-comparison tbody tr").nth(1)).toContainText(
    "-14.77%",
  );
  await expect(
    page.locator(".study-metrics .research-metric").first(),
  ).toContainText("243");
  await expect(page.locator(".study-cohorts tbody tr")).toHaveCount(3);
  await page.getByLabel("Diagnostic grouping").selectOption("direction");
  await expect(page.locator(".study-cohorts tbody tr")).toHaveCount(2);
  await page.getByLabel("Diagnostic grouping").selectOption("atr_fraction");
  await expect(page.locator(".study-cohorts")).toContainText("1.00%");
  await page
    .getByLabel("Diagnostic grouping")
    .selectOption("aligned_ema50_slope_atr");
  await expect(page.locator(".study-cohorts")).toContainText("0.05 ATR");
  await page.getByLabel("Diagnostic policy").selectOption("stop_target");
  await expect(
    page.locator(".study-metrics .research-metric").first(),
  ).toContainText("161");
  await page.getByLabel("Diagnostic period").selectOption("final_evaluation");
  await page.getByLabel("Diagnostic scenario").selectOption("higher_cost");
  await expect(page.locator(".study-comparison tbody tr").nth(1)).toContainText(
    "-1.75%",
  );
  await expect(page.locator(".study-comparison tbody tr").nth(2)).toContainText(
    "-3.74%",
  );
  await page
    .getByText("Inspect all 27 registered experiments", { exact: true })
    .click();
  await expect(page.locator(".study-all-experiments tbody tr")).toHaveCount(27);
  await page
    .getByText("Study identity and limitations", { exact: true })
    .click();
  await expect(page.getByText(study.report.id, { exact: true })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Trade diagnostic cohorts", exact: true }),
  ).toHaveAttribute("tabindex", "0");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  expect(errors).toEqual([]);
  await page
    .getByRole("button", { name: "Historical results", exact: true })
    .click();
  await expect(page.locator(".research-comparison tbody tr")).toHaveCount(9);
});

test("missing, mismatched and offline study do not replace the original baseline", async ({
  page,
  isMobile,
}) => {
  let state = "empty";
  await page.route("**/api/research/study", (route) =>
    state === "offline"
      ? route.fulfill({ status: 503, json: { error: "Study offline" } })
      : route.fulfill({
          json:
            state === "empty"
              ? { available: false, report: null }
              : {
                  ...study,
                  report: {
                    ...study.report,
                    baseline_report_id: "different-baseline",
                  },
                },
        }),
  );
  await open(page, isMobile);
  await expect(
    page.getByRole("heading", { name: "No exit study yet" }),
  ).toBeVisible();
  await expect(page.locator(".study-comparison")).toHaveCount(0);
  for (state of ["mismatch", "offline"]) {
    await page
      .getByRole("button", { name: "Historical results", exact: true })
      .click();
    await expect(page.locator(".research-metric").first()).toContainText(
      "1.76%",
    );
    await page
      .getByRole("button", { name: "Trade diagnostics & exits", exact: true })
      .click();
    await expect(page.locator(".study-empty [role=alert]")).toContainText(
      state === "offline" ? "Study offline" : "different baseline",
    );
    await expect(page.locator(".study-comparison")).toHaveCount(0);
  }
});

test("study export link and fetched payload preserve exact backend strings through its separate endpoint", async ({
  page,
  isMobile,
}) => {
  await page.route("**/api/research/study**", (route) => {
    const file = new URL(route.request().url()).searchParams.get("file");
    return file
      ? route.fulfill({
          body: JSON.stringify(study.report),
          contentType: "application/json",
          headers: {
            "Content-Disposition": 'attachment; filename="exit-study.json"',
          },
        })
      : route.fulfill({ json: study });
  });
  await open(page, isMobile);
  // Chromium native downloads bypass route interception. Actual downloads are
  // verified separately by capture-exit-study.mjs against the real API.
  await expect(
    page.getByRole("link", { name: "Download exit study", exact: true }),
  ).toHaveAttribute("href", "/api/research/study?file=report.json");
  const downloaded = await page.evaluate(async () =>
    (await fetch("/api/research/study?file=report.json")).json(),
  );
  expect(downloaded).toEqual(study.report);
  expect(downloaded.groups[0].metrics.expectancy_r).toBe(
    study.report.groups[0].metrics.expectancy_r,
  );
});
