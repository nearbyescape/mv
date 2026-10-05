// Visual QA uses an actual backend-generated test response; never writes live data.
import { chromium, expect } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
const fixture = JSON.parse(await readFile("apps/web/tests/fixtures/engine-feed.json", "utf8"));
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
await page.route("**/api/signals**", route => route.fulfill({ json: fixture }));
await page.goto("http://127.0.0.1:3100");
await page.getByRole("button", { name: "Inspect signal", exact: true }).click();
const dialog = page.getByRole("dialog");
await expect(dialog).toBeVisible();
await dialog.evaluate(element => {
  const label = document.createElement("p");
  label.textContent = "CONTROLLED BACKEND TEST FIXTURE · NOT A LIVE BINANCE SIGNAL";
  label.style.cssText = "padding:12px;margin-bottom:15px;background:#f5f1e4;color:#665730;font-size:11px;border-radius:6px";
  element.prepend(label);
});
await page.screenshot({ path: "artifacts/signal-evidence-test-fixture-desktop.png" });
await page.setViewportSize({ width: 390, height: 844 });
await page.screenshot({ path: "artifacts/signal-evidence-test-fixture-mobile.png" });
await browser.close();
console.log("Captured explicitly labeled controlled signal-evidence fixtures");
