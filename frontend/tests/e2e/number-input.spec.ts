import { expect, test, type Page } from "@playwright/test";

// 페르소나 워크스루(2026-10) P2: 수량에 "1.5"를 한 글자씩 치면 점만 지워져 15주로 들어갔다.
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
