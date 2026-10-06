import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const PROFILE = JSON.parse(readFileSync(path.resolve(process.cwd(), "../schema/profiling_output.v1_1.example.json"), "utf8"));

test("전체 일·월·연 기간 탐색과 오늘 Live 선 연결", async ({ page }) => {
  test.skip(process.env.TAL_SENTIMENT_E2E !== "1", "run with TAL_SENTIMENT_E2E=1");
  await page.addInitScript((profile) => {
    localStorage.setItem("takealook.demo-session.v1", JSON.stringify({ userId: "demo_minji", displayName: "김민지", signedInAt: new Date().toISOString() }));
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
  }, PROFILE);
  await page.goto("/stocks/035420");
  const panel = page.locator("#sentiment-panel");
  const timeline = page.getByLabel("감성 시점 탐색");
  const tabs = page.getByRole("tablist", { name: "뉴스 분위기 기간" });
  await expect(page.getByText(/일별 관련 기사 평균.*2016.01.01.*2026.10.04.*BigKinds/)).toBeVisible();
  await expect(timeline.getByRole("button", { name: "2016.01.01", exact: true })).toHaveCount(1);
  await expect(timeline.getByRole("button", { name: "2026.10.04", exact: true })).toHaveCount(1);
  await expect(panel.locator('[data-sentiment-live="today"]')).toHaveCount(1);
  const marker = panel.locator('[data-sentiment-live="today"]');
  expect(await marker.getAttribute("fill")).toEqual(await marker.getAttribute("stroke"));
  const curve = (await panel.locator(".recharts-line-curve").first().getAttribute("d"))!;
  const points = curve.split(/[ML]/).filter(Boolean);
  expect(points).toHaveLength(9);
  const endpoint = points.at(-1)!.split(",").map(Number);
  expect(endpoint[0]).toBeCloseTo(Number(await marker.getAttribute("cx")), 5);
  expect(endpoint[1]).toBeCloseTo(Number(await marker.getAttribute("cy")), 5);
  expect(await timeline.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0);

  // Eight historical points plus today's single dot; historical series has no dots.
  await expect(panel.locator(".recharts-line-dots circle")).toHaveCount(1);
  await timeline.getByRole("button", { name: "2016.01.10", exact: true }).click();
  await expect(panel.locator('[data-sentiment-live="today"]')).toHaveCount(0);
  await expect(timeline.getByRole("button", { name: "2016.01.10", exact: true })).toHaveAttribute("aria-pressed", "true");

  await tabs.getByRole("tab", { name: "월별", exact: true }).click();
  await expect(page.getByText(/기사 수 가중평균/)).toBeVisible();
  await expect(timeline.getByRole("button", { name: "2016.01", exact: true })).toHaveCount(1);
  await expect(panel.locator('[data-sentiment-live="today"]')).toHaveCount(0);
  await expect(timeline.getByRole("button", { name: "오늘 Live", exact: true })).toHaveCount(0);
  await expect(timeline.getByRole("button", { name: "2026.10", exact: true })).toHaveCount(1);
  await expect(page.getByText("월·연 평균은 과거 뉴스와 오늘 Live 기사를 기사 수에 따라 함께 반영합니다.")).toBeVisible();
  await expect(page.getByText(/직전 24시간.*NewsAPI.ai/)).toBeVisible();
  await tabs.getByRole("tab", { name: "연별", exact: true }).click();
  await expect(timeline.getByRole("button", { name: "2016", exact: true })).toHaveCount(1);
  await expect(timeline.getByRole("button", { name: "2026", exact: true })).toHaveCount(1);
  await expect(panel.locator('[data-sentiment-live="today"]')).toHaveCount(0);
  await expect(timeline.getByRole("button", { name: "오늘 Live", exact: true })).toHaveCount(0);
  await timeline.getByRole("button", { name: "2016", exact: true }).click();
  await tabs.getByRole("tab", { name: "연별", exact: true }).press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "일별", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(panel.locator('[data-sentiment-live="today"]')).toHaveCount(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
