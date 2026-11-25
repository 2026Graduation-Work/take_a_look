import { expect, test, type Page } from "@playwright/test";
import { TIP_STRIP_TIPS } from "../../lib/tip-strip-tips";
import { STORAGE_KEYS } from "../../lib/storage-keys";
import { finishDemo } from "./demo-steps";

const TODAY = new Date("2026-11-25T13:00:00.000Z");
const BEFORE_MIDNIGHT = new Date("2026-11-25T14:59:00.000Z");
const [first, second, third] = TIP_STRIP_TIPS;

function tipStrip(page: Page) {
  return page.getByRole("region", { name: "알고 계셨나요?" });
}

function marketBar(page: Page) {
  return page.getByRole("region", { name: "시장 브리핑" });
}

async function setTabHidden(page: Page, hidden: boolean) {
  await page.evaluate(hidden => {
    Object.defineProperty(document, "hidden", { value: hidden, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);
}

test("팁은 5초마다 바뀌고 마우스, 가려진 탭, 키보드 포커스에서 멈춘다", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.install({ time: TODAY });
  await finishDemo(page);
  const strip = tipStrip(page);
  await expect(strip).toContainText(first.headline);
  await page.clock.fastForward(5_100);
  await expect(strip).toContainText(second.headline);

  await strip.hover();
  const box = (await strip.boundingBox())!;
  await page.mouse.move(10, box.y + box.height / 2);
  await page.clock.fastForward(20_000);
  await expect(strip).toContainText(second.headline);
  await page.mouse.move(0, 0);
  await page.clock.fastForward(4_000);
  await expect(strip).toContainText(second.headline);
  await page.clock.fastForward(1_100);
  await expect(strip).toContainText(third.headline);

  await setTabHidden(page, true);
  await page.clock.fastForward(20_000);
  await expect(strip).toContainText(third.headline);
  await setTabHidden(page, false);
  await page.clock.fastForward(4_000);
  await expect(strip).toContainText(third.headline);
  await page.clock.fastForward(1_100);
  await expect(strip).toContainText(first.headline);

  await marketBar(page).getByRole("button", { name: /시장 흔들림/ }).focus();
  const link = strip.getByRole("link", { name: "자세히 보기" });
  await page.keyboard.press("Tab");
  await expect(link).toBeFocused();
  await page.clock.fastForward(20_000);
  await expect(link).toBeFocused();
  await expect(strip).toContainText(first.headline);
});

test.describe("터치", () => {
  test.use({ hasTouch: true, isMobile: true, viewport: { width: 390, height: 844 } });

  test("팁 문장을 터치하면 이동 없이 10초 멈췄다가 다시 바뀐다", async ({ page }) => {
    await page.clock.install({ time: TODAY });
    await finishDemo(page);
    const strip = tipStrip(page);
    await expect(strip).toContainText(first.headline);
    await strip.getByText(first.headline, { exact: false }).tap({ position: { x: 8, y: 8 } });
    await expect(page).toHaveURL("/");
    await page.clock.fastForward(9_000);
    await expect(strip).toContainText(first.headline);
    await page.clock.fastForward(1_100);
    await expect(strip).toContainText(second.headline);

    const sentence = strip.getByText(second.headline, { exact: false });
    await sentence.dispatchEvent("pointerdown", { pointerType: "touch" });
    await page.clock.fastForward(12_000);
    await expect(strip).toContainText(second.headline);
    await sentence.dispatchEvent("pointercancel", { pointerType: "touch" });
    await page.clock.fastForward(9_000);
    await expect(strip).toContainText(second.headline);
    await page.clock.fastForward(1_100);
    await expect(strip).toContainText(third.headline);
  });
});

test("문장 바로 뒤의 밑줄 링크를 누르면 계산 예시가 있는 이용 안내로 간다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await finishDemo(page);
  const strip = tipStrip(page);
  const sentence = strip.getByText(first.headline, { exact: false });
  const link = sentence.getByRole("link", { name: "자세히 보기" });
  await expect(sentence).toHaveText(first.headline + " 자세히 보기");
  await expect(link).toHaveCSS("text-decoration-line", "underline");
  await expect(strip.getByRole("link")).toHaveCount(1);
  await sentence.click({ position: { x: 8, y: 8 } });
  await expect(page).toHaveURL("/");
  await link.click();
  await expect(page).toHaveURL("/guide#beginner-tips");
  const section = page.getByRole("region", { name: "알고 계셨나요?" });
  await expect(section.getByRole("heading")).toBeInViewport();
  for (const { headline, description, source } of TIP_STRIP_TIPS) {
    await expect(section).toContainText(headline);
    await expect(section).toContainText(description);
    await expect(section).toContainText(source);
  }
});

test("그만 보면 시장 바를 남기고 본문이 올라오며 서울 자정까지 다른 탭과 이동에도 적용된다", async ({ page, context }) => {
  await page.clock.install({ time: BEFORE_MIDNIGHT });
  await finishDemo(page);
  const strip = tipStrip(page);
  await expect(strip).toBeVisible();
  const originalStrip = (await strip.boundingBox())!;
  const originalMarket = await marketBar(page).boundingBox();
  const summary = page.getByRole("heading", { level: 1 });
  const originalSummary = (await summary.boundingBox())!;

  const otherTab = await context.newPage();
  await otherTab.goto("/performance");
  await expect(tipStrip(otherTab)).toBeVisible();
  await page.bringToFront();
  const hide = strip.getByRole("button", { name: "오늘은 그만 보기" });
  await hide.focus();
  await page.keyboard.press("Enter");
  await expect(strip).toHaveCount(0);
  await expect(tipStrip(otherTab)).toHaveCount(0);
  await expect.poll(async () => (await summary.boundingBox())?.y).toBeCloseTo(originalSummary.y - originalStrip.height, 0);
  expect(await marketBar(page).boundingBox()).toEqual(originalMarket);
  expect(await page.evaluate(() => document.activeElement?.textContent?.startsWith("오늘은 그만 보기"))).toBe(false);
  await otherTab.close();

  await page.getByRole("link", { name: "모델 성적표", exact: true }).click();
  await expect(page).toHaveURL("/performance");
  await expect(page.getByRole("heading", { name: "시장 분위기 지표를 더하면 예측이 나아질까요?" })).toBeVisible();
  await expect(strip).toHaveCount(0);
  await page.reload();
  await expect(marketBar(page)).toBeVisible();
  await expect(strip).toHaveCount(0);

  await page.clock.fastForward(61_000);
  await expect(strip).toContainText(first.headline);
  await page.reload();
  await expect(strip).toBeVisible();
});

test("동작 줄이기 설정에서는 팁 하나를 고정하고 즉시 숨긴다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.clock.install({ time: TODAY });
  await finishDemo(page);
  const strip = tipStrip(page);
  await expect(strip).toContainText(first.headline);
  await page.clock.fastForward(20_000);
  await expect(strip).toContainText(first.headline);
  await strip.getByRole("button", { name: "오늘은 그만 보기" }).click();
  await expect(page.locator('section[aria-label="알고 계셨나요?"]')).toHaveCount(0);
  await expect(marketBar(page)).toBeVisible();
});

