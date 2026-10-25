import { mkdir } from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 합성 수급 + 데모 설문만 사용한다. 캡처에 실제 계좌·사용자 응답을 넣지 않는다.
test("계산 근거: 4+4 축, 위치 막대, 유형 이유와 체크포인트 이유를 반응형으로 표시한다", async ({ page }) => {
  await finishDemo(page);
  // 독립 분석형(보유 기간 +0.5, 나머지 0), N09만 발화하도록 합성 응답을 만든다.
  await page.evaluate(() => {
    const profile = JSON.parse(localStorage.getItem("takealook.ips-profile.v1")!);
    for (const axis of profile.style_axes.axes) axis.ratio = axis.axis_id === "turnover" ? 0.5 : 0;
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
  });
  await page.goto("/stocks/000660"); // supabase-stub.mjs BASIS_CODE: 합성 수급·위험도·차트가 있는 종목
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  const basis = page.locator('section[aria-labelledby="more-basis"]');
  const axes = basis.getByRole("region", { name: "설문 8가지 답" });
  await expect(axes.getByRole("meter")).toHaveCount(8);
  await expect(basis.getByText("가격 흐름 분위기", { exact: true })).toBeVisible();
  await expect(basis.getByText(/합친 점수가/)).toBeVisible();
  await expect(axes).not.toContainText(/0\.00|0\.50/);
  await expect(basis.getByText("설문에서 보유 기간이 짧은 쪽으로 답해 표시했어요.")).toBeVisible();
  await expect(basis.getByLabel("내 투자 유형", { exact: true })).toContainText("독립 분석형");
  await expect(basis.getByRole("list", { name: "내 성향에 맞춘 읽는 순서" }).getByRole("listitem")).toHaveCount(4);
  const output = process.env.BASIS_SCREENSHOT_DIR;
  if (output) await mkdir(output, { recursive: true });
  for (const width of [1280, 768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    const meters = axes.getByRole("meter");
    const positions = await meters.evaluateAll(els => els.map(el => ({ x: el.getBoundingClientRect().x, y: el.getBoundingClientRect().y })));
    if (width >= 768) {
      expect(positions[0].y).toBe(positions[4].y);
      expect(positions[0].x).toBe(positions[3].x);
      expect(positions[4].x).toBeGreaterThan(positions[0].x);
    } else {
      expect(positions[0].x).toBe(positions[4].x);
      expect(positions[4].y).toBeGreaterThan(positions[3].y);
    }
    // 한 점수마다 2px짜리 위치 표시 하나: 채운 구간을 만들지 않는다.
    await expect(meters.first()).toHaveAttribute("aria-valuenow", "0");
    const pointer = meters.nth(2).locator("span.bg-ink");
    expect((await pointer.boundingBox())!.width).toBe(2);
    if (output) await basis.screenshot({ style: "header, nextjs-portal { visibility: hidden !important; }", path: path.join(output, `after-with-checkpoint-${width}.png`) });
  }
  // 데이터가 없을 때는 이유를 만들어 보이지 않는다.
  await page.goto("/stocks/051910"); // NO_BASIS_CODE: 모델 신호만 있고 합성 수급·위험도는 없음
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  await expect(basis.getByText("확인할 것이 뜬 이유", { exact: true })).toHaveCount(0);
  if (output) {
    await page.setViewportSize({ width: 1280, height: 900 });
    await basis.screenshot({ style: "header, nextjs-portal { visibility: hidden !important; }", path: path.join(output, "after-without-checkpoint-1280.png") });
  }
});
