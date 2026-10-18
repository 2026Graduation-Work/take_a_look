import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));
test("실제 성적표: 출처·기간·운영 모델과의 구분, 급변 구간 미산출, 모바일 표", async ({ page }, testInfo) => {
  await page.addInitScript((value) => {
    localStorage.setItem("takealook.demo-session.v1", JSON.stringify({ userId: "demo-test", displayName: "테스터", signedInAt: new Date().toISOString() }));
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(value));
  }, profile);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/performance");
  const main = page.getByRole("main");
  await expect(main.getByRole("heading", { name: "시장 분위기 지표를 더하면 예측이 나아질까요?" })).toBeVisible();
  await expect(main.getByText("예시 데이터", { exact: true })).toHaveCount(0);
  await expect(main.getByText(/지금 운영 중인 모델의 성적은 아니에요/)).toBeVisible();
  await expect(main.getByText(/2019\.01\.07~2025\.12\.30/)).toBeVisible();
  await expect(main.getByRole("table")).toContainText("170개");
  await expect(main.getByRole("table")).toContainText("174개");
  await page.getByRole("tab", { name: "고변동일 상위 20%" }).click();
  await expect(main.getByRole("table")).toContainText("미산출");
  await expect(main.getByText(/별도 백테스트 미산출/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("performance-mobile.png"), fullPage: true });
});
