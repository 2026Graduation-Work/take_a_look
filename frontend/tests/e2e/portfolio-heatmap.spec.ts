import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));

async function openHeatmap(page: Page, weights = [86, 14], secondName = "삼성전자") {
  const holdings = [
    { code: "000660", name: "SK하이닉스", quantity: weights[0], avgBuyPrice: 100_000 },
    { code: "005930", name: secondName, quantity: weights[1], avgBuyPrice: 100_000 },
  ];
  await page.addInitScript(({ profile, holdings }) => {
    localStorage.setItem("takealook.demo-session.v1", JSON.stringify({
      userId: "demo_heatmap", displayName: "히트맵 확인", signedInAt: new Date().toISOString(),
    }));
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
    localStorage.setItem("takealook.holdings.v1", JSON.stringify(holdings));
  }, { profile, holdings });
  await page.route(/\/rest\/v1\/latest_chart_signal_snapshots/, (route) => route.fulfill({ json: holdings.map((holding) => ({
    stock_code: holding.code, close: 100_000, as_of: "2026-10-14", status: "available",
    scores: { up: 0.7, neutral: 0.2, down: 0.1 },
  })) }));
  await page.goto("/");
  const map = page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" });
  await expect(map.getByRole("listitem")).toHaveCount(2);
  await expect(map.getByRole("listitem", { name: /삼성전자/ })).toHaveAccessibleName(/상승 신호/);
  return map;
}

// #326 후속: 이름이 안 보이는 칸이 없게 — 모든 칸 44px 이상 + 이름, 넘치면 "그 밖의 N종목"
const CODES = ["000660", "005930", "005380", "035720", "068270", "000270", "051910", "006400", "035420", "105560", "055550", "012330"];
async function openMany(page: Page, weights: number[]) {
  const holdings = weights.map((quantity, index) => ({ code: CODES[index], name: `종목${index + 1}`, quantity, avgBuyPrice: 100_000 }));
  await page.addInitScript(({ profile, holdings }) => {
    localStorage.setItem("takealook.demo-session.v1", JSON.stringify({ userId: "demo_heatmap", displayName: "히트맵 확인", signedInAt: new Date().toISOString() }));
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
    localStorage.setItem("takealook.holdings.v1", JSON.stringify(holdings));
  }, { profile, holdings });
  await page.route(/\/rest\/v1\/latest_chart_signal_snapshots/, (route) => route.fulfill({ json: holdings.map((holding) => ({
    stock_code: holding.code, close: 100_000, as_of: "2026-10-14", status: "available", scores: { up: 0.7, neutral: 0.2, down: 0.1 },
  })) }));
  await page.goto("/");
  return page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" });
}

