import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { featureLabel } from "../../lib/featureLabels.ts";
import { contributionPercent, contributionWord } from "../../lib/display.ts";

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
  // 과거 비슷한 경우: pack의 실제 기간과 횟수, 범위 끝은 오늘 종가 기준 원
  await expect(page.getByTestId("preview-provenance")).toHaveText(/^2026.09.21 기준\. \d{4}년 \d+월~\d{4}년 \d+월 중 오늘과 점수가 비슷했던 [\d,]+번\([\d,]+개 종목\)의 결과예요\. 원은 오늘 종가 기준이에요\.$/);
  await expect(page.locator('section[aria-labelledby="glance-title"]')).toContainText(/%\s*\(약 [\d,]+원\)/);
  await page.getByRole("button", { name: "모델 신호 설명 보기" }).click();
  await expect(page.getByText(/세 점수를 내고 가장 큰 쪽/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("heading", { name: /^모델 신호 하락\s*앞으로 4주$/ })).toBeVisible();
  await expect(page.locator('section[aria-labelledby="checkpoint-title"]')).toBeVisible();
  await expect(page.getByRole("tablist", { name: "판단 근거" }).getByRole("tab")).toHaveCount(4);
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const model = page.getByRole("tabpanel");
  const expected = snapshots.find((s: { horizon: number }) => s.horizon === 20).inference.features;
  await expect(model.getByText("계산 근거", { exact: true })).toBeVisible();
  await expect(model.getByText(expected[0].contribution.toFixed(4), { exact: true })).not.toBeVisible();
  await model.locator("summary", { hasText: "계산 근거" }).click();
  // 비중을 모르면(전체 합 없음) 상위 3개를 막대로, 계산 근거에는 모두
  await expect(model.locator("[data-model-feature]")).toHaveCount(Math.min(3, expected.length));
  for (const [index, feature] of expected.entries()) {
    if (index < 3) {
      const row = model.locator(`[data-model-feature="${feature.name}"]`);
      await expect(row).toContainText(featureLabel(feature.name, feature.label_ko));
      await expect(row).toContainText(contributionWord(feature.contribution, "상승")); // 미리보기 표본은 class_2(상승). 전체 합이 없으면 방향만
    }
    await expect(model.locator("dd").nth(index)).toContainText("미제공");
  }
  await expect(model).not.toContainText(/비율 합 100%|뉴스 분위기|회사 체력|사고판 주체/);
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  await expect(page.locator("[data-zero-line]")).toHaveCount(1);
  await expect(page.locator('section[aria-labelledby="more-distribution"]')).not.toContainText(/이하|이상/);
  await expect(page.locator('section[aria-labelledby="more-basis"]')).toContainText(/모델 신호 기준선: 위 [\d,]+원, 아래 [\d,]+원/);
  const horizons = page.locator('section[aria-labelledby="more-horizons"]');
  await expect(horizons.getByRole("listitem")).toHaveCount(2);
  await expect(horizons.getByRole("listitem").filter({ hasText: "5거래일" })).toContainText("↓ 하락");
  await expect(horizons.getByRole("listitem").filter({ hasText: "20거래일" })).toContainText("↓ 하락");
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
  await expect(page.getByRole("heading", { name: /^모델 신호 미제공$/ })).toBeVisible();
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
  // 비중은 전체 피처 합 기준으로 표시하고, 나머지 제공 항목은 계산 근거로 이동한다.
  const visible = features.slice(0, 3);
  await expect(model.locator("[data-model-feature]")).toHaveCount(visible.length);
  for (const feature of visible) {
    await expect(model.locator(`[data-model-feature="${feature.name}"]`)).toContainText(contributionWord(feature.contribution, "상승", 1));
  }
  await expect(model).not.toContainText("기여도");
  if (features.length > visible.length) await expect(model).toContainText(`제공된 다른 ${features.length - visible.length}개 항목`);
  await expect(model.locator("details.disclosure")).not.toHaveAttribute("open", "");
  await model.locator("summary", { hasText: "계산 근거" }).click();
  await expect(model.locator("dd").first()).toContainText(contributionPercent(features[0].contribution, 1));
  await expect(model).toContainText("각 항목이 점수를 바꾼 크기를 모두 더해 100%");
  await expect(model.locator("[data-model-feature]")).not.toContainText(["영향 비중", "관측값", "관측값"]);
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
  await expect(page.getByRole("heading", { name: /모델 신호 상승/ })).toBeVisible();
  await page.locator("summary", { hasText: "더 알아보기" }).click();
  for (const h of [5, 20]) await expect(page.locator('section[aria-labelledby="more-horizons"]')
    .getByRole("listitem").filter({ hasText: `${h}거래일` })).toContainText("↑ 상승");
});

