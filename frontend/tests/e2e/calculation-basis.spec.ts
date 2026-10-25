import { mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 합성 수급 + 데모 설문만 사용한다. 캡처에 실제 계좌·사용자 응답을 넣지 않는다.
test("더 알아보기: 8축과 가격 흐름을 5칸 단계 막대로, 점수 숫자는 계산 근거 묶음에만", async ({ page }) => {
  await finishDemo(page);
  // 독립 분석형(보유 기간 +0.5, 나머지 0), N09만 발화하도록 합성 응답을 만든다.
  await page.evaluate(() => {
    const profile = JSON.parse(localStorage.getItem("takealook.ips-profile.v1")!);
    for (const axis of profile.style_axes.axes) axis.ratio = axis.axis_id === "turnover" ? 0.5 : 0;
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
  });
  await page.goto("/stocks/000660"); // supabase-stub.mjs BASIS_CODE: 합성 수급·위험도·차트가 있는 종목
  const more = page.locator("details", { has: page.locator("summary", { hasText: "더 알아보기" }) });
  await more.locator("summary").click();
  await expect(more.locator("summary")).toHaveText("더 알아보기");
  const type = page.locator('section[aria-labelledby="more-type"]');
  const axes = type.getByRole("region", { name: "설문 8가지 답" });
  await expect(axes.getByRole("img")).toHaveCount(8);
  // 저장 +0.5(단기 매매 쪽) → 보유 기간 막대에서는 왼쪽 두 번째 칸, 오른쪽 끝은 '길게'
  const turnover = axes.locator("[data-stage]", { hasText: "보유 기간" });
  await expect(turnover).toHaveAttribute("data-stage", "1");
  await expect(turnover).toContainText("단기 매매 쪽");
  await expect(turnover).toContainText("길게");
  await expect(type).not.toContainText(/[−+-]?[01]\.\d|−1|\+1/);
  await expect(type.getByText("설문에서 보유 기간이 짧은 쪽으로 답해 표시했어요.")).toBeVisible();
  await expect(type.getByLabel("내 투자 유형", { exact: true })).toContainText("독립 분석형");
  await expect(type.getByRole("list", { name: "내 성향에 맞춘 읽는 순서" }).getByRole("listitem")).toHaveCount(4);
  const mood = page.locator('section[aria-labelledby="more-mood"]');
  await expect(mood.getByRole("img")).toHaveCount(1);
  await expect(mood).not.toContainText(/\d\.\d/);
  await expect(page.locator('section[aria-labelledby="more-basis"]')).toContainText(/가격 흐름 분위기 점수 [−+]?\d\.\d\d\(범위 −1/);
  // 다섯 묶음 제목은 20px, 묶음 사이 48px
  for (const id of ["more-type", "more-mood", "more-distribution", "more-basis", "more-sources"]) {
    await expect(page.locator(`#${id}`)).toHaveCSS("font-size", "20px");
  }
  const output = process.env.BASIS_SCREENSHOT_DIR;
  if (output) await mkdir(output, { recursive: true });
  for (const width of [1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const bars = axes.getByRole("img");
    const positions = await bars.evaluateAll(els => els.map(el => ({ x: el.getBoundingClientRect().x, y: el.getBoundingClientRect().y })));
    if (width >= 768) {
      expect(positions[0].y).toBe(positions[4].y);
      expect(positions[0].x).toBe(positions[3].x);
      expect(positions[4].x).toBeGreaterThan(positions[0].x);
    } else {
      expect(positions[0].x).toBe(positions[4].x);
      expect(positions[4].y).toBeGreaterThan(positions[3].y);
    }
    if (output) await more.screenshot({ style: "header, nextjs-portal { visibility: hidden !important; }", path: path.join(output, `after-${width}.png`) });
  }
  // 데이터가 없을 때는 이유를 만들어 보이지 않는다.
  await page.goto("/stocks/051910"); // NO_BASIS_CODE: 모델 신호만 있고 합성 수급·위험도는 없음
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  await expect(page.getByText("확인할 것이 뜬 이유", { exact: true })).toHaveCount(0);
});