test.describe("작은 비중 여러 종목(390)", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("1%·3%·5% 종목 10개: 모든 칸이 44px 이상이고 이름이 칸 안에 보인다", async ({ page }) => {
    const map = await openMany(page, [60, 15, 5, 5, 5, 3, 3, 2, 1, 1]);
    const items = map.getByRole("listitem");
    await expect(items).toHaveCount(10);
    const mapBox = (await map.boundingBox())!;
    for (let index = 0; index < 10; index++) {
      const tile = items.nth(index);
      const box = (await tile.boundingBox())!;
      expect(box.height).toBeGreaterThanOrEqual(44);
      expect(box.y + box.height).toBeLessThanOrEqual(mapBox.y + mapBox.height + 0.5);
      const name = tile.getByText(/^종목\d+$/);
      await expect(name).toBeVisible();
      const nameBox = (await name.boundingBox())!;
      expect(nameBox.x + 2).toBeGreaterThanOrEqual(box.x);
      // 이름 줄이 찌그러지지 않고(한 줄 높이) 칸 안에 온전히 있다
      expect(nameBox.height).toBeGreaterThanOrEqual(16);
      expect(nameBox.y).toBeGreaterThanOrEqual(box.y);
      expect(nameBox.y + nameBox.height).toBeLessThanOrEqual(box.y + box.height + 0.5);
      // 아래 줄이 보이면 이름과 겹치지 않는다
      const signal = tile.getByText(/상승\s쪽/);
      if (await signal.isVisible()) expect((await signal.boundingBox())!.y).toBeGreaterThanOrEqual(nameBox.y + nameBox.height - 0.5);
    }
  });

  test("12개면 작은 것들을 '그 밖의 N종목' 칸으로 묶고, 누르면 목록이 열린다(키보드 포함)", async ({ page }) => {
    const map = await openMany(page, [40, 15, 10, 8, 6, 5, 5, 3, 3, 2, 2, 1]);
    const others = map.getByRole("button", { name: /그 밖의 3종목/ });
    await expect(others).toBeVisible();
    for (let index = 1; index <= 9; index++) await expect(map.getByText(`종목${index}`, { exact: true })).toBeVisible();
    const list = page.getByRole("list", { name: "그 밖의 보유 종목" });
    await expect(list).toHaveCount(0);
    await others.click();
    await expect(others).toHaveAttribute("aria-expanded", "true");
    await expect(list.getByRole("link")).toHaveText([/종목11/, /종목10/, /종목12/]); // 같은 금액은 코드 순
    await others.focus();
    await page.keyboard.press("Enter");
    await expect(list).toHaveCount(0);
  });
});

test("치우친 비중에서도 작은 칸은 최소 폭으로 이름을 보이고, 정보는 포인터 오른쪽 위에 온전히 보인다", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const map = await openHeatmap(page);
  await expect(page.getByLabel("보유 종목 정보 선택")).toBeHidden();
  const small = map.getByRole("listitem", { name: /삼성전자/ });
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  await expect(map.getByRole("listitem", { name: /SK하이닉스/ }).getByText("SK하이닉스", { exact: true })).toBeVisible();
  const box = (await small.boundingBox())!;
  const large = (await map.getByRole("listitem", { name: /SK하이닉스/ }).boundingBox())!;
  // 14%지만 이름이 보이게 열 최소 폭(30%)으로 그린다
  expect(box.width / (box.width + large.width)).toBeCloseTo(0.3, 1);
  const point = { x: box.x + box.width / 2, y: box.y + box.height * 0.9 };
  await page.mouse.move(point.x, point.y);
  const popup = page.getByRole("tooltip");
  await expect(popup).toContainText("삼성전자");
  await expect(popup).toContainText("앞으로 4주 상승");
  await expect(popup).toContainText("비중 14%");
  await expect(popup).toContainText("평가금액 140만원");
  const popupBox = (await popup.boundingBox())!;
  expect(popupBox.x).toBeGreaterThan(point.x);
  expect(popupBox.y + popupBox.height).toBeLessThan(point.y);
  expect(await popup.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath("heatmap-desktop.png") });
  await page.mouse.move(point.x, point.y - 32);
  await expect.poll(async () => (await popup.boundingBox())!.y).toBeLessThan(popupBox.y);
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  await page.mouse.move(point.x, point.y - 40);
  await expect(popup).toBeHidden();
  await page.mouse.move(0, 0);
  await small.hover();
  await expect(popup).toBeVisible();
  await page.mouse.move(0, 0);
  await expect(popup).toBeHidden();
  await small.click();
  await expect(page).toHaveURL(/\/stocks\/005930$/);
});

test("99:1 비중과 화면 가장자리에서도 팝업이 화면 밖으로 잘리지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const map = await openHeatmap(page, [99, 1]);
  const small = map.getByRole("listitem", { name: /삼성전자/ });
  const box = (await small.boundingBox())!;
  const large = (await map.getByRole("listitem", { name: /SK하이닉스/ }).boundingBox())!;
  expect(box.width / (box.width + large.width)).toBeCloseTo(0.3, 1);
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  await small.hover();
  const popup = page.getByRole("tooltip");
  await expect(popup).toContainText("비중 1%");
  const bounds = (await popup.boundingBox())!;
  expect(bounds.x).toBeGreaterThanOrEqual(16);
  expect(bounds.x + bounds.width).toBeLessThanOrEqual(374);
  expect(bounds.y).toBeGreaterThanOrEqual(16);
  expect(bounds.y + bounds.height).toBeLessThanOrEqual(828);
  await page.mouse.wheel(0, 100);
  await expect(popup).toBeHidden();
});

