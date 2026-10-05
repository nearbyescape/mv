import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

test("invitation links work on an already-open sign-in page and clear the URL fragment", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Welcome back", exact: true }),
  ).toBeVisible();
  // An SSR heading precedes hydration. An already-open form is interactive.
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeEnabled();
  await page.goto("/login#invite=" + "a".repeat(43));
  await expect(
    page.getByRole("heading", { name: "Accept your invitation", exact: true }),
  ).toBeVisible();
  expect(new URL(page.url()).hash).toBe("");
  await expect(page.getByLabel("Your name", { exact: true })).toBeVisible();
  expect(
    (
      await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze()
    ).violations,
  ).toEqual([]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("failed sign-in reports the service error and never shows an authenticated state", async ({
  page,
}) => {
  await page.route("**/api/auth/login", (route) =>
    route.fulfill({
      status: 401,
      json: { detail: "Email or password is incorrect" },
    }),
  );
  await page.goto("/login");
  await page
    .getByLabel("Email address", { exact: true })
    .fill("viewer@example.test");
  await page
    .getByLabel("Password", { exact: true })
    .fill("incorrect test password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Email or password is incorrect" }),
  ).toContainText("Email or password is incorrect");
  await expect(
    page.getByRole("heading", { name: "Market overview", exact: true }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => localStorage.getItem("mv_session")),
  ).toBeNull();
});
