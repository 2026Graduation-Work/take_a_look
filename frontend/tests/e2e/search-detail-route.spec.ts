import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";
import { mockSupabaseAuth } from "./supabase-mock";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));
const catalog = [{ code: "005930", name: "삼성전자" }, { code: "005935", name: "삼성전자우" }];

for (const mode of ["데모", "로그인"]) {
  test(`${mode}: 강한 신호 목록 밖 검색은 종목 코드로 이동하고 모호한 검색은 후보를 안내한다`, async ({ page }) => {
    if (mode === "로그인") await mockSupabaseAuth(page, { profile });
    await page.route("**/rest/v1/stocks?**", async (route) => {
      if (new URL(route.request().url()).searchParams.get("select") === "code,name") {
        await route.fulfill({ json: catalog });
      } else await route.fallback();
    });
    await page.route("**/rest/v1/latest_chart_signal_snapshots?**", async (route) => {
      if (new URL(route.request().url()).searchParams.get("select")?.includes("scores:")) {
        await route.fulfill({ json: [] });
      } else await route.fallback();
    });
    if (mode === "데모") await finishDemo(page);
    else {
      await page.goto("/login");
      await page.getByRole("button", { name: "이메일로 시작" }).click();
      await page.getByRole("tab", { name: "회원가입" }).click();
      await page.getByLabel("이름").fill("검색 검사");
      await page.getByLabel("이메일").fill("qa-search@example.com");
      await page.getByLabel("비밀번호").fill("qa-password");
      await page.getByRole("button", { name: "가입하고 시작", exact: true }).click();
      await expect(page).toHaveURL("/");
    }

    const search = page.getByRole("searchbox", { name: "종목 검색" });
    const detailLink = page.getByRole("link", { name: "종목 정보 보기", exact: true });
    for (const query of ["삼성전자", "005930"]) {
      await expect(page.getByText("오늘 보여 줄 모델 신호가 아직 없어요.")).toBeVisible();
      await search.fill(query);
      await expect(detailLink).toHaveAttribute("href", "/stocks/005930");
      await detailLink.click();
      await expect(page).toHaveURL("/stocks/005930");
      await expect(page.getByRole("heading", { name: "삼성전자", exact: true })).toBeVisible();
      await page.getByRole("link", { name: "대시보드", exact: true }).click();
    }

    await expect(page.getByText("오늘 보여 줄 모델 신호가 아직 없어요.")).toBeVisible();
    await search.fill("삼성");
    await expect(page.getByText("검색창에 표시된 후보에서 종목을 골라 주세요.")).toBeVisible();
    await expect(detailLink).toHaveCount(0);
    await page.getByRole("link", { name: "삼성전자 005930", exact: true }).click();
    await expect(page).toHaveURL("/stocks/005930");
    await page.getByRole("link", { name: "대시보드", exact: true }).click();

    await expect(page.getByText("오늘 보여 줄 모델 신호가 아직 없어요.")).toBeVisible();
    await search.fill("전자우");
    await expect(detailLink).toHaveAttribute("href", "/stocks/005935");
    await search.fill("없는종목");
    await expect(detailLink).toHaveCount(0);
    await expect(page.getByText("종목명이나 코드를 확인하고 다시 검색해 주세요.")).toBeVisible();
  });
}
