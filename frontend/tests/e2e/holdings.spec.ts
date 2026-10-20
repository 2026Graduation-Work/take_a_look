import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { mockSupabaseAuth } from "./supabase-mock";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));
async function signUp(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이름").fill("보유 사용자");
  await page.getByLabel("이메일").fill("holdings@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL("/");
}

test("로그인: 브라우저 저장본 없이 DB 보유를 읽고 저장 실패가 기존 보유를 지우지 않는다", async ({ page }) => {
  const { tables, holdingErrors } = await mockSupabaseAuth(page, { profile });
  await signUp(page);
  tables.portfolio_holdings.set("005935", { user_id: "app-user-1", stock_code: "005935", quantity: 7,
    avg_buy_price: 50000, is_active: true, display_order: 1, stocks: { name: "삼성전자우" } });
  await page.evaluate(() => localStorage.removeItem("takealook.holdings.v1"));
  await page.goto("/portfolio");
  await expect(page.getByLabel("삼성전자우 수량", { exact: true })).toHaveValue("7");
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.holdings.v1")!)[0].quantity)).toBe(7);
  await page.getByLabel("삼성전자우 수량", { exact: true }).fill("8");
  holdingErrors.upsert = true;
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "보유 종목 저장 실패" })).toBeVisible();
  expect(tables.portfolio_holdings.get("005935")?.is_active).toBe(true);
  expect(tables.portfolio_holdings.get("005935")?.quantity).toBe(7);
  holdingErrors.upsert = false;
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("저장했어요");
  expect(tables.portfolio_holdings.get("005935")?.quantity).toBe(8);
  await page.evaluate(() => localStorage.removeItem("takealook.holdings.v1"));
  await page.reload();
  await expect(page.getByLabel("삼성전자우 수량", { exact: true })).toHaveValue("8");
  await page.goto("/profile");
  await page.getByRole("region", { name: "계정" }).getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByLabel("이메일").fill("holdings@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page).toHaveURL("/");
  await page.goto("/portfolio");
  await expect(page.getByLabel("삼성전자우 수량", { exact: true })).toHaveValue("8");
});

test("로그인: 보유 조회 실패를 빈 목록으로 보이지 않고 저장을 차단한 뒤 재시도한다", async ({ page }) => {
  const { holdingErrors, calls } = await mockSupabaseAuth(page, { profile });
  await signUp(page);
  holdingErrors.read = true;
  await page.goto("/portfolio");
  await expect(page.getByRole("alert").filter({ hasText: "보유 종목 조회 실패" })).toBeVisible();
  await expect(page.getByRole("button", { name: "저장", exact: true })).toBeDisabled();
  await expect(page.getByText("아직 넣은 종목이 없어요.")).toHaveCount(0);
  expect(calls.filter((call) => /^(POST|PATCH).*portfolio_holdings/.test(call))).toEqual([]);
  holdingErrors.read = false;
  await page.getByRole("button", { name: "다시 불러오기" }).click();
  await expect(page.getByText("아직 넣은 종목이 없어요.")).toBeVisible();
});
