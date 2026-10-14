import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));

async function openHeatmap(page: Page, weights = [86, 14]) {
  const holdings = [
    { code: "000660", name: "SK하이닉스", quantity: weights[0], avgBuyPrice: 100_000 },
    { code: "005930", name: "삼성전자", quantity: weights[1], avgBuyPrice: 100_000 },
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
  await expect(map.getByRole("listitem", { name: /삼성전자/ })).toHaveAccessibleName(/상방 신호/);
  return map;
}

test("치우친 비중에서도 타일은 비례하고 정보는 포인터 오른쪽 위에 온전히 보인다", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const map = await openHeatmap(page);
  const small = map.getByRole("listitem", { name: /삼성전자/ });
  await expect(small.getByText("삼성전자", { exact: true })).toBeHidden();
  await expect(map.getByRole("listitem", { name: /SK하이닉스/ }).getByText("SK하이닉스", { exact: true })).toBeVisible();
  const box = (await small.boundingBox())!;
  const large = (await map.getByRole("listitem", { name: /SK하이닉스/ }).boundingBox())!;
  expect(box.width / (box.width + large.width)).toBeCloseTo(0.14, 2);
  const point = { x: box.x + box.width / 2, y: box.y + box.height * 0.9 };
  await page.mouse.move(point.x, point.y);
  const popup = page.getByRole("tooltip");
  await expect(popup).toContainText("삼성전자");
  await expect(popup).toContainText("앞으로 4주 상방");
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
  expect(box.width / (box.width + large.width)).toBeCloseTo(0.01, 2);
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

test("타일 공간이 줄었다가 넓어지면 이름, 신호, 비중을 함께 숨기고 다시 표시한다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const map = await openHeatmap(page, [60, 40]);
  const small = map.getByRole("listitem", { name: /삼성전자/ });
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  await expect(small.getByText("상방", { exact: true })).toBeVisible();
  await expect(small.getByText("비중 40%", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 844 });
  await expect(small.getByText("삼성전자", { exact: true })).toBeHidden();
  await expect(small.getByText("상방", { exact: true })).toBeHidden();
  await expect(small.getByText("비중 40%", { exact: true })).toBeHidden();
  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(small.getByText("삼성전자", { exact: true })).toBeVisible();
  await expect(small.getByText("비중 40%", { exact: true })).toBeVisible();
});

test.describe("터치", () => {
  test.use({ hasTouch: true, viewport: { width: 390, height: 844 } });
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
    await page.getByRole("heading", { name: "내 보유 종목의 오늘 신호" }).tap();
    await expect(popup).toBeHidden();
    await small.tap();
    await popup.getByRole("link", { name: "종목 상세 보기" }).tap();
    await expect(page).toHaveURL(/\/stocks\/005930$/);
  });
});