test("키보드 포커스로 정보를 읽고 Enter로 상세 화면에 들어간다", async ({ page }) => {
  const map = await openHeatmap(page, [81, 19]);
  const first = map.getByRole("listitem", { name: /SK하이닉스/ });
  await first.focus();
  await expect(page.getByRole("tooltip")).toContainText("비중 81%");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("tooltip")).toContainText("삼성전자");
  await expect(page.getByRole("tooltip")).toContainText("비중 19%");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/stocks\/005930$/);
});

test("타일 공간이 줄었다 넓어져도 이름은 늘 보이고, 좁으면 평가금액 (비중)만 숨긴다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const map = await openHeatmap(page, [60, 40]);
  const small = map.getByRole("listitem", { name: /삼성전자/ });
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  // 칸 안에는 신호 단어 없이 이름과 '평가금액 (비중)'만(10/20)
  await expect(small.getByText("상승", { exact: true })).toHaveCount(0);
  await expect(small.getByText(/만원 \(40%\)$/)).toBeVisible();
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  const tile = (await small.boundingBox())!;
  const weight = small.getByText(/만원 \(40%\)$/);
  if (await weight.isVisible()) {
    const box = (await weight.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(tile.x + tile.width);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(small.getByText(/만원 \(40%\)$/)).toBeVisible();
});

test.describe("터치", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } });
  test("1% 타일은 충분한 크기의 종목 선택으로도 정보를 열 수 있다", async ({ page }) => {
    await openHeatmap(page, [99, 1]);
    const selector = page.getByLabel("보유 종목 정보 선택");
    await expect(selector).toBeVisible();
    const box = (await selector.boundingBox())!;
    expect(box.width).toBeGreaterThanOrEqual(44);
    expect(box.height).toBeGreaterThanOrEqual(44);
    await selector.selectOption("005930");
    await expect(page.getByRole("dialog", { name: "삼성전자 보유 정보" })).toContainText("비중 1%");
  });

  test("짧은 화면에서 팝업 내부를 스크롤해도 닫히지 않는다", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 320 });
    await openHeatmap(page, [99, 1], "삼성전자".repeat(20));
    const selector = page.getByLabel("보유 종목 정보 선택");
    await selector.scrollIntoViewIfNeeded();
    await selector.selectOption("005930");
    const popup = page.getByRole("dialog");
    await expect(popup).toBeVisible();
    expect(await popup.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    await popup.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    await expect.poll(() => popup.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
    await expect(popup).toBeVisible();
    await popup.getByRole("button", { name: "닫기" }).tap();
    await expect(popup).toBeHidden();
  });

  test("탭하면 보유 정보가 열리고 닫기, 바깥 탭, 상세 이동이 가능하다", async ({ page }, testInfo) => {
    const map = await openHeatmap(page);
    const small = map.getByRole("listitem", { name: /삼성전자/ });
    const popup = page.getByRole("dialog", { name: "삼성전자 보유 정보" });
    await small.tap();
    await expect(page).toHaveURL("/");
    await expect(popup).toContainText("비중 14%");
    await page.screenshot({ path: testInfo.outputPath("heatmap-touch.png") });
    await popup.getByRole("button", { name: "닫기" }).tap();
    await expect(popup).toBeHidden();
    await small.tap();
    await page.getByRole("heading", { name: "내 포트폴리오" }).tap();
    await expect(popup).toBeHidden();
    await small.tap();
    await popup.getByRole("link", { name: "종목 상세 보기" }).tap();
    await expect(page).toHaveURL(/\/stocks\/005930$/);
  });
});
