import { expect, test } from "@playwright/test";
import { toHoldingsStep } from "./demo-steps";

test("데모: 예시 보유를 모두 지워도 보유 없이 시작할 수 있다", async ({ page }) => {
  await toHoldingsStep(page);
  for (const name of ["삼성전자", "카카오", "셀트리온", "현대차"]) await page.getByRole("button", { name: `${name} 삭제` }).click();
  const start = page.getByRole("button", { name: "보유 없이 시작" });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("관심 가는 종목을 검색해 보세요")).toBeVisible();
});
