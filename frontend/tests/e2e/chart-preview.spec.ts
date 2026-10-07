import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
const rows = snapshots.map((payload: { batch_id: string; stock_code: string; horizon: number }) => ({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload,
}));

test("public predictions retain the original detail UI and both model directions", async ({ page }) => {
  const archivedRows = structuredClone(rows);
  for (const row of archivedRows) delete row.payload.inference.contribution_abs_sum;
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => {
    expect(new URL(route.request().url()).searchParams.get("batch_id")).toBeNull();
    return route.fulfill({ json: archivedRows });
  });
  await page.goto("/stocks/005930");
  await expect(page.getByTestId("preview-provenance")).toHaveText(/모델 검증 전 · 2026.09.21/);
  await expect(page.getByRole("heading", { name: /모델 신호 하방\s*순위 미제공/ })).toBeVisible();
  await expect(page.locator('section[aria-labelledby="checkpoint-title"]')).toBeVisible();
  await expect(page.getByRole("tablist", { name: "판단 근거" }).getByRole("tab")).toHaveCount(4);
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const model = page.getByRole("tabpanel");
  const expected = snapshots.find((s: { horizon: number }) => s.horizon === 20).inference.features;
  await expect(model.getByText("계산값 보기", { exact: true })).toBeVisible();
  await expect(model.getByText(expected[0].contribution.toFixed(4), { exact: true })).not.toBeVisible();
  await model.locator("summary", { hasText: "계산값 보기" }).click();
  // 비중을 모르면(전체 합 없음) 상위 3개를 막대로, 계산값 보기에는 모두
  await expect(model.locator("[data-model-feature]")).toHaveCount(Math.min(3, expected.length));
  for (const [index, feature] of expected.entries()) {
    if (index < 3) {
      const row = model.locator(`[data-model-feature="${feature.name}"]`);
      await expect(row).toContainText(feature.label_ko);
      await expect(row).toContainText("기여도 미제공");
    }
    await expect(model.locator("dd").filter({ hasText: feature.contribution.toFixed(4) })).toBeVisible();
  }
  await expect(model).not.toContainText(/비율 합 100%|뉴스 분위기|회사 체력|사고판 주체/);
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  const horizons = page.locator('section[aria-labelledby="more-horizons"]');
  await expect(horizons.getByRole("listitem")).toHaveCount(2);
  await expect(horizons.getByRole("listitem").filter({ hasText: "5거래일" })).toContainText("↓ 하방");
  await expect(horizons.getByRole("listitem").filter({ hasText: "20거래일" })).toContainText("↓ 하방");
  await expect(page.getByText(/상위 \d+%/)).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("failed public reads show retry, without restoring demo predictions", async ({ page }) => {
  let fail = true;
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill(fail
    ? { status: 503, json: { message: "unavailable" } } : { json: rows }));
  await page.goto("/stocks/005930");
  // PostgREST retries transient 503 responses before exposing the error.
  await expect(page.getByText("차트를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: /모델 신호 미제공\s*순위 미제공/ })).toBeVisible();
  await expect(page.getByText(/상위 \d+%/)).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByTestId("preview-provenance")).toContainText("2026.09.21");
});

test("feature shares use the whole-model denominator and raw values are collapsed", async ({ page }) => {
  const wholeModel = structuredClone(rows);
  for (const row of wholeModel) row.payload.inference.contribution_abs_sum = 1;
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: wholeModel }));
  await page.goto("/stocks/005930");
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const model = page.getByRole("tabpanel");
  const features = wholeModel.find((row: { horizon: number }) => row.horizon === 20).payload.inference.features;
  // 상위 3개 중 비중 10% 이상만 막대, 나머지는 "그 밖의 N개" 한 줄
  const visible = features.slice(0, 3).filter((feature: { contribution: number }) => Math.abs(feature.contribution) * 100 >= 10);
  await expect(model.locator("[data-model-feature]")).toHaveCount(visible.length);
  for (const feature of visible) {
    await expect(model.locator(`[data-model-feature="${feature.name}"]`)).toContainText(
      `기여도 ${(Math.abs(feature.contribution) * 100).toFixed(1)}%`);
  }
  if (features.length > visible.length) await expect(model).toContainText(`그 밖의 ${features.length - visible.length}개 항목`);
  await expect(model.locator("details.disclosure")).not.toHaveAttribute("open", "");
  await model.locator("summary", { hasText: "계산값 보기" }).click();
  await expect(model.locator("dd").first()).toHaveText(features[0].contribution.toFixed(4));
  await expect(model).toContainText("합이 100%가 아닐 수 있어요");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("observed prices remain visible when no historical distribution is available", async ({ page }) => {
  const withoutCases = structuredClone(rows);
  for (const row of withoutCases) row.payload.distribution = {
    ...row.payload.distribution, status: "no_cases", sample_count: 0, stock_count: 0,
    period_start: null, period_end: null, histogram: { bins: [], central_68: null },
  };
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: withoutCases }));
  await page.goto("/stocks/005930");
  await expect(page.getByRole("img", { name: "최근 60거래일 주가 흐름. 수익률 범위 미제공" })).toBeVisible();
  await expect(page.getByText("최근 주가 기록이 아직 없어 흐름을 그리지 않았어요.")).toHaveCount(0);
});

