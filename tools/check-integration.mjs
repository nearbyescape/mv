import { chromium, expect } from "@playwright/test";

const browser = await chromium.launch();
const page = await browser.newPage();
const originalResponse = await page.request.get(
  "http://127.0.0.1:3100/api/watchlist",
);
expect(originalResponse.ok()).toBe(true);
const original = (await originalResponse.json()).symbols;
const changed = [...original].reverse();
if (JSON.stringify(changed) === JSON.stringify(original))
  changed.push("SOLUSDT");
try {
  await page.goto("http://127.0.0.1:3100");
  await expect(page.locator(".watch-panel")).toContainText(
    "Saved configuration",
  );
  await page
    .getByRole("button", { name: "Manage markets", exact: true })
    .click();
  await page
    .getByLabel("Chosen coins", { exact: true })
    .fill(changed.join(", "));
  await page.getByRole("button", { name: "Save chosen coins" }).click();
  await expect(page.getByRole("status")).toContainText("saved to the database");
  await page.reload();
  await expect(page.locator(".watch-panel")).toContainText(
    "Saved configuration",
  );
  const persisted = await page.request.get(
    "http://127.0.0.1:3100/api/watchlist",
  );
  expect((await persisted.json()).symbols).toEqual(changed);
  console.log(
    "PASS: browser save → Next proxy → FastAPI → migrated database → reload",
  );
  const blocked = await page.request.put(
    "http://127.0.0.1:3100/api/watchlist",
    {
      data: { symbols: original },
      headers: { Origin: "https://untrusted.example" },
    },
  );
  expect(blocked.status()).toBe(403);
  console.log("PASS: foreign-origin configuration write rejected");
  const signalBlocked = await page.request.post("http://127.0.0.1:3100/api/signals", {
    data: { id: "0".repeat(64), action: "hold" }, headers: { Origin: "https://untrusted.example" },
  });
  expect(signalBlocked.status()).toBe(403);
  console.log("PASS: foreign-origin signal-state write rejected");
} finally {
  const restored = await page.request.put(
    "http://127.0.0.1:3100/api/watchlist",
    {
      data: { symbols: original },
      headers: { Origin: "http://127.0.0.1:3100" },
    },
  );
  expect(restored.ok()).toBe(true);
  await browser.close();
}
