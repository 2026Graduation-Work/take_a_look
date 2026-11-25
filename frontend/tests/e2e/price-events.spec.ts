import { expect, test, type Page, type Route } from "@playwright/test";
import { eventChartRows, eventDates, priceEventsFixture } from "./price-events-fixture.mjs";

const firstStock = "005930";
const secondStock = "005380";
const [latest, middle, oldest] = eventDates;
const formatted = (date: string) => date.replaceAll("-", ".");
const panel = (page: Page) => page.getByRole("region", { name: "가격이 크게 움직인 날" });
const dates = (page: Page) => page.getByRole("group", { name: "변동일 선택" });
const dateButton = (page: Page, date: string) => dates(page).getByRole("button", { name: formatted(date) });
const disclosures = (page: Page) => panel(page).getByRole("region", { name: "앞뒤 거래일에 나온 공시" });
const kospi = (page: Page) => panel(page).getByRole("region", { name: "같은 날 코스피" });
const selected = (page: Page) => panel(page).locator("[aria-live=polite]");
const marker = (page: Page, date: string) => page.getByRole("button", { name: new RegExp(`^차트에서 ${formatted(date)}`) });
const row = (code: string, date: string, title: string) => ({
  stock_code: code, filed_on: date, title, kind: "earnings", rcept_no: `${date.replaceAll("-", "")}000001`,
});
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
}

type FixtureQuery = (route: Route, url: URL, fixture: unknown) => Promise<void> | undefined;
async function mockContext(page: Page, handle?: FixtureQuery) {
  const calls: URL[] = [];
  await page.route("**/rest/v1/**", async route => {
    const url = new URL(route.request().url());
    const fixture = priceEventsFixture(url);
    if (fixture === null) return route.fallback();
    calls.push(url);
    return handle?.(route, url, fixture) ?? route.fulfill({ json: fixture });
  });
  return {
    counts: () => ({
      market: calls.filter(url => url.pathname.endsWith("/market_status")).length,
      disclosures: calls.filter(url => url.pathname.endsWith("/disclosures")).length,
    }),
  };
}
const isLatestDisclosure = (url: URL) => url.pathname.endsWith("/disclosures") &&
  url.searchParams.getAll("filed_on").includes(`lte.${latest}`);

async function ignoreDisclosureAbort(page: Page) {
  await page.addInitScript(() => {
    const original = window.fetch;
    window.fetch = (input, options) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
      return url.pathname.endsWith("/disclosures") && url.searchParams.has("filed_on")
        ? original(input, { ...options, signal: undefined }) : original(input, options);
    };
  });
}

test.use({ hasTouch: true });