test("dense 2%p distributions keep positive-width bars", async ({ page }) => {
  const denseRows = structuredClone(rows);
  for (const row of denseRows) row.payload.distribution.histogram.bins = Array.from({ length: 1030 }, (_, i) => ({
    left: -60 + i * 2, right: -58 + i * 2, count: i === 30 ? row.payload.distribution.sample_count : 0,
  }));
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: denseRows }));
  await page.goto("/stocks/005930");
  await expect(page.getByTestId("preview-provenance")).toContainText("2026.09.21");
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  const histogram = page.getByRole("img", { name: /과거 유사 신호 .*건의 실현 수익률 분포/ });
  // 빈 칸은 1~99% 구간 밖이라 버려지고, 건수가 있는 한 칸만 폭을 채운다
  await expect(histogram.locator("path")).toHaveCount(1);
  expect(await histogram.locator("path").evaluateAll(paths => paths.every(path => {
    const d = path.getAttribute("d")!;
    const left = Number(d.match(/^M([^,]+),/)![1]);
    const right = Number(d.match(/H([^\s]+)/)![1]);
    return Number.isFinite(left) && right >= left;
  }))).toBe(true);
});

test("another stock reads the latest batch and refreshes after returning to the page", async ({ page }) => {
  let latest = structuredClone(rows);
  for (const row of latest) {
    row.stock_code = row.payload.stock_code = "005380";
    row.payload.stock_name = "현대차";
  }
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => {
    const query = new URL(route.request().url()).searchParams;
    expect(query.get("batch_id")).toBeNull();
    expect(query.get("stock_code")).toContain("005380");
    return route.fulfill({ json: latest });
  });
  await page.goto("/stocks/005380");
  await expect(page.getByTestId("preview-provenance")).toContainText("2026.09.21");
  latest = structuredClone(latest);
  for (const row of latest) {
    row.batch_id = row.payload.batch_id = "new-daily-batch";
    row.payload.data_asof = "2026-09-22";
    row.payload.inference.scores = { down: .1, neutral: .2, up: .7 };
  }
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByTestId("preview-provenance")).toContainText("2026.09.22");
  await expect(page.getByRole("heading", { name: /모델 신호 상방/ })).toBeVisible();
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  for (const h of [5, 20]) await expect(page.locator('section[aria-labelledby="more-horizons"]')
    .getByRole("listitem").filter({ hasText: `${h}거래일` })).toContainText("↑ 상방");
});

for (const [space, target, scores, color] of [
  ["class_0_raw_margin", "하방", { down: .7, neutral: .2, up: .1 }, "var(--color-down)"],
  ["class_1_raw_margin", "중립", { down: .2, neutral: .7, up: .1 }, "var(--color-muted)"],
  ["class_2_raw_margin", "상방", { down: .1, neutral: .2, up: .7 }, "var(--color-up)"],
] as const) {
  test(`contributions explain ${target} with strengthening and weakening factors`, async ({ page }) => {
    const selected = structuredClone(rows);
    for (const row of selected) {
      row.payload.inference.scores = scores;
      row.payload.inference.contribution_space = space;
      row.payload.inference.contribution_abs_sum = 1;
      row.payload.inference.features[0].contribution = .12;
      row.payload.inference.features[1].contribution = -.10;
    }
    await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: selected }));
    await page.goto("/stocks/005930");
    await expect(page.getByRole("heading", { name: new RegExp(`모델 신호 ${target}`) })).toBeVisible();
    await page.getByRole("tab", { name: "모델이 본 이유" }).click();
    const panel = page.getByRole("tabpanel");
    await expect(panel).toContainText(`모델의 ${target} 점수`);
    const third = Math.abs(selected.find((row: { horizon: number }) => row.horizon === 20).payload.inference.features[2].contribution) * 100;
    await expect(panel.locator("[data-model-feature]")).toHaveCount(third >= 10 ? 3 : 2);
    await expect(panel.locator("[data-model-feature]").nth(0)).toContainText(`${target} 강화 · 기여도 12.0%`);
    await expect(panel.locator("[data-model-feature]").nth(1)).toContainText(`${target} 완화 · 기여도 10.0%`);
    // 방향 색은 막대가 맡는다(DESIGN.md 2-1)
    expect(await panel.locator("[data-model-feature]").nth(0).locator("span[style]").first().getAttribute("style")).toContain(`background-color: ${color}`);
    expect(await panel.locator("[data-model-feature]").nth(1).locator("span[style]").first().getAttribute("style")).toContain("background-color: var(--color-muted)");
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
