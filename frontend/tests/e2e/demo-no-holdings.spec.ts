import { expect, test } from "@playwright/test";
import { finishDemo, toHoldingsStep } from "./demo-steps";

test("데모: 예시 보유를 모두 지워도 보유 없이 시작할 수 있다", async ({ page }) => {
  await toHoldingsStep(page);
  for (const name of ["삼성전자", "카카오", "셀트리온", "현대차"]) await page.getByRole("button", { name: `${name} 삭제` }).click();
  const start = page.getByRole("button", { name: "보유 없이 시작" });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByText("관심 가는 종목을 검색해 보세요")).toBeVisible();
  await page.goto("/stocks/005930");
  await expect(page.getByRole("heading", { name: "삼성전자", exact: true })).toBeVisible();
  await expect(page.getByText(/^보유 \d+주$/)).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { name: "삼성전자", exact: true })).toBeVisible();
  await expect(page.getByText(/^보유 \d+주$/)).toHaveCount(0);
  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "넣은 종목 0개" })).toBeVisible();
});

test("데모: 한 종목만 제거해도 상세에 예시 수량이 다시 나타나지 않는다", async ({ page }) => {
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByRole("button", { name: "삼성전자 삭제", exact: true }).click();
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  await page.goto("/stocks/005930");
  await expect(page.getByRole("heading", { name: "삼성전자", exact: true })).toBeVisible();
  await expect(page.getByText(/^보유 \d+주$/)).toHaveCount(0);
  await page.goto("/stocks/005380");
  await expect(page.getByText("보유 5주", { exact: true })).toBeVisible();
  await page.goto("/stocks/005930");
  await expect(page.getByText(/^보유 \d+주$/)).toHaveCount(0);
});

test("데모: 남아 있는 보유 종목의 수정 수량과 평단은 상세에 유지된다", async ({ page }) => {
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("삼성전자 수량", { exact: true }).fill("7");
  await page.getByLabel("삼성전자 평균 매입가", { exact: true }).fill("12000");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  await page.goto("/stocks/005930");
  await expect(page.getByText("보유 7주", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("보유 7주", { exact: true })).toBeVisible();
  await page.goto("/portfolio");
  await expect(page.getByLabel("삼성전자 수량", { exact: true })).toHaveValue("7");
  await expect(page.getByLabel("삼성전자 평균 매입가", { exact: true })).toHaveValue("12,000");
});
