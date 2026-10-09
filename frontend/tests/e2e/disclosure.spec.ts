import { expect, test, type Page } from "@playwright/test";

// 데모 응답(제외 항목: SPAC·관리종목)으로 대시보드까지
async function readyDashboard(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL("/");
}

async function tabTo(page: Page, isTarget: () => boolean) {
  for (let step = 0; step < 60; step += 1) {
    await page.keyboard.press("Tab");
    if (await page.evaluate(isTarget)) return;
  }
  throw new Error("Tab으로 대상에 닿지 못했습니다");
}

test("키보드만으로 시장 흔들림 설명과 제외 항목을 열고 닫는다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await readyDashboard(page);
  const tooltip = page.getByRole("region", { name: "시장 흔들림 설명" });
  const trigger = page.getByRole("button", { name: /시장 흔들림/ });

  await tabTo(page, () => document.activeElement?.textContent?.includes("시장 흔들림") ?? false);
  await expect(tooltip).toBeHidden(); // 포커스만으로는 열리지 않는다
  await page.keyboard.press("Enter");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("지난 1년 중");
  // 트리거 바로 아래에 붙는다
  const [t, p] = [await trigger.boundingBox(), await tooltip.boundingBox()];
  expect(p!.y).toBeGreaterThanOrEqual(t!.y + t!.height);
  expect(p!.y - (t!.y + t!.height)).toBeLessThan(24);
  await page.keyboard.press("Escape");
  await expect(tooltip).toBeHidden();
  await expect(trigger).toBeFocused();

  const summary = page.locator("summary", { hasText: "직접 고른 제외 항목" });
  await expect(summary.locator(".count")).toHaveText(/\d+개/);
  await tabTo(page, () => document.activeElement?.textContent?.includes("직접 고른 제외 항목") ?? false);
  const list = page.locator("details", { has: summary }).getByRole("listitem").first();
  await expect(list).toBeHidden();
  await page.keyboard.press("Enter");
  await expect(list).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(list).toBeHidden();
});

test("마우스는 올려도 열리지 않고, 누르면 열리고 바깥을 누르면 닫힌다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await readyDashboard(page);
  const panel = page.getByRole("region", { name: "시장 흔들림 설명" });
  const trigger = page.getByRole("button", { name: /시장 흔들림/ });
  await trigger.hover();
  await expect(panel).toBeHidden();
  await trigger.click();
  await expect(panel).toBeVisible();
  await page.mouse.click(10, 600);
  await expect(panel).toBeHidden();
});

test.describe("터치", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } });
  test("탭하면 열리고 바깥을 탭하면 닫힌다", async ({ page }) => {
    await readyDashboard(page);
    await page.getByRole("button", { name: /시장 흔들림/ }).tap();
    await expect(page.getByRole("region", { name: "시장 흔들림 설명" })).toBeVisible();
    await page.getByRole("heading", { name: "내 보유 종목의 오늘 신호" }).tap();
    await expect(page.getByRole("region", { name: "시장 흔들림 설명" })).toBeHidden();
  });
});
