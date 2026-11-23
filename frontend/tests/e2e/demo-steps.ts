import { expect, type Page } from "@playwright/test";

export async function toHoldingsStep(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  for (let i = 0; i < 40; i++) {
    if (await page.getByRole("heading", { name: "지금 가진 주식이 있나요?" }).isVisible()) return;
    const done = page.getByRole("button", { name: "완료", exact: true });
    await (await done.isVisible() ? done : page.getByRole("button", { name: "다음", exact: true })).click({ timeout: 2_000 }).catch(() => {});
  }
}

export async function finishDemo(page: Page): Promise<void> {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
}
