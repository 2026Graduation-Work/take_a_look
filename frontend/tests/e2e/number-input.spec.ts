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
  await expect(page.getByRole("alert").filter({ hasText: "수량은" })).toContainText("현대차의 수량은 1~999,999,999주의 정수");

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
  await expect(page.getByRole("alert").filter({ hasText: "수량은" })).toContainText("삼성전자의 수량은 1~999,999,999주의 정수");
  await expect(page.getByText("저장했어요")).toHaveCount(0);
});

test("수량과 평균 매입가는 입력하는 동안 천 단위 쉼표를 보이고, 저장 값은 숫자 그대로다", async ({ page }) => {
  await toHoldingsStep(page);
  const price = page.getByLabel("삼성전자 평균 매입가");
  await price.fill("");
  await price.pressSequentially("1234567");
  await expect(price).toHaveValue("1,234,567");
  // 붙여넣은 값도 같게
  await price.fill("71,200");
  await expect(price).toHaveValue("71,200");
  await page.getByLabel("삼성전자 수량").fill("12000");
  await expect(page.getByLabel("삼성전자 수량")).toHaveValue("12,000");
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.holdings.v1")!));
  expect(saved.find((row: { code: string }) => row.code === "005930")).toMatchObject({ quantity: 12000, avgBuyPrice: 71200 });
});

test("잘못된 수량과 평단을 그대로 보이고 기존 저장값을 보존한다", async ({ page }) => {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await page.goto("/portfolio");
  const before = await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"));
  const quantity = page.getByLabel("삼성전자 수량", { exact: true });
  for (const text of ["-1", "1e3", "10abc", "9".repeat(24)]) {
    await quantity.fill(text);
    await expect(quantity).toHaveValue(text);
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "수량은" })).toContainText("수량은 1~999,999,999주의 정수");
    expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  }
  await quantity.fill("15");
  const price = page.getByLabel("삼성전자 평균 매입가", { exact: true });
  for (const text of ["-100", "71200원", "1000000000000"]) {
    await price.fill(text);
    await expect(price).toHaveValue(text);
    await page.getByRole("button", { name: "저장", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "평균 매입가는" })).toContainText("평균 매입가는 0~999,999,999,999원의 정수");
    expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  }
  await price.fill("");
  await price.pressSequentially("-100");
  await expect(price).toHaveValue("-100");
  await price.fill("0");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  await page.reload();
  await expect(price).toHaveValue("0");
});

test("새로 추가한 행도 잘못된 수량을 바꾸지 않고 온보딩 저장을 막는다", async ({ page }) => {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "현대차 삭제" }).click();
  await page.getByLabel("종목 검색").fill("현대차");
  await page.getByLabel("종목 검색").press("Enter");
  const quantity = page.getByLabel("현대차 수량", { exact: true });
  await quantity.pressSequentially("1e3");
  await expect(quantity).toHaveValue("1e3");
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "수량은" })).toContainText("현대차의 수량은 1~999,999,999주의 정수");
  await expect(page).toHaveURL(/\/survey$/);
});
