/** Layout acceptance: page-level scrolling, exactly three internal stream scrollers, no horizontal overflow, tall document frame. */
import { expect, test } from "@playwright/test";

const WIDTHS = [1920, 1440, 1280, 1024, 768, 390];

async function openExaminedDeal(page: import("@playwright/test").Page) {
  await page.goto("/console");
  await page.getByTestId("preset").selectOption("discrepant");
  await page.getByTestId("create-btn").click();
  await expect(page.getByTestId("deal-id")).toContainText("Created");
  await page.getByTestId("examine-btn").click();
  await expect(page.getByTestId("k-badge")).toContainText("k=2", { timeout: 90_000 });
}

test("console scrolls as a page with only the three stream panels scrolling internally", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await openExaminedDeal(page);
  await page.getByTestId("mode-mock").click();
  await page.getByTestId("negotiate-btn").click();
  await expect(page.getByTestId("payout")).toBeVisible({ timeout: 120_000 });

  const metrics = await page.evaluate(() => {
    const allowed = new Set(["event-list", "ledger-feed", "verifier-log"]);
    const scrollers = [...document.querySelectorAll<HTMLElement>("body *")].filter((el) => {
      const cs = getComputedStyle(el);
      const vertical = /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight + 1;
      const horizontal = /(auto|scroll)/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 1;
      return (vertical || horizontal) && !el.matches("aside");
    }).map((el) => el.closest<HTMLElement>("[data-testid]")?.dataset.testid || el.tagName);
    const offenders = scrollers.filter((s) => !allowed.has(s));
    return {
      pageScrolls: document.documentElement.scrollHeight > window.innerHeight,
      docHeight: document.querySelector<HTMLElement>('[data-testid="doc-frame"]')!.getBoundingClientRect().height,
      scrollers, offenders,
      hscroll: document.documentElement.scrollWidth > window.innerWidth,
    };
  });
  expect(metrics.pageScrolls).toBe(true);
  expect(metrics.hscroll).toBe(false);
  expect(metrics.docHeight).toBeGreaterThanOrEqual(720);
  // only the three stream panels may scroll internally
  expect(metrics.offenders, JSON.stringify(metrics.scrollers)).toEqual([]);

  // ladder, parties, finality fully visible without inner scrollbars
  for (const id of ["tranche-panel", "parties", "finality", "fees", "checklist", "doc-viewer"]) {
    const clipped = await page.getByTestId(id).evaluate((el) => el.scrollHeight > el.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(el).overflowY));
    expect(clipped, id).toBe(false);
  }
  await expect(page.getByTestId("tranche-rung_5")).toBeVisible();
  await expect(page.getByTestId("tranche-fee")).toBeVisible();

  // expand toggle
  await page.getByTestId("presentation-expand").click();
  await expect(page.getByTestId("presentation-expanded-row")).toBeVisible();
  const expandedH = await page.getByTestId("doc-frame").evaluate((el) => el.getBoundingClientRect().height);
  expect(expandedH).toBeGreaterThanOrEqual(900);
  await page.getByTestId("presentation-expand").click();
  await expect(page.getByTestId("presentation-expanded-row")).toHaveCount(0);
});

test("no horizontal scrollbar at any breakpoint", async ({ page }) => {
  await openExaminedDeal(page);
  for (const w of WIDTHS) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.waitForTimeout(250);
    const hscroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    expect(hscroll, `width ${w}`).toBe(false);
    const minH = w >= 768 ? 720 : 520;
    const h = await page.getByTestId("doc-frame").evaluate((el) => el.getBoundingClientRect().height);
    expect(h, `doc frame at ${w}`).toBeGreaterThanOrEqual(minH);
  }
});