test("chart markers and date buttons share keyboard and touch selection without reads", async ({ page }) => {
  const db = await mockContext(page);
  await page.goto(`/stocks/${firstStock}`);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(disclosures(page)).toContainText("실적");
  await expect(disclosures(page)).toContainText("차트 기준일까지 나온 자료만 확인했어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await expect(panel(page).getByRole("region", { name: "이날 뉴스" })).toContainText("이 자료는 지금 제공하지 않아요.");
  await expect.poll(db.counts).toEqual({ market: 1, disclosures: 3 });
  await expect(dates(page).getByRole("button")).toHaveCount(3);

  await marker(page, oldest).press("Enter");
  await expect(dateButton(page, oldest)).toHaveAttribute("aria-pressed", "true");
  await expect(selected(page)).toContainText(formatted(oldest));
  await expect(kospi(page)).toContainText("+0.75%");
  await dateButton(page, middle).press("Space");
  await expect(marker(page, middle)).toHaveAttribute("aria-pressed", "true");
  await expect(selected(page)).toContainText(formatted(middle));
  await expect(kospi(page)).toContainText("-0.51%");

  await page.getByRole("tab", { name: "1주", exact: true }).click();
  await expect(dateButton(page, middle)).toHaveAttribute("aria-pressed", "true");
  await expect(disclosures(page).getByRole("link").first()).toHaveAttribute("href", /^https:\/\/dart\.fss\.or\.kr\//);
  await disclosures(page).getByRole("button", { name: "더 보기(1)" }).click();
  await expect(disclosures(page).getByRole("link")).toHaveCount(4);
  for (const width of [1280, 1024, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
  await marker(page, latest).tap();
  await expect(selected(page)).toContainText(formatted(latest));
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });
});

test("source failures, empty coverage and one invalid KOSPI day stay local", async ({ page }) => {
  let failed = true;
  const db = await mockContext(page, (route, url, fixture) => {
    if (url.pathname.endsWith("/market_status")) return route.fulfill({
      json: (fixture as Array<{ status_date: string; index_quotes: object[] }>).map(item => item.status_date === middle
        ? { ...item, index_quotes: [{ symbol: "KOSPI", changePercent: "잘못된 숫자" }] } : item),
    });
    if (isLatestDisclosure(url) && failed) {
      failed = false;
      return route.fulfill({ status: 503, json: { message: "unavailable" } });
    }
    if (url.pathname.endsWith("/disclosures") && url.searchParams.getAll("filed_on").some(filter => filter.startsWith("lte.") && filter < `lte.${middle}`)) {
      return route.fulfill({ json: [] });
    }
  });
  await page.goto(`/stocks/${firstStock}`);
  await expect(disclosures(page)).toContainText("자료를 불러오지 못했어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await disclosures(page).getByRole("button", { name: "다시 확인" }).click();
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요. 조회된 자료만 표시해요.");
  expect(db.counts()).toEqual({ market: 1, disclosures: 4 });

  await dateButton(page, middle).click();
  await expect(kospi(page)).toContainText("자료를 불러오지 못했어요.");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await dateButton(page, oldest).click();
  await expect(kospi(page)).toContainText("+0.75%");
  await expect(disclosures(page)).toContainText("이 기간에 수집된 공시가 없어요.");
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
});

test("same-key retry retains previous success and rejects an older late response", async ({ page }) => {
  await page.clock.install();
  await ignoreDisclosureAbort(page);
  let attempt = 0;
  const waiting = deferred();
  const release = deferred();
  await mockContext(page, async (route, url, fixture) => {
    if (!isLatestDisclosure(url)) return route.fulfill({ json: fixture });
    attempt += 1;
    if (attempt === 1) return route.fulfill({ json: [row(firstStock, latest, "처음 내려받은 자료")] });
    if (attempt === 2) {
      waiting.resolve();
      await release.promise;
      return route.fulfill({ json: [row(firstStock, latest, "늦게 끝난 이전 자료")] });
    }
    return route.fulfill({ json: [row(firstStock, latest, "가장 최근에 확인한 자료")] });
  });
  await page.goto(`/stocks/${firstStock}`);
  await expect(disclosures(page)).toContainText("처음 내려받은 자료");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await waiting.promise;
  await expect(disclosures(page)).toContainText("새로 확인하는 중이에요.");
  await expect(disclosures(page)).toContainText("처음 내려받은 자료");
  await page.clock.fastForward(10_100);
  await expect(disclosures(page)).toContainText("이전 조회 자료예요.");
  await disclosures(page).getByRole("button", { name: "다시 확인" }).click();
  await expect(disclosures(page)).toContainText("가장 최근에 확인한 자료");
  const oldResponse = page.waitForResponse(response => isLatestDisclosure(new URL(response.url())));
  release.resolve();
  await (await oldResponse).finished();
  await expect(disclosures(page)).toContainText("가장 최근에 확인한 자료");
  await expect(disclosures(page)).not.toContainText("늦게 끝난 이전 자료");
});

test("switching stocks discards delayed disclosure results from the previous stock", async ({ page }) => {
  await ignoreDisclosureAbort(page);
  const waiting = deferred();
  const release = deferred();
  await mockContext(page, (route, url, fixture) => {
    if (!isLatestDisclosure(url) || url.searchParams.get("stock_code") !== `eq.${firstStock}`) return;
    waiting.resolve();
    return release.promise.then(() => route.fulfill({ json: fixture }));
  });
  await page.goto(`/stocks/${firstStock}`);
  await waiting.promise;
  await page.getByRole("searchbox", { name: "종목 검색" }).fill(secondStock);
  await page.getByRole("link", { name: /현대차 005380/ }).click();
  await expect(page).toHaveURL(`/stocks/${secondStock}`);
  await expect(disclosures(page)).toContainText("현대차 가상 공시 1");
  const oldResponse = page.waitForResponse(response => {
    const url = new URL(response.url());
    return isLatestDisclosure(url) && url.searchParams.get("stock_code") === `eq.${firstStock}`;
  });
  release.resolve();
  await (await oldResponse).finished();
  await expect(disclosures(page)).toContainText("현대차 가상 공시 1");
  await expect(disclosures(page)).not.toContainText("삼성전자 가상 공시");
});

test("legacy snapshots still display chart and skip event source reads", async ({ page }) => {
  const db = await mockContext(page, (route, url) => {
    if (!url.pathname.endsWith("/latest_chart_signal_snapshots")) return;
    const rows = eventChartRows(firstStock);
    for (const response of rows) Reflect.deleteProperty(response.payload.prices, "event_basis");
    return route.fulfill({ json: rows });
  });
  await page.goto(`/stocks/${firstStock}`);
  await expect(page.getByRole("img", { name: /^최근 60거래일 주가 흐름/ })).toBeVisible();
  await expect(panel(page)).toContainText("변동일을 확인할 가격 자료가 부족해요.");
  expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
});

test("a new batch keeps a still-valid selected date and chooses the latest when it disappears", async ({ page }) => {
  let revision = 0;
  await mockContext(page, (route, url, fixture) => {
    if (url.pathname.endsWith("/latest_chart_signal_snapshots")) {
      const charts = eventChartRows(firstStock);
      for (const chart of charts) {
        chart.batch_id = chart.payload.batch_id = `batch-${revision}`;
        if (revision === 2) {
          const { prices } = chart.payload;
          const hash = "b".repeat(64);
          chart.payload.sources.prices_sha256 = prices.event_basis.input_sha256 = hash;
          prices.event_basis.previous_bar = { ...prices.event_basis.previous_bar, close: 11400 };
          prices.history = prices.history.map((bar: { date: string; close: number }) =>
            bar.date < middle ? { ...bar, close: 11400 } : bar);
        }
      }
      return route.fulfill({ json: charts });
    }
    if (url.pathname.endsWith("/disclosures")) {
      const results = fixture as ReturnType<typeof row>[];
      return route.fulfill({ json: results.map(item => ({ ...item, title: `${item.title} (갱신 ${revision})` })) });
    }
  });

  await page.goto(`/stocks/${firstStock}`);
  await dateButton(page, oldest).click();
  await expect(disclosures(page)).toContainText("갱신 0");
  revision = 1;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(disclosures(page)).toContainText("갱신 1");
  await expect(selected(page)).toContainText(formatted(oldest));
  await expect(marker(page, oldest)).toHaveAttribute("aria-pressed", "true");

  revision = 2;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(dateButton(page, oldest)).toHaveCount(0);
  await expect(disclosures(page)).toContainText("갱신 2");
  await expect(selected(page)).toContainText(formatted(latest));
  await expect(marker(page, latest)).toHaveAttribute("aria-pressed", "true");
});

test("a missing trading day keeps both ordinary charts and never creates an event", async ({ page }) => {
  const db = await mockContext(page, (route, url) => {
    if (!url.pathname.endsWith("/latest_chart_signal_snapshots")) return;
    const rows = eventChartRows(firstStock);
    for (const { payload: { prices } } of rows) {
      prices.event_basis.daily_sigma = .05;
      prices.event_basis.previous_bar = { ...prices.event_basis.previous_bar, close: 10000 };
      prices.history = prices.history.map((bar: { date: string; close: number }, index: number) => ({
        ...bar, close: index < 21 ? 10000 : index === 21 ? 11000 : 12100,
      }));
      prices.history.splice(21, 1);
    }
    return route.fulfill({ json: rows });
  });
  await page.goto(`/stocks/${firstStock}`);
  const chart = page.getByRole("img", { name: /^최근 60거래일 주가 흐름/ });
  const unavailable = "변동일을 확인할 가격 자료가 부족해요.";
  for (const horizon of ["1주", "4주"]) {
    const tab = page.getByRole("tab", { name: horizon, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(chart).toBeVisible();
    await expect(panel(page)).toContainText(unavailable);
    await expect(page.getByRole("button", { name: /^차트에서 / })).toHaveCount(0);
  }
  expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
});
