import { test } from "@playwright/test";
// Utility: capture landing + console after a mock run for visual review (screenshots are gitignored).
test("screenshots", async ({ page }) => {
  await page.goto("/");
  await page.waitForTimeout(500);
  await page.screenshot({ path: "screenshots/landing.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "screenshots/landing-mobile.png", fullPage: false });
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/console");
  await page.getByTestId("preset").selectOption("discrepant");
  await page.getByTestId("create-btn").click();
  await page.getByTestId("examine-btn").click();
  await page.getByTestId("k-badge").waitFor({ timeout: 90_000 });
  await page.getByTestId("mode-mock").click();
  await page.getByTestId("negotiate-btn").click();
  await page.getByTestId("payout").waitFor({ timeout: 120_000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: "screenshots/console.png", fullPage: false });
  await page.getByTestId("tranche-rung_4").hover();
  await page.waitForTimeout(400);
  await page.screenshot({ path: "screenshots/console-hover.png", fullPage: false });
});
