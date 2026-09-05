/** Probe (not part of the suite): prove the new build is live by checking Negotiate & Settle is disabled while a lock is in flight. */
import { expect, test } from "@playwright/test";

test("negotiate is greyed out during lock, enabled after", async ({ page, request }) => {
  await page.goto("/console");
  await page.getByTestId("preset").selectOption("discrepant");
  await page.getByTestId("create-btn").click();
  await expect(page.getByTestId("deal-id")).toContainText("Created");
  const dealId = new URL(page.url()).searchParams.get("deal")!;
  await page.getByTestId("examine-btn").click();
  await expect(page.getByTestId("k-badge")).toContainText("k=2", { timeout: 90_000 });

  // before lock: disabled with the reason
  await expect(page.getByTestId("negotiate-btn")).toBeDisabled();
  await expect(page.getByTestId("negotiation-placeholder")).toHaveText("Lock the escrow ladder first");

  await page.getByTestId("lock-top-btn").click();
  await expect(page.getByTestId("lock-btn")).toContainText("Locking…", { timeout: 15_000 });
  await expect(page.getByTestId("negotiate-btn")).toBeDisabled();
  await page.screenshot({ path: "screenshots/lock-in-progress.png", fullPage: false });
  // the API refuses too while the lock is in flight
  const r = await request.get(`http://127.0.0.1:8000/api/deal/${dealId}/negotiate/stream?mode=mock`);
  expect(r.status()).toBe(409);
  console.log(`deal ${dealId}: negotiate disabled during lock; API answered ${r.status()} for negotiate during LOCKING`);

  await expect(page.getByTestId("tranche-fee")).toHaveAttribute("data-status", "LOCKED", { timeout: 200_000 });
  await expect(page.getByTestId("negotiate-btn")).toBeEnabled();
  await page.getByTestId("mode-mock").click();
  await page.getByTestId("negotiate-btn").click();
  await expect(page.getByTestId("payout")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId("tranche-base")).toHaveAttribute("data-status", "RELEASED", { timeout: 60_000 });
  console.log(`deal ${dealId}: settled on ledger after lock`);
});
