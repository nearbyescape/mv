// Read-only visual/integration check of an actual committed signal, without mocks.
import { chromium, expect } from "@playwright/test";
import { mkdir, readFile } from "node:fs/promises";
await mkdir("artifacts", { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  const response = await page.request.get("http://127.0.0.1:3100/api/signals");
  expect(response.ok()).toBe(true);
  const feed = await response.json();
  expect(feed.signals.length).toBeGreaterThan(0);
  const signal = feed.signals[0];
  await page.goto("http://127.0.0.1:3100");
  await expect(page.locator(".live-signal-journal")).toContainText(signal.id.slice(0, 12));
  await page.getByRole("button", { name: "Inspect signal", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByText("Publication guards and evidence identity", { exact: true }).click();
  await expect(dialog.getByText(signal.id, { exact: true })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await dialog.getByRole("button", { name: "Download evidence", exact: true }).click();
  const downloaded = JSON.parse(await readFile(await (await downloadPromise).path(), "utf8"));
  expect(downloaded.evidence).toEqual(signal.evidence);
  expect(downloaded.plan_hash).toBe(signal.plan_hash);
  expect(downloaded.entry).toBe(signal.entry);
  await dialog.evaluate(element => element.scrollTop = 0);
  await page.screenshot({ path: "artifacts/live-signal-evidence-desktop.png" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "artifacts/live-signal-evidence-mobile.png" });
  console.log(JSON.stringify({ result: "PASS: actual Binance plan → API → web journal/dialog → intact evidence download", id: signal.id }));
} finally {
  await browser.close();
}
