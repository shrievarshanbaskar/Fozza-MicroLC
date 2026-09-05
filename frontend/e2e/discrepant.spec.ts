/**
 * Headless click-through of the discrepant preset on /console: create -> examine -> negotiate (mock by default,
 * LIVE with E2E_MODE=live) -> settlement plan, on one page with no refresh and no console errors.
 * Requires the API on :8000 and the frontend on :3000. Selectors target data-testid only.
 */
import { expect, test } from "@playwright/test";

const MODE = (process.env.E2E_MODE || "mock") as "mock" | "live";

test("discrepant preset end to end without refresh", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));

  await page.goto("/console");
  await expect(page.getByTestId("stat-cards")).toBeVisible();
  await page.getByTestId("preset").selectOption("discrepant");
  await page.getByTestId("create-btn").click();
  await expect(page.getByTestId("deal-id")).toBeVisible();
  await expect(page.getByTestId("deal-id")).toContainText("Created");
  const url = page.url();
  expect(url).toContain("/console?deal=");

  await page.getByTestId("examine-btn").click();
  await expect(page.getByTestId("k-badge")).toContainText("k=2", { timeout: 90_000 });
  await expect(page.getByTestId("badge-bill_of_lading")).toBeVisible();
  await expect(page.getByTestId("rule-R09")).toHaveAttribute("data-hit", "true");
  await expect(page.getByTestId("rule-R15")).toHaveAttribute("data-hit", "true");
  await expect(page.locator('[data-testid^="rule-"][data-hit="true"]')).toHaveCount(2);
  await expect(page.getByTestId("stat-rules-passed")).toContainText("17");

  await page.getByTestId("doc-tab-packing_list").click();
  await page.getByTestId("fields-toggle").click();
  await expect(page.getByTestId("doc-viewer")).toContainText("3900");

  await page.getByTestId(`mode-${MODE}`).click();
  await page.getByTestId("negotiate-btn").click();
  await expect(page.locator('[data-testid="event"][data-actor="verifier"][data-action="pay"]').first()).toBeVisible({ timeout: 120_000 });
  await expect(page.locator('[data-testid="event"][data-action="bounce"]').first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("payout")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("tranche-base")).toHaveAttribute("data-status", /RELEASE/);
  await expect(page.getByTestId("tranche-fee")).toHaveAttribute("data-status", /RELEASE/);
  await expect(page.getByTestId("tranche-rung_5")).toHaveAttribute("data-status", /RETURN/);
  await expect(page.getByTestId("latency").first()).toBeVisible();
  await expect(page.getByTestId("evidence-R15")).toBeVisible();
  await expect(page.getByTestId("verifier-log")).toContainText("Independent Evidence Verified");
  await expect(page.getByTestId("stat-negotiated-price")).toContainText("Discrepancy Adj.");

  expect(page.url()).toBe(url); // same page, no refresh
  const realErrors = errors.filter((e) => !/favicon|net::ERR_ABORTED|Download the React DevTools/i.test(e));
  expect(realErrors, realErrors.join("\n")).toEqual([]);
});

test("landing renders at mobile width and links to the console", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.goto("/");
  await expect(page.getByTestId("hero-cta")).toBeVisible();
  await expect(page.getByTestId("stats-strip")).toBeVisible();
  await expect(page.getByTestId("how-it-works")).toBeVisible();
  await page.getByTestId("hero-cta").click();
  await expect(page).toHaveURL(/\/console/);
  expect(errors).toEqual([]);
});