for (const [space, target, scores, color] of [
  ["class_0_raw_margin", "하락", { down: .7, neutral: .2, up: .1 }, "var(--color-down)"],
  ["class_1_raw_margin", "중립", { down: .2, neutral: .7, up: .1 }, "var(--color-muted)"],
  ["class_2_raw_margin", "상승", { down: .1, neutral: .2, up: .7 }, "var(--color-up)"],
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
    await expect(panel.locator("[data-model-feature]")).toHaveCount(3);
    await expect(panel.locator("[data-model-feature]").nth(0)).toContainText(`${target} 점수를 크게 높였어요.`);
    await expect(panel.locator("[data-model-feature]").nth(1)).toContainText(`${target} 점수를 크게 낮췄어요.`);
    // 방향 색은 막대가 맡는다(DESIGN.md 2-1)
    expect(await panel.locator("[data-model-feature]").nth(0).locator("span[style]").first().getAttribute("style")).toContain(`background-color: ${color}`);
    expect(await panel.locator("[data-model-feature]").nth(1).locator("span[style]").first().getAttribute("style")).toContain("background-color: var(--color-muted)");
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

for (const total of [undefined, 0]) {
  test(`missing or zero denominator (${total}) never invents a share`, async ({ page }) => {
    const selected = structuredClone(rows);
    for (const row of selected) {
      row.payload.inference.contribution_abs_sum = total;
      if (total === 0) for (const feature of row.payload.inference.features) feature.contribution = 0;
    }
    await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: selected }));
    await page.goto("/stocks/005930");
    await page.getByRole("tab", { name: "모델이 본 이유" }).click();
    const panel = page.getByRole("tabpanel");
    await expect(panel.locator("[data-model-feature]")).toHaveCount(3);
    await expect(panel.locator("[data-model-feature] div[aria-hidden]")).toHaveCount(3);
    await expect(panel.locator("[data-model-feature]").first()).not.toContainText("영향 비중");
    if (total === 0) await expect(panel.locator("[data-model-feature]").first()).toContainText("바꾸지 않았어요");
  });
}

test("shares use the entire denominator while bars retain relative scaling and calculation basis stays compact", async ({ page }) => {
  const selected = structuredClone(rows);
  for (const row of selected) {
    row.payload.inference.contribution_abs_sum = 1;
    row.payload.inference.features[0].contribution = .12;
    row.payload.inference.features[1].contribution = -.12;
    row.payload.inference.features[2].contribution = -1.2e-7;
    row.payload.inference.features[2].value = null;
  }
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: selected }));
  await page.goto("/stocks/005930");
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const panel = page.getByRole("tabpanel");
  const items = panel.locator("[data-model-feature]");
  for (const index of [0, 1]) {
    await expect(items.nth(index)).toContainText(index === 0 ? "크게 높였어요" : "크게 낮췄어요");
    expect(await items.nth(index).locator("span[style]").getAttribute("style")).toContain("width: 50%");
  }
  await expect(items.nth(2)).toContainText("조금 낮췄어요");
  await expect(items).not.toContainText(["관측값", "관측값", "관측값"]);
  await panel.getByText("계산 근거", { exact: true }).click();
  await expect(panel.locator("dd").nth(0)).toHaveText("높임, 12%");
  await expect(panel.locator("dd").nth(1)).toHaveText("낮춤, 12%");
  await expect(panel.locator("dd").nth(2)).toHaveText("낮춤, 0.1% 미만");
  await expect(panel).not.toContainText("+0.1200");
  await expect(panel).not.toContainText("모델에 넣은 값:");
  await expect(panel.locator("dd")).toHaveCount(5);
  await expect(panel).not.toContainText("계산 방법:");
  const headingRow = items.first().locator("div").first();
  const rightText = headingRow.locator("span").last();
  const [rowBounds, textBounds] = await Promise.all([headingRow.boundingBox(), rightText.boundingBox()]);
  expect(Math.abs(rowBounds!.x + rowBounds!.width - textBounds!.x - textBounds!.width)).toBeLessThanOrEqual(1);
  for (const width of [320, 390, 1200]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});


