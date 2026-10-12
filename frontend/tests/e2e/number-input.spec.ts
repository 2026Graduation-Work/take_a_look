import { expect, test } from "@playwright/test";
import { toHoldingsStep } from "./demo-steps";

test("수량 소수점은 그대로 보이고 넣을 때 막힌다, 전각 숫자는 읽는다", async ({ page }) => {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "현대차 삭제" }).click();
  await page.getByLabel("종목 검색").fill("현대차");
  const quantity = page.getByLabel("수량(주)");
  await quantity.pressSequentially("1.5");
  await expect(quantity).toHaveValue("1.5");
  await page.getByRole("button", { name: "종목 넣기" }).click();
  await expect(page.getByText("수량은 1 이상의 정수로 적어 주세요", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "현대차 삭제" })).toHaveCount(0); // 15주로 들어가지 않았다

  await quantity.fill("１２");
  await expect(quantity).toHaveValue("12");
});
