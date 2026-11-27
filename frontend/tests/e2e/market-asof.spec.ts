import { expect, test } from "@playwright/test";

for (const scenario of [
  { label: "같은 최신 기준일", marketDate: "2026-09-21", now: "2026-09-22T12:00:00+09:00", showLocal: false, stale: false },
  { label: "서로 다른 기준일", marketDate: "2026-09-22", now: "2026-09-23T12:00:00+09:00", showLocal: true, stale: false },
  { label: "시장 바와 같지만 갱신 지연", marketDate: "2026-09-21", now: "2026-09-24T19:00:00+09:00", showLocal: true, stale: true },
]) {
  test(`기준일 안내: ${scenario.label}`, async ({ page }) => {
    await page.clock.setFixedTime(new Date(scenario.now));
    await page.route("**/rest/v1/market_status?**", route => route.fulfill({ json: {
      status_date: scenario.marketDate,
      condition: "stable",
      volatility_score: 50,
      volume_score: 50,
      index_quotes: [
        { symbol: "KOSPI", label: "KOSPI", value: 2500, change: 10, changePercent: 0.4 },
        { symbol: "KOSDAQ", label: "KOSDAQ", value: 750, change: 3, changePercent: 0.4 },
      ],
    } }));
    await page.goto("/stocks/000660");
    const market = page.getByRole("region", { name: "시장 브리핑", exact: true });
    await expect(market).toContainText(`시세 ${scenario.marketDate.replaceAll("-", ".")} 종가 기준`);
    await expect(market).toContainText("실시간 아님");
    if (scenario.stale) await expect(market).toContainText("3일 전 데이터예요");
    else await expect(market).not.toContainText("일 전 데이터예요");
    const header = page.getByRole("region", { name: "SK하이닉스", exact: true });
    await expect(header.getByText("275,000원", { exact: true })).toBeVisible();
    await expect(header.getByText("2026.09.21 종가 기준", { exact: true })).toHaveCount(scenario.showLocal ? 1 : 0);
    const overview = page.getByRole("tabpanel", { name: "한눈에 보기", exact: true });
    await expect(overview.getByText("2026.09.21 종가 기준", { exact: true })).toHaveCount(scenario.showLocal ? 1 : 0);

    await page.getByRole("tab", { name: "모델이 본 이유", exact: true }).click();
    const provenance = page.getByTestId("preview-provenance");
    if (scenario.showLocal) {
      await expect(provenance).toContainText("2026.09.21 기준.");
      await expect(provenance).toContainText("원은 2026.09.21 종가 기준이에요.");
    } else {
      await expect(provenance).not.toContainText("2026.09.21 기준.");
      await expect(provenance).not.toContainText("종가 기준이에요.");
    }

    await page.getByRole("tab", { name: "회사 상태", exact: true }).click();
    const financial = page.getByRole("tabpanel", { name: "회사 상태", exact: true }).getByRole("region", { name: "회사 상태", exact: true });
    await financial.getByText("계산 근거", { exact: true }).click();
    await expect(financial.getByText(/^재무 /)).toContainText("2026");
    await expect(financial.getByText(/PER\/PBR 주가 2026\.09\.21 종가 기준/)).toHaveCount(scenario.showLocal ? 1 : 0);
    await expect(page.getByRole("link", { name: "가상 공시 테스트" })).toBeVisible();
    await market.getByRole("button", { name: /시장 흔들림/ }).click();
    await expect(page.getByRole("region", { name: "시장 흔들림 설명" })).not.toContainText(scenario.marketDate.replaceAll("-", "."));
    await page.keyboard.press("Escape");
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await expect(market.getByText("실시간 아님", { exact: true })).toBeVisible();
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  });
}
