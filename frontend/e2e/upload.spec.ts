/** Part D: drop three PDFs (the clean fixtures) onto a deal and examine them through the real upload endpoint. */
import { expect, test } from "@playwright/test";
import path from "node:path";

const FIX = path.resolve(__dirname, "../../docs/generated/clean");

test("upload own PDFs and examine", async ({ page }) => {
  await page.goto("/console?upload=1");
  await expect(page.getByTestId("uploader")).toBeVisible();
  await page.getByTestId("preset").selectOption("discrepant");
  await page.getByTestId("create-btn").click();
  await expect(page.getByTestId("deal-id")).toContainText("Created");
  await page.locator('[data-testid="slot-invoice.pdf"] input[type=file]').setInputFiles(path.join(FIX, "invoice.pdf"));
  await page.locator('[data-testid="slot-bill_of_lading.pdf"] input[type=file]').setInputFiles(path.join(FIX, "bill_of_lading.pdf"));
  await page.locator('[data-testid="slot-packing_list.pdf"] input[type=file]').setInputFiles(path.join(FIX, "packing_list.pdf"));
  await page.getByTestId("upload-btn").click();
  await expect(page.getByTestId("k-badge")).toContainText("k=0", { timeout: 120_000 });
  await expect(page.getByTestId("upload-note")).toHaveCount(0);
});
