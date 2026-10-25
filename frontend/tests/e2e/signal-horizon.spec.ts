import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 대시보드 신호 기간 전환(지도교수 10/15 "왜 4주?"): 기본 4주, 1주로 바꾸면 보유 맵·강한 신호·요약이 같은 기간을 따른다
const row = (horizon: number, down: number, up: number) => ({
  stock_code: "005930", name: "삼성전자", close: 70_000, as_of: "2026-10-16", status: "available",
  scores: { down, neutral: 0.1, up }, horizon,
});

test("앞으로 4주 | 1주 전환: 목록·문구가 바뀌고 이 기기에 기억된다", async ({ page }) => {
  await page.route(/\/rest\/v1\/latest_chart_signal_snapshots/, (route) => {
    const short = route.request().url().includes("horizon=eq.5");
    // 4주는 상승, 1주는 하락으로 서로 다르게
    return route.fulfill({ json: [short ? row(5, 0.7, 0.2) : row(20, 0.2, 0.7)] });
  });
  await page.route(/\/rest\/v1\/stocks\?/, (route) =>
    route.fulfill({ json: [{ code: "005930", market: "KOSPI", risk_grade: 3, risk_flags: [] }] }));
  await finishDemo(page);

  const group = page.getByRole("tablist", { name: "신호 기간" });
  const strong = page.getByRole("region", { name: "신호가 강한 종목" });
  const tile = page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" }).getByRole("listitem", { name: /삼성전자/ });
  await expect(group.getByRole("tab", { name: "4주" })).toHaveAttribute("aria-selected", "true");
  await expect(strong.locator('[data-stock-row="005930"]')).toContainText("상승");
  await expect(tile).toHaveAccessibleName(/앞으로 4주 상승 신호/);
  // 기간 설명은 전환 옆 ⓘ 안에만(10/26). 바깥 한 줄과 오른쪽 목록 제목 아래 'N주 기준'은 없다
  await expect(page.getByText(/짧은 흔들림에 더 민감/)).toHaveCount(0);
  await expect(strong.getByText(/주 기준/)).toHaveCount(0);
  const below = await tile.boundingBox();
  // 예시 보유 4종목 중 카카오(예시 값)만 하락 → 1주로 바꾸면 삼성전자도 하락
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("카카오에 하락 신호가 있어요.");

  await group.getByRole("tab", { name: "1주" }).click();
  await expect(group.getByRole("tab", { name: "1주" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByText(/짧은 흔들림에 더 민감/)).toHaveCount(0);
  expect((await tile.boundingBox())?.y).toBe(below?.y); // 기간을 바꿔도 아래 내용이 움직이지 않는다
  await page.getByRole("button", { name: "1주와 4주 설명 보기" }).click();
  await expect(page.getByText(/1주는 짧은 흔들림에 더 민감하고, 기본은 4주예요\./)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(strong.locator('[data-stock-row="005930"]')).toContainText("하락");
  await expect(tile).toHaveAccessibleName(/앞으로 1주 하락 신호/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^(삼성전자, 카카오|카카오, 삼성전자)에 하락 신호가 있어요\.$/);

  await page.reload();
  await expect(page.getByRole("tablist", { name: "신호 기간" }).getByRole("tab", { name: "1주" })).toHaveAttribute("aria-selected", "true");
});