test("팁 저장소가 막혀도 현재 앱에서 그만 볼 수 있다", async ({ page }) => {
  await finishDemo(page);
  await page.addInitScript(key => {
    const getItem = Storage.prototype.getItem;
    const setItem = Storage.prototype.setItem;
    Storage.prototype.getItem = function (name) {
      if (name === key) throw new DOMException("저장소 차단", "SecurityError");
      return getItem.call(this, name);
    };
    Storage.prototype.setItem = function (name, value) {
      if (name === key) throw new DOMException("저장소 차단", "SecurityError");
      setItem.call(this, name, value);
    };
  }, STORAGE_KEYS.tipDismissedOn);
  await page.reload();
  const strip = tipStrip(page);
  await expect(strip).toBeVisible();
  await strip.getByRole("button", { name: "오늘은 그만 보기" }).click();
  await expect(strip).toHaveCount(0);
  await page.getByRole("link", { name: "모델 성적표", exact: true }).click();
  await expect(page).toHaveURL("/performance");
  await expect(marketBar(page)).toBeVisible();
  await expect(strip).toHaveCount(0);
});

test("좁은 화면에도 두 지수의 절대값, 등락률, 오래된 데이터 알림을 표시한다", async ({ page }) => {
  await page.clock.install({ time: TODAY });
  await page.route("**/rest/v1/market_status?*", route => {
    return route.fulfill({
      json: [{
        status_date: "2026-11-20",
        condition: "caution",
        volatility_score: 45,
        volume_score: 81,
        index_quotes: [
          { symbol: "KOSPI", label: "KOSPI", value: 4214.17, change: 6.39, changePercent: 0.15 },
          { symbol: "KOSDAQ", label: "KOSDAQ", value: 925.47, change: -7.12, changePercent: -0.76 },
          { symbol: "KOSPI200", label: "KOSPI 200", value: 605.98, change: 0.29, changePercent: 0.05 },
        ],
      }],
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  await finishDemo(page);
  const bar = marketBar(page);
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const value of ["KOSPI", "4,214.17", "+0.15%", "KOSDAQ", "925.47", "-0.76%", "5일 전 데이터예요"]) {
      await expect(bar.getByText(value, { exact: true })).toBeInViewport({ ratio: 1 });
    }
    expect(await bar.evaluate(el => el.scrollWidth - el.clientWidth)).toBe(0);
    await expect(bar.getByText("KOSPI 200", { exact: true })).toHaveCount(0);
    await expect(bar).not.toContainText("거래");
  }

  await expect(bar.getByText("+0.15%", { exact: true })).toHaveCSS("color", "rgb(176, 52, 42)");
  await expect(bar.getByText("-0.76%", { exact: true })).toHaveCSS("color", "rgb(39, 75, 150)");
  const detail = bar.getByRole("button", { name: /시장 흔들림 보통/ });
  expect((await detail.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await detail.click();
  const popover = page.getByRole("region", { name: "시장 흔들림 설명" });
  await expect(popover).toContainText("거래 높음");
  await expect(popover.locator("p").last()).toHaveText("2026.11.20 기준");
  await expect(bar.getByText("2026.11.20 기준", { exact: true })).toHaveCount(0);
  await expect(popover.getByText("2026.11.20 기준", { exact: true })).toHaveCount(1);
});

test("종목 로딩이 1초를 넘기면 팁을 보여 주고 로딩 완료 후에도 띠가 하나다", async ({ page }) => {
  await page.clock.install({ time: TODAY });
  await finishDemo(page);
  await expect(tipStrip(page)).toBeVisible();
  const loadChunks = Promise.withResolvers<void>();
  await page.route("**/_next/static/chunks/*.js", async route => {
    await loadChunks.promise;
    await route.continue();
  });
  await page.getByRole("searchbox", { name: "종목 검색" }).fill("010130");
  const stock = page.getByRole("link", { name: /로딩 확인 종목/ });
  await expect(stock).toBeVisible();
  await stock.click();
  const loading = page.getByRole("main").filter({ hasText: "종목 정보를 불러오는 중이에요." });
  const strip = tipStrip(page);
  try {
    await expect(loading).toBeVisible();
    await expect(strip).toHaveCount(0);
    await page.clock.fastForward(800);
    await expect(strip).toHaveCount(0);
    await page.clock.fastForward(300);
    await expect(strip).toContainText(first.headline);
    await expect(loading).toBeVisible();
  } finally {
    loadChunks.resolve();
  }

  await expect(page.getByRole("heading", { name: "로딩 확인 종목", exact: true })).toBeVisible();
  await expect(marketBar(page)).toBeVisible();
  await expect(strip).toHaveCount(1);
});
