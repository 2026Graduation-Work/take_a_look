import { expect, test } from "@playwright/test";
import { toHoldingsStep } from "./demo-steps";

test("수량 소수점은 그대로 보이고 넣을 때 막힌다, 전각 숫자는 읽는다", async ({ page }) => {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "현대차 삭제" }).click();
  // 검색에서 고르면(Enter) 바로 목록 맨 위에 행이 생기고 수량 칸으로 간다
  await page.getByLabel("종목 검색").fill("현대차");
  await page.getByLabel("종목 검색").press("Enter");
  const quantity = page.getByLabel("현대차 수량");
  await expect(quantity).toBeFocused();
  await quantity.pressSequentially("1.5");
  await expect(quantity).toHaveValue("1.5");
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page.getByText("현대차의 수량을 1 이상의 정수로 적어 주세요", { exact: false })).toBeVisible();

  await quantity.fill("１２");
  await expect(quantity).toHaveValue("12");
});

test("보유 목록 줄 안 수정칸도 소수점을 보여 주고 저장할 때 막는다", async ({ page }) => {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await page.goto("/portfolio");
  const quantity = page.getByLabel("삼성전자 수량");
  await quantity.fill("");
  await quantity.pressSequentially("1.5");
  await expect(quantity).toHaveValue("1.5");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByText("삼성전자의 수량과 평균 매입가는 정수로 적어 주세요.")).toBeVisible();
  await expect(page.getByText("저장했어요")).toHaveCount(0);
});