test("feature explanations use the common info icon, hover remains open over the popup and Escape restores focus", async ({ page }) => {
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: rows }));
  await page.goto("/stocks/005930");
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const first = page.getByRole("tabpanel").locator("[data-model-feature]").first();
  const trigger = first.getByRole("button", { name: /설명 보기$/ });
  await expect(trigger).toContainText("ⓘ");
  const description = page.getByRole("region", { name: /설명$/ });
  await expect(description).toHaveCount(0);
  await trigger.hover();
  await expect(description).toBeVisible();
  await expect(description).toContainText("변화율");
  await description.hover();
  await expect(description).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(description).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(description).toBeVisible();
  await page.keyboard.press("Escape");
  await trigger.hover();
  await expect(description).toBeVisible();
  await page.mouse.move(0, 0);
  await expect(description).toHaveCount(0);
  await trigger.click();
  await expect(description).toBeVisible();
  await trigger.click();
  await expect(description).toHaveCount(0);
});

test.describe("feature explanation touch", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } });
  test("tap opens the same info popup and outside tap dismisses it", async ({ page }) => {
    await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: rows }));
    await page.goto("/stocks/005930");
    await page.getByRole("tab", { name: "모델이 본 이유" }).tap();
    await page.getByRole("tabpanel").locator("[data-model-feature]").first().getByRole("button", { name: /설명 보기$/ }).tap();
    const popup = page.getByRole("region", { name: /설명$/ });
    await expect(popup).toBeVisible();
    const bounds = (await popup.boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390);
    await page.getByRole("tab", { name: "모델이 본 이유" }).tap();
    await expect(popup).toHaveCount(0);
  });
});


test("mobile feature names stay on one line and detailed copy explains size words", async ({ page }) => {
  const selected = structuredClone(rows);
  for (const row of selected) {
    row.payload.inference.contribution_space = "class_0_raw_margin";
    row.payload.inference.contribution_abs_sum = 1;
    row.payload.inference.features[0] = { ...row.payload.inference.features[0], name: "cord_20", contribution: -.12 };
  }
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: selected }));
  await page.goto("/stocks/005930");
  await page.getByRole("tab", { name: "모델이 본 이유" }).click();
  const panel = page.getByRole("tabpanel");
  const item = panel.locator('[data-model-feature="cord_20"]');
  const label = item.getByRole("button", { name: "20일 등락과 거래량 동행 설명 보기" }).locator("span").first();
  for (const width of [320, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    const dimensions = await label.evaluate(node => ({ height: node.getBoundingClientRect().height, lineHeight: parseFloat(getComputedStyle(node).lineHeight) }));
    expect(dimensions.height).toBeLessThanOrEqual(dimensions.lineHeight + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await expect(panel.getByText("하락 점수를 높이고 낮춘 정도예요. 예측 확률이나 수익률이 아니에요.", { exact: true })).toBeVisible();
  await panel.getByText("계산 근거", { exact: true }).click();
  await expect(panel).toContainText("10% 이상이면 ‘크게’, 그보다 작으면 ‘조금’");
  await expect(panel).toContainText("각 항목이 점수를 바꾼 크기를 모두 더해 100%");
  await expect(panel.locator("dd").first()).toHaveText("낮춤, 12%");
});
