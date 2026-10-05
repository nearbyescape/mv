import { chromium, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 1080 },
  deviceScaleFactor: 1,
});
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await page.goto("http://127.0.0.1:3100", { waitUntil: "networkidle" });
await expect(page.locator(".watch-panel")).toContainText("Saved configuration", { timeout: 25000 });
await page.screenshot({
  path: "artifacts/dashboard-desktop.png",
  fullPage: true,
});
await page.getByRole("button", { name: "Switch to dark theme" }).click();
await page.screenshot({ path: "artifacts/dashboard-dark.png", fullPage: true });
await page.getByRole("button", { name: "Switch to light theme" }).click();
await page.setViewportSize({ width: 390, height: 844 });
await expect
  .poll(() =>
    page.locator(".sidebar").evaluate((e) => e.getBoundingClientRect().right),
  )
  .toBeLessThanOrEqual(0);
await page.screenshot({
  path: "artifacts/dashboard-mobile.png",
  fullPage: true,
});
console.log(
  JSON.stringify({
    errors,
    desktop: "artifacts/dashboard-desktop.png",
    mobile: "artifacts/dashboard-mobile.png",
  }),
);
await browser.close();
