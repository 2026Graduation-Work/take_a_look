import { expect, test, type Page } from "@playwright/test";

// 페르소나 워크스루(2026-10) P1: 데모 예시 보유를 모두 지우면 '저장하고 시작'이 꺼져 대시보드로 갈 수 없었다.
async function toHoldingsStep(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  for (let i = 0; i < 25; i++) {
    if (await page.getByRole("heading", { name: "지금 가진 주식이 있나요?" }).isVisible()) return;
    const done = page.getByRole("button", { name: "완료", exact: true });
    await (await done.isVisible() ? done : page.getByRole("button", { name: "다음", exact: true })).click();
  }
}

test("데모: 예시 보유를 모두 지워도 보유 없이 시작할 수 있다", async ({ page }) => {
  await toHoldingsStep(page);
  for (const name of ["삼성전자", "카카오", "셀트리온", "현대차"]) await page.getByRole("button", { name: `${name} 삭제` }).click();
  const start = page.getByRole("button", { name: "보유 없이 시작" });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("관심 가는 종목을 검색해 보세요")).toBeVisible();
});
