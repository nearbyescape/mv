import { chromium, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
await page.goto("http://127.0.0.1:3100");
await expect(page.locator(".watch-panel")).toContainText(
  "Saved configuration",
  { timeout: 25000 },
);
let failures = 0;
async function scan(name) {
  const result = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  failures += result.violations.length;
  console.log(
    JSON.stringify({
      name,
      violations: result.violations.map((v) => ({
        id: v.id,
        nodes: v.nodes.map((n) => ({
          target: n.target,
          summary: n.failureSummary,
        })),
      })),
    }),
  );
}
await scan("Desktop overview");
await page.getByRole("button", { name: "Demo data", exact: true }).click();
await page.getByRole("button", { name: "Inspect setup", exact: true }).click();
await scan("Setup dialog");
await page.keyboard.press("Escape");
await page.getByRole("button", { name: "Binance data", exact: true }).click();
await page.getByRole("button", { name: "Switch to dark theme" }).click();
await scan("Dark overview");
await page.getByRole("button", { name: "Switch to light theme" }).click();
await page.setViewportSize({ width: 390, height: 844 });
await expect
  .poll(() =>
    page.locator(".sidebar").evaluate((e) => e.getBoundingClientRect().right),
  )
  .toBeLessThanOrEqual(0);
await scan("Mobile overview");
await browser.close();
if (failures) process.exitCode = 1;
