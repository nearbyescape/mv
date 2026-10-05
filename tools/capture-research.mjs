// Actual local report through the protected backend/proxy; no mocked replies.
import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile } from "node:fs/promises";
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1080 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const response = await page.request.get("http://127.0.0.1:3100/api/research");
  expect(response.ok()).toBe(true);
  const feed = await response.json();
  expect(feed.available).toBe(true);
  await page.goto("http://127.0.0.1:3100");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await expect(page.locator(".research-comparison tbody tr")).toHaveCount(9);
  await page.screenshot({
    path: "artifacts/research-desktop.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download report", exact: true })
    .click();
  const downloaded = JSON.parse(
    await readFile(await (await downloadPromise).path(), "utf8"),
  );
  expect(downloaded).toEqual(feed.report);
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  await page.screenshot({
    path: "artifacts/research-dark.png",
    fullPage: true,
  });
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to light theme", exact: true })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page
        .locator(".sidebar")
        .evaluate((element) => element.getBoundingClientRect().right),
    )
    .toBeLessThanOrEqual(0);
  await page.screenshot({
    path: "artifacts/research-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  console.log(
    JSON.stringify({
      result:
        "PASS: actual offline report → API/proxy → Research → intact download; light/dark/mobile accessibility",
      id: feed.report.id,
    }),
  );
  expect(errors).toEqual([]);
} finally {
  await browser.close();
}
