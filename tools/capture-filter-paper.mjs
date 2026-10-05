import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto("http://127.0.0.1:3100");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page
    .getByRole("button", { name: "Entry filters", exact: true })
    .click();
  await expect(page.locator(".study-comparison tbody tr")).toHaveCount(3);
  const feed = await (
    await page.request.get("http://127.0.0.1:3100/api/research/filters")
  ).json();
  expect(feed.available).toBe(true);
  expect(feed.report.groups).toHaveLength(27);
  const pending = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download filter study", exact: true })
    .click();
  expect(
    JSON.parse(await readFile(await (await pending).path(), "utf8")),
  ).toEqual(feed.report);
  for (const file of Object.keys(feed.report.files)) {
    const response = await page.request.get(
      `http://127.0.0.1:3100/api/research/filters?file=${file}`,
      { timeout: 60000 },
    );
    expect(response.ok()).toBe(true);
    expect(
      createHash("sha256")
        .update(await response.body())
        .digest("hex"),
    ).toBe(feed.report.files[file]);
  }
  await page.screenshot({
    path: "artifacts/filter-study-desktop.png",
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Forward paper", exact: true })
    .click();
  await expect(page.locator(".study-comparison tbody tr")).toHaveCount(6);
  const paper = await (
    await page.request.get("http://127.0.0.1:3100/api/paper")
  ).json();
  expect(paper.available).toBe(true);
  expect(paper.run.state).toBe("observing");
  expect(paper.run.observed_minutes).toBeGreaterThanOrEqual(2);
  expect(paper.run.assessment_ready).toBe(false);
  await page.screenshot({
    path: "artifacts/forward-paper-desktop.png",
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  await page.screenshot({
    path: "artifacts/forward-paper-dark.png",
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Entry filters", exact: true })
    .click();
  await page.screenshot({
    path: "artifacts/filter-study-dark.png",
    fullPage: true,
  });
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  const mobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
  });
  const mp = await mobile.newPage();
  await mp.goto("http://127.0.0.1:3100");
  await mp
    .getByRole("button", { name: "Open navigation", exact: true })
    .click();
  await mp.getByRole("button", { name: "Research", exact: true }).click();
  await expect
    .poll(() =>
      mp.locator(".sidebar").evaluate((e) => e.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(0);
  for (const [tab, name] of [
    ["Entry filters", "filter-study"],
    ["Forward paper", "forward-paper"],
  ]) {
    await mp.getByRole("button", { name: tab, exact: true }).click();
    await expect(mp.locator(".study-comparison tbody tr")).toHaveCount(
      tab === "Entry filters" ? 3 : 6,
    );
    expect(
      await mp.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    expect(
      (
        await new AxeBuilder({ page: mp })
          .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
          .analyze()
      ).violations,
    ).toEqual([]);
    await mp.screenshot({
      path: `artifacts/${name}-mobile.png`,
      fullPage: true,
    });
  }
  expect(errors).toEqual([]);
  const result = {
    report_id: feed.report.id,
    forward_run_id: paper.run.id,
    observed_symbol_minutes: paper.run.observed_minutes,
    closed_trades: paper.run.sleeves.reduce((n, s) => n + s.closed_trades, 0),
    checks:
      "Actual API and website: original filter report native download/all export hashes; six real forward journal sleeves; light/dark/mobile Axe and no overflow/runtime errors passed. No mocked transport.",
  };
  await writeFile(
    "artifacts/filter-paper-browser-verification.json",
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result, null, 2));
} finally {
  await browser.close();
}
