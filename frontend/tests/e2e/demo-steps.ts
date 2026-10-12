import { expect, type Page } from "@playwright/test";

// 데모로 들어가 '데모 응답'으로 설문을 끝내고 보유 단계("지금 가진 주식이 있나요?")까지 간다.
export async function toHoldingsStep(page: Page): Promise<void> {
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

// 예시 보유 그대로 시작해 대시보드까지
export async function finishDemo(page: Page): Promise<void> {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
}
