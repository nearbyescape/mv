// Actual protected local study/API/proxy; no mocked transport or live state changes.
import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

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
  const response = await page.request.get(
    "http://127.0.0.1:3100/api/research/study",
  );
  expect(response.ok()).toBe(true);
  const feed = await response.json();
  expect(feed.available).toBe(true);
  await page.goto("http://127.0.0.1:3100");
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page
    .getByRole("button", { name: "Trade diagnostics & exits", exact: true })
    .click();
  await expect(page.locator(".study-comparison tbody tr")).toHaveCount(3);
  await expect(
    page.getByText("27 registered experiments", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "artifacts/exit-study-desktop.png",
    fullPage: true,
  });
  const pending = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "Download exit study", exact: true })
    .click();
  const downloaded = JSON.parse(
    await readFile(await (await pending).path(), "utf8"),
  );
  expect(downloaded).toEqual(feed.report);
  for (const name of [
    "diagnostics.json",
    "trades.csv",
    "trades.jsonl",
    "dataset-manifest.json",
    "source-audit.json",
  ]) {
    const file = await page.request.get(
      `http://127.0.0.1:3100/api/research/study?file=${name}`,
      { timeout: 60000 },
    );
    expect(file.ok(), name).toBe(true);
    expect(
      createHash("sha256")
        .update(await file.body())
        .digest("hex"),
      name,
    ).toBe(feed.report.files[name]);
  }
  expect(
    (await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze())
      .violations,
  ).toEqual([]);
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  await page.screenshot({
    path: "artifacts/exit-study-dark.png",
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
    path: "artifacts/exit-study-mobile.png",
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
  expect(errors).toEqual([]);
  const result = {
    result:
      "PASS: actual exit study → protected API/proxy → diagnostics/compare → report and all five intact exports; no app console/runtime errors; light/dark/mobile accessibility",
    id: feed.report.id,
  };
  await writeFile(
    "artifacts/exit-study-browser-verification.json",
    JSON.stringify(result, null, 2),
  );
  console.log(JSON.stringify(result));
} finally {
  await browser.close();
}
