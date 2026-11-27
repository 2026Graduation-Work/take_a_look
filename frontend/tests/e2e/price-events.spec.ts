import assert from "node:assert/strict";
import { join } from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";
import type { DatedClose } from "../../lib/price-events";
import { eventChartRows, eventDates, eventNews, eventNewsSelect, isEventNewsQuery, priceEventsFixture } from "./price-events-fixture.mjs";

const firstStock = "005930";
const secondStock = "005380";
const [latest, middle, oldest] = eventDates;
const formatted = (date: string) => date.replaceAll("-", ".");
const panel = (page: Page) => page.getByRole("dialog", { name: "가격이 크게 움직인 날" });
const eventStatus = (page: Page) => page.getByRole("status", { name: "변동일 조회 상태" });
const disclosures = (page: Page) => panel(page).getByRole("region", { name: "앞뒤 거래일에 나온 공시" });
const news = (page: Page) => panel(page).getByRole("region", { name: "이날 뉴스" });
const kospi = (page: Page) => panel(page).getByRole("region", { name: "같은 날 코스피" });
const selected = (page: Page) => panel(page).locator("p[aria-live=polite]");
const marker = (page: Page, date: string) => page.getByRole("button", { name: new RegExp(`^차트에서 ${formatted(date)}`) });
const openEvent = (page: Page, date = latest) => marker(page, date).press("Enter");
const row = (code: string, date: string, title: string) => ({
  stock_code: code, filed_on: date, title, kind: "earnings", rcept_no: `${date.replaceAll("-", "")}000001`,
});
function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
}

type FixtureQuery = (route: Route, url: URL, fixture: unknown) => Promise<void> | undefined;
const isMarket = (url: URL) => url.pathname.endsWith("/market_status");
const isDisclosure = (url: URL) => url.pathname.endsWith("/disclosures");
const isChart = (url: URL) => url.pathname.endsWith("/latest_chart_signal_snapshots");
const isNewsOn = (url: URL, date: string) => isEventNewsQuery(url) && url.searchParams.get("article_date") === `eq.${date}`;
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
      market: calls.filter(isMarket).length,
      disclosures: calls.filter(isDisclosure).length,
    }),
    newsCalls: () => calls.filter(isEventNewsQuery),
  };
}
const isLatestDisclosure = (url: URL) => isDisclosure(url) &&
  url.searchParams.getAll("filed_on").includes(`lte.${latest}`);
const focusRefresh = (page: Page) => page.evaluate(() => window.dispatchEvent(new Event("focus")));
const retry = (source: ReturnType<typeof disclosures>) => source.getByRole("button", { name: "다시 확인" });
const chart = (page: Page) => page.getByRole("img", { name: "최근 주가 흐름", exact: true });
const serverError = (route: Route) => route.fulfill({ status: 503, json: { message: "internal fixture detail" } });

async function capturePanel(page: Page, name: string) {
  const directory = process.env.PRICE_EVENT_EVIDENCE_DIR;
  if (!directory) return;
  await page.screenshot({ path: join(directory, `${name}-${page.viewportSize()?.width}.png`) });
}

async function ignoreEventSourceAbort(page: Page) {
  await page.addInitScript(newsSelect => {
    const original = window.fetch;
    window.fetch = (input, options) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
      const disclosure = url.pathname.endsWith("/disclosures") && url.searchParams.has("filed_on");
      const article = url.pathname.endsWith("/news_articles") && url.searchParams.get("select") === newsSelect;
      return disclosure || article
        ? original(input, { ...options, signal: undefined }) : original(input, options);
    };
  }, eventNewsSelect);
}

test.use({ hasTouch: true });

test("hover opens the date popup and the pointer can cross into its links", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.clock.install();
  await mockContext(page);
  await page.goto(`/stocks/${firstStock}`);
  await expect(marker(page, latest)).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  await expect(page.getByRole("group", { name: "변동일 선택" })).toHaveCount(0);
  await expect(page.getByText("앞뒤 거래일 공시", { exact: true })).toHaveCount(0);

  await marker(page, latest).hover();
  await expect(selected(page)).toContainText(formatted(latest));
  const firstLink = disclosures(page).getByRole("link").first();
  await expect(firstLink).toHaveAttribute("href", /^https:\/\/dart\.fss\.or\.kr\//);
  await expect(news(page)).toContainText("삼성전자 가상 뉴스 1");
  await capturePanel(page, "hover-popup");
  const box = await firstLink.boundingBox();
  assert.ok(box);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 12 });
  await page.clock.runFor(1000);
  await expect(panel(page)).toBeVisible();
  await disclosures(page).getByRole("button", { name: "더 보기(1)" }).click();
  await expect(disclosures(page).getByRole("link")).toHaveCount(4);
  await page.mouse.move(1, 420);
  await page.clock.runFor(1000);
  await expect(panel(page)).toHaveCount(0);
});

test("keyboard and touch open chart markers without additional reads", async ({ page }) => {
  const newsEnabled = (process.env.NEXT_PUBLIC_PRICE_EVENT_NEWS_ENABLED ?? "1") === "1";
  const db = await mockContext(page);
  await page.goto(`/stocks/${firstStock}`);
  await expect.poll(db.counts).toEqual({ market: 1, disclosures: 3 });
  await expect(page.getByRole("button", { name: /^차트에서 / })).toHaveCount(3);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(disclosures(page)).toContainText("실적");
  await expect(disclosures(page)).toContainText("차트 기준일까지 나온 자료만 확인했어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  if (newsEnabled) {
    await expect(news(page)).toContainText("삼성전자 가상 뉴스 1");
    await expect.poll(() => db.newsCalls().length).toBe(3);
    expect(db.newsCalls().map(url => url.searchParams.get("article_date")).sort()).toEqual(eventDates.map(date => `eq.${date}`).sort());
    for (const url of db.newsCalls()) {
      expect(url.searchParams.get("stock_code")).toBe(`eq.${firstStock}`);
      expect(url.searchParams.get("track")).toBe("eq.live");
      expect(url.searchParams.get("order")).toBe("published_at.desc.nullslast,news_id.asc");
      expect(url.searchParams.get("limit")).toBe("50");
    }
  } else {
    await expect(news(page)).toContainText("이 자료는 지금 제공하지 않아요.");
    await expect(retry(news(page))).toHaveCount(0);
  }
  await openEvent(page, oldest);
  await expect(marker(page, oldest)).toHaveAttribute("aria-expanded", "true");
  await expect(selected(page)).toContainText(formatted(oldest));
  await expect(kospi(page)).toContainText("+0.75%");
  if (newsEnabled) await expect(news(page)).toContainText(`${formatted(oldest)} 14:00`);
  await marker(page, middle).press("Space");
  await expect(marker(page, middle)).toHaveAttribute("aria-expanded", "true");
  await expect(selected(page)).toContainText(formatted(middle));
  await expect(kospi(page)).toContainText("-0.51%");

  await expect(panel(page)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(disclosures(page).getByRole("link").first()).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(marker(page, middle)).toBeFocused();

  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await marker(page, latest).tap();
    await expect(selected(page)).toContainText(formatted(latest));
    if (newsEnabled) await expect(news(page)).toContainText("삼성전자 가상 뉴스 1");
    const box = await panel(page).boundingBox();
    assert.ok(box);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    if (width === 390) await capturePanel(page, "tap-popup");
    expect(box.height).toBeLessThanOrEqual(422);
    await page.touchscreen.tap(8, Math.round(box.y + box.height / 2));
    await expect(panel(page)).toHaveCount(0);
  }
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });
  expect(db.newsCalls()).toHaveLength(newsEnabled ? 3 : 0);
});

test("Escape keeps the hovered date closed until the pointer leaves", async ({ page }) => {
  await page.clock.install();
  await mockContext(page);
  await page.goto(`/stocks/${firstStock}`);
  const trigger = marker(page, latest);
  await trigger.hover();
  await expect(panel(page)).toBeVisible();
  const box = await trigger.boundingBox();
  assert.ok(box);

  await page.keyboard.press("Escape");
  await expect(panel(page)).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await page.mouse.move(box.x + box.width / 2 + 1, box.y + box.height / 2);
  await page.clock.runFor(1000);
  await expect(panel(page)).toHaveCount(0);

  await page.mouse.move(1, 420);
  await trigger.hover();
  await expect(selected(page)).toContainText(formatted(latest));
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
  await openEvent(page);
  await expect(disclosures(page)).toContainText("자료를 보낸 서버에서 오류가 났어요.");
  await capturePanel(page, "initial-failure");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await disclosures(page).getByRole("button", { name: "다시 확인" }).click();
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
  expect(db.counts()).toEqual({ market: 1, disclosures: 4 });

  await openEvent(page, middle);
  await expect(kospi(page)).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await openEvent(page, oldest);
  await expect(kospi(page)).toContainText("+0.75%");
  await expect(disclosures(page)).toContainText("조회된 공시가 없어요.");
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
});

test("news distinguishes rate limit, malformed response, access denial and a successful empty day", async ({ page }) => {
  let latestAttempt = 0;
  let middleAttempt = 0;
  const db = await mockContext(page, (route, url) => {
    if (isNewsOn(url, latest) && ++latestAttempt === 1) return route.fulfill({ status: 429, json: { message: "fixture rate detail" } });
    if (isNewsOn(url, middle)) return route.fulfill({ json: ++middleAttempt === 1 ? { invalid: true } : [] });
    if (isNewsOn(url, oldest)) return route.fulfill({ status: 403, json: { message: "fixture access detail" } });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  const source = news(page);
  await expect(source).toContainText("조회 요청이 제한돼 지금은 자료를 확인할 수 없어요.");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await expect.poll(() => db.newsCalls().length).toBe(3);
  await retry(source).click();
  const first = source.getByRole("link", { name: "삼성전자 가상 뉴스 1" });
  await expect(first).toHaveAttribute("href", `https://example.test/news/${firstStock}/${latest}/1`);
  await expect(first).toHaveAttribute("rel", "noopener noreferrer");
  await first.scrollIntoViewIfNeeded();
  const popupBox = await panel(page).boundingBox();
  const newsBox = await first.boundingBox();
  assert.ok(popupBox && newsBox);
  expect(newsBox.y).toBeGreaterThanOrEqual(popupBox.y);
  expect(newsBox.y + newsBox.height).toBeLessThanOrEqual(popupBox.y + popupBox.height);
  await capturePanel(page, "news-popup");
  await expect(first.locator("..")).toContainText("가상 언론사");
  await expect(first.locator("..").locator("time")).toHaveText(`${formatted(latest)} 14:00`);
  await expect(source.getByText("삼성전자 가상 뉴스 3")).toBeVisible();
  await expect(source.getByRole("link", { name: "삼성전자 가상 뉴스 3" })).toHaveCount(0);
  await expect(source.getByRole("listitem")).toHaveCount(3);
  await source.getByRole("button", { name: "더 보기(1)" }).click();
  await expect(source.getByRole("listitem")).toHaveCount(4);
  await expect(source.getByRole("link", { name: "삼성전자 가상 뉴스 4" }).locator("..").locator("time")).toHaveText(formatted(latest));
  expect(db.newsCalls()).toHaveLength(4);
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });

  await openEvent(page, middle);
  await expect(source).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await retry(source).click();
  await expect(source).toContainText("조회된 뉴스가 없어요.");
  await expect(source).toContainText("저장된 뉴스만 조회해요.");
  await expect(retry(source)).toHaveCount(0);
  await expect(source.getByRole("listitem")).toHaveCount(0);

  await openEvent(page, oldest);
  await expect(source).toContainText("이 자료에 접근할 수 없어요.");
  await expect(retry(source)).toHaveCount(0);
  expect(db.newsCalls()).toHaveLength(5);
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });
});

test("a timed-out news refresh keeps the last result and ignores its late response after retry", async ({ page }) => {
  await page.clock.install();
  await ignoreEventSourceAbort(page);
  const waiting = deferred();
  const release = deferred();
  let attempt = 0;
  const db = await mockContext(page, async (route, url, fixture) => {
    if (isNewsOn(url, latest)) {
      const [article] = eventNews(firstStock, latest);
      attempt += 1;
      if (attempt === 2) {
        waiting.resolve();
        await release.promise;
        return route.fulfill({ json: [{ ...article, title: "늦게 도착한 가상 뉴스" }] });
      }
      if (attempt === 3) return route.fulfill({ json: [{ ...article, title: "새로 확인한 가상 뉴스" }] });
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  const source = news(page);
  await expect(source).toContainText("삼성전자 가상 뉴스 1");
  await focusRefresh(page);
  await waiting.promise;
  await expect(source).toContainText("새로 확인하는 중이에요.");
  await expect(source).toContainText("삼성전자 가상 뉴스 1");
  const status = source.getByRole("status", { name: "뉴스 조회 상태" });
  const checked = status.locator("time");
  const firstTime = await checked.getAttribute("datetime");
  assert.ok(firstTime);
  await page.clock.fastForward(10_001);
  await expect(status).toContainText("새로 확인하는 데 시간이 오래 걸려 중단했어요. 이전 조회 자료를 표시해요.");
  await expect(checked).toHaveAttribute("datetime", firstTime);
  await expect(source).toContainText("삼성전자 가상 뉴스 1");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await expect.poll(db.counts).toEqual({ market: 2, disclosures: 6 });
  await expect.poll(() => db.newsCalls().length).toBe(6);
  await retry(source).press("Enter");
  await expect(status).toBeFocused();
  await expect(source).toContainText("새로 확인한 가상 뉴스");
  await expect(checked).toHaveCount(0);
  const lateResponse = page.waitForResponse(response => isNewsOn(new URL(response.url()), latest));
  release.resolve();
  await (await lateResponse).finished();
  await expect(source).not.toContainText("늦게 도착한 가상 뉴스");
  expect(db.newsCalls()).toHaveLength(7);
  expect(db.counts()).toEqual({ market: 2, disclosures: 6 });
});

test("same-key retry retains previous success and rejects an older late response", async ({ page }) => {
  await page.clock.install();
  await ignoreEventSourceAbort(page);
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
  await openEvent(page);
  await expect(disclosures(page)).toContainText("처음 내려받은 자료");
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await waiting.promise;
  await expect(disclosures(page)).toContainText("새로 확인하는 중이에요.");
  await expect(disclosures(page)).toContainText("처음 내려받은 자료");
  await page.clock.fastForward(10_100);
  await expect(disclosures(page)).toContainText("새로 확인하는 데 시간이 오래 걸려 중단했어요.");
  await expect(disclosures(page)).toContainText("이전 조회 자료를 표시해요.");
  await disclosures(page).getByRole("button", { name: "다시 확인" }).click();
  await expect(disclosures(page)).toContainText("가장 최근에 확인한 자료");
  const oldResponse = page.waitForResponse(response => isLatestDisclosure(new URL(response.url())));
  release.resolve();
  await (await oldResponse).finished();
  await expect(disclosures(page)).toContainText("가장 최근에 확인한 자료");
  await expect(disclosures(page)).not.toContainText("늦게 끝난 이전 자료");
});

test("switching stocks discards delayed disclosure and news results from the previous stock", async ({ page }) => {
  await ignoreEventSourceAbort(page);
  const pendingDisclosure = deferred();
  const pendingNews = deferred();
  const release = deferred();
  await mockContext(page, (route, url, fixture) => {
    if (url.searchParams.get("stock_code") !== `eq.${firstStock}`) return;
    if (isLatestDisclosure(url)) pendingDisclosure.resolve();
    else if (isNewsOn(url, latest)) pendingNews.resolve();
    else return;
    return release.promise.then(() => route.fulfill({ json: fixture }));
  });
  await page.goto(`/stocks/${firstStock}`);
  await Promise.all([pendingDisclosure.promise, pendingNews.promise]);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("자료를 불러오는 중이에요.");
  await expect(news(page)).toContainText("자료를 불러오는 중이에요.");
  await page.getByRole("searchbox", { name: "종목 검색" }).fill(secondStock);
  await page.getByRole("link", { name: /현대차 005380/ }).click();
  await expect(page).toHaveURL(`/stocks/${secondStock}`);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("현대차 가상 공시 1");
  await expect(news(page)).toContainText("현대차 가상 뉴스 1");
  const oldResponses = [isLatestDisclosure, (url: URL) => isNewsOn(url, latest)].map(matches =>
    page.waitForResponse(response => {
      const url = new URL(response.url());
      return matches(url) && url.searchParams.get("stock_code") === `eq.${firstStock}`;
    }));
  release.resolve();
  await Promise.all(oldResponses.map(async response => (await response).finished()));
  await expect(disclosures(page)).toContainText("현대차 가상 공시 1");
  await expect(disclosures(page)).not.toContainText("삼성전자 가상 공시");
  await expect(news(page)).toContainText("현대차 가상 뉴스 1");
  await expect(news(page)).not.toContainText("삼성전자 가상 뉴스");
});

test("legacy snapshots still display chart and skip event source reads", async ({ page }) => {
  const db = await mockContext(page, (route, url) => {
    if (!url.pathname.endsWith("/latest_chart_signal_snapshots")) return;
    const rows = eventChartRows(firstStock);
    for (const response of rows) Reflect.deleteProperty(response.payload.prices, "event_basis");
    return route.fulfill({ json: rows });
  });
  await page.goto(`/stocks/${firstStock}`);
  await expect(page.getByRole("img", { name: "최근 주가 흐름", exact: true })).toBeVisible();
  await expect(eventStatus(page)).toContainText("이 차트에는 변동일을 고르는 기준이 없어요.");
  await capturePanel(page, "missing-basis");
  expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
});

test("the popup follows a surviving date and closes when a new batch removes that marker", async ({ page }) => {
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
  await openEvent(page, oldest);
  await expect(disclosures(page)).toContainText("갱신 0");
  revision = 1;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(disclosures(page)).toContainText("갱신 1");
  await expect(selected(page)).toContainText(formatted(oldest));
  await expect(marker(page, oldest)).toHaveAttribute("aria-expanded", "true");

  revision = 2;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(marker(page, oldest)).toHaveCount(0);
  await expect(panel(page)).toHaveCount(0);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("갱신 2");
  await expect(selected(page)).toContainText(formatted(latest));
  await expect(marker(page, latest)).toHaveAttribute("aria-expanded", "true");
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
  const chart = page.getByRole("img", { name: "최근 주가 흐름", exact: true });
  const unavailable = "가격 기록의 개수나 날짜가 맞지 않아 변동일을 확인할 수 없어요.";
  for (const horizon of ["1주", "4주"]) {
    const tab = page.getByRole("tab", { name: horizon, exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
    await expect(chart).toBeVisible();
    await expect(eventStatus(page)).toContainText(unavailable);
    await expect(page.getByRole("button", { name: /^차트에서 / })).toHaveCount(0);
  }
  expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
});

test("the chart's first load and failure continue to use the chart retry", async ({ page }) => {
  const waiting = deferred();
  const release = deferred();
  let attempt = 0;
  const db = await mockContext(page, async (route, url, fixture) => {
    if (isChart(url) && ++attempt === 1) {
      waiting.resolve();
      await release.promise;
      return route.fulfill({ status: 400, json: { message: "hidden chart error" } });
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto(`/stocks/${firstStock}`);
  await waiting.promise;
  await expect(page.getByText(/신호와 근거를 불러오는 중이에요/)).toBeVisible();
  await expect(panel(page)).toHaveCount(0);
  release.resolve();
  const alert = page.getByRole("alert").filter({ hasText: "차트를 불러오지 못했어요" });
  await expect(alert).toBeVisible();
  expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
  await alert.getByRole("button", { name: "다시 시도" }).click();
  await openEvent(page);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
});

const unusableCharts = [
  { name: "invalid-basis", copy: "변동일을 고르는 기준을 확인할 수 없어요." },
  { name: "different-bases", copy: "기간마다 가격 기록이나 계산 기준이 달라 변동일을 확인할 수 없어요." },
  { name: "different-prices", copy: "기간마다 가격 기록이나 계산 기준이 달라 변동일을 확인할 수 없어요." },
  { name: "no-comparisons", copy: "가격 변화를 비교할 수 있는 거래일이 없어요." },
  { name: "no-moves", copy: "확인한 날 중 기준을 넘은 날이 없어요." },
] as const;

for (const { name, copy } of unusableCharts) {
  test(`${name} leaves the ordinary chart available and skips source reads`, async ({ page }) => {
    const db = await mockContext(page, (route, url) => {
      if (!isChart(url)) return;
      const charts = eventChartRows(firstStock);
      for (const chart of charts) {
        const { prices } = chart.payload;
        if (name === "invalid-basis") prices.event_basis.input_sha256 = "b".repeat(64);
        if (name === "different-bases" && chart.horizon === 5) prices.event_basis.daily_sigma = .04;
        if (name === "different-prices" && chart.horizon === 5) {
          prices.history = prices.history.map((bar: DatedClose, index: number) => index === 0 ? { ...bar, close: bar.close + 1 } : bar);
        }
        if (name === "no-comparisons") prices.history = prices.history.map((bar: DatedClose) => ({ ...bar, volume: 0 }));
        if (name === "no-moves") {
          prices.history = prices.history.map((bar: DatedClose) => ({ ...bar, close: 10000 }));
          prices.event_basis.previous_bar = null;
        }
      }
      return route.fulfill({ json: charts });
    });
    await page.goto(`/stocks/${firstStock}`);
    await expect(eventStatus(page)).toContainText(copy);
    await page.getByRole("tab", { name: "1주", exact: true }).click();
    await expect(chart(page)).toBeVisible();
    await expect(page.getByRole("button", { name: /^차트에서 / })).toHaveCount(0);
    if (name === "invalid-basis") await capturePanel(page, name);
    if (name === "no-moves") {
      await expect(eventStatus(page)).toContainText("일부 거래일은 비교하지 못했어요.");
    }
    expect(db.counts()).toEqual({ market: 0, disclosures: 0 });
  });
}

test("empty disclosures, absent market rows and missing KOSPI values are success without retry", async ({ page }) => {
  const db = await mockContext(page, (route, url) => {
    if (isDisclosure(url)) return route.fulfill({ json: [] });
    if (isMarket(url)) return route.fulfill({
      json: [
        { status_date: latest, index_quotes: [{ symbol: "KOSPI", changePercent: 0 }] },
        { status_date: middle, index_quotes: [{ symbol: "KOSPI", changePercent: null }] },
      ],
    });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("조회된 공시가 없어요.");
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await openEvent(page, middle);
  await expect(kospi(page)).toContainText("이날 코스피 등락률이 자료에 없어요.");
  await openEvent(page, oldest);
  await expect(kospi(page)).toContainText("이날 조회된 코스피 자료가 없어요.");
  await expect(retry(disclosures(page))).toHaveCount(0);
  await expect(retry(kospi(page))).toHaveCount(0);
  await capturePanel(page, "empty-success");
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });
});

test("partial and capped disclosures keep verified rows during failure, then recovery replaces them with fresh empty", async ({ page }) => {
  const invalid = row(secondStock, latest, "화면에 나오면 안 되는 다른 종목 공시");
  let attempt = 0;
  const db = await mockContext(page, (route, url) => {
    if (isLatestDisclosure(url)) {
      attempt += 1;
      if (attempt === 2) return route.fulfill({ json: [invalid] });
      if (attempt === 3) return route.fulfill({ json: [] });
      return route.fulfill({
        json: [invalid, ...Array.from({ length: 49 }, (_, i) => ({
          ...row(firstStock, latest, `유효한 가상 공시 ${i + 1}`),
          rcept_no: `${latest.replaceAll("-", "")}${String(i + 1).padStart(6, "0")}`,
        }))],
      });
    }
    if (isDisclosure(url)) return route.fulfill({ json: [invalid] });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  const publicRows = disclosures(page);
  const partialCoverage = "형식이 맞지 않는 공시는 뺐어요. 조회 한도에 도달해 공시가 더 있는지 확인하지 못했어요.";
  await expect(publicRows).toContainText(partialCoverage);
  await expect(publicRows).not.toContainText(invalid.title);
  await expect(publicRows.getByRole("link")).toHaveCount(3);
  await publicRows.getByRole("button", { name: "더 보기(46)" }).click();
  await expect(publicRows.getByRole("link")).toHaveCount(49);
  await openEvent(page, middle);
  await expect(publicRows).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await expect(publicRows.getByRole("link")).toHaveCount(0);
  await expect(retry(publicRows)).toBeVisible();
  await openEvent(page);
  await focusRefresh(page);
  await expect(publicRows).toContainText("새 자료의 형식이 맞지 않아 갱신하지 못했어요. 이전 조회 자료를 표시해요.");
  await expect(publicRows).toContainText(partialCoverage);
  await expect(publicRows.getByRole("link")).toHaveCount(3);
  await retry(publicRows).click();
  await expect(publicRows).toContainText("조회된 공시가 없어요.");
  await expect(publicRows).not.toContainText("갱신하지 못했어요");
  await expect(publicRows.getByRole("link")).toHaveCount(0);
  expect(db.counts()).toEqual({ market: 2, disclosures: 7 });
});

test("access denial stays local and suppresses repeat reads until a new batch", async ({ page }) => {
  await page.clock.install();
  let nextBatch = false;
  const db = await mockContext(page, (route, url) => {
    if (isChart(url) && nextBatch) {
      const charts = eventChartRows(firstStock).map(chart => ({
        ...chart, batch_id: "new-permissions-batch", payload: { ...chart.payload, batch_id: "new-permissions-batch" },
      }));
      return route.fulfill({ json: charts });
    }
    if (!isDisclosure(url) || nextBatch) return;
    if (isLatestDisclosure(url)) return route.fulfill({ status: 401, json: { message: "fixture restricted" } });
    const upper = url.searchParams.getAll("filed_on").find(value => value.startsWith("lte.")) ?? "";
    if (upper > `lte.${middle}`) return route.fulfill({ status: 403, json: { message: "fixture forbidden" } });
    return route.fulfill({ status: 400, json: { code: "42501", message: "fixture insufficient privilege" } });
  });
  await page.goto(`/stocks/${firstStock}`);
  for (const date of eventDates) {
    await openEvent(page, date);
    await expect(disclosures(page)).toContainText("이 자료에 접근할 수 없어요.");
    await expect(retry(disclosures(page))).toHaveCount(0);
  }
  await focusRefresh(page);
  await expect.poll(db.counts).toEqual({ market: 2, disclosures: 3 });
  await page.clock.fastForward(300_001);
  await expect.poll(db.counts).toEqual({ market: 3, disclosures: 3 });
  nextBatch = true;
  await focusRefresh(page);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시");
  await expect.poll(db.counts).toEqual({ market: 4, disclosures: 6 });
});

test("rate limit, blocked connection and invalid HTTP success each offer only their source retry", async ({ page }) => {
  await page.clock.install();
  let disclosureAttempts = 0;
  let marketAttempts = 0;
  const db = await mockContext(page, (route, url) => {
    if (isLatestDisclosure(url)) {
      disclosureAttempts += 1;
      if (disclosureAttempts === 1) return route.fulfill({ status: 429, json: { message: "internal rate detail" } });
      if (disclosureAttempts === 2) return route.fulfill({ contentType: "text/plain", body: "internal invalid body" });
      if (disclosureAttempts === 3) return route.fulfill({ status: 400, json: { message: "internal unknown error" } });
    }
    if (isMarket(url) && ++marketAttempts === 1) return route.abort("failed");
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("조회 요청이 제한돼 지금은 자료를 확인할 수 없어요.");
  await expect(kospi(page)).toContainText("자료를 받지 못했어요. 연결 상태를 확인해 주세요.");
  await page.clock.fastForward(30_000);
  expect(db.counts()).toEqual({ market: 1, disclosures: 3 });
  await retry(disclosures(page)).click();
  await expect(disclosures(page)).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await expect(disclosures(page)).not.toContainText("internal invalid body");
  expect(db.counts()).toEqual({ market: 1, disclosures: 4 });
  await retry(kospi(page)).click();
  await expect(kospi(page)).toContainText("코스피 0.00%");
  expect(db.counts()).toEqual({ market: 2, disclosures: 4 });
  await retry(disclosures(page)).click();
  await expect(disclosures(page)).toContainText("자료를 불러오지 못했어요.");
  await expect(disclosures(page)).not.toContainText("internal unknown error");
  await retry(disclosures(page)).click();
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  expect(db.counts()).toEqual({ market: 2, disclosures: 6 });
});

test("first timeout keeps the chart usable and keyboard retry focuses its live status on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.clock.install();
  const waiting = deferred();
  const release = deferred();
  let attempt = 0;
  const db = await mockContext(page, async (route, url, fixture) => {
    if (isLatestDisclosure(url) && ++attempt === 1) {
      waiting.resolve();
      await release.promise;
      return route.abort();
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto(`/stocks/${firstStock}`);
  await waiting.promise;
  await openEvent(page);
  await expect(disclosures(page)).toContainText("자료를 불러오는 중이에요.");
  await expect(chart(page)).toBeVisible();
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await page.clock.fastForward(10_001);
  release.resolve();
  const status = disclosures(page).getByRole("status", { name: "공시 조회 상태" });
  await expect(status).toContainText("자료를 불러오는 데 시간이 오래 걸려 중단했어요.");
  await expect(status).toHaveAttribute("aria-live", "polite");
  expect((await retry(disclosures(page)).boundingBox())?.height).toBeGreaterThanOrEqual(44);
  await retry(disclosures(page)).press("Enter");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(status).toBeFocused();
  await expect(retry(disclosures(page))).toHaveCount(0);
  expect(db.counts()).toEqual({ market: 1, disclosures: 4 });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  }
});

test("failed refresh of an earlier empty read keeps its time and a recovery can return fresh empty", async ({ page }) => {
  await page.clock.install();
  const waiting = deferred();
  const release = deferred();
  let attempt = 0;
  const db = await mockContext(page, (route, url) => {
    if (!isLatestDisclosure(url)) return;
    attempt += 1;
    if (attempt === 2) {
      waiting.resolve();
      return release.promise.then(() => serverError(route));
    }
    return route.fulfill({ json: [] });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  const source = disclosures(page);
  await expect(source).toContainText("조회된 공시가 없어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await focusRefresh(page);
  await waiting.promise;
  await expect(source).toContainText("새로 확인하는 중이에요.");
  const checked = source.getByRole("status").locator("time");
  const firstTime = await checked.getAttribute("datetime");
  assert.ok(firstTime);
  await page.clock.fastForward(4_000);
  release.resolve();
  await expect(source).toContainText("지난번에 조회된 공시가 없었어요.");
  await expect(source).toContainText("자료를 보낸 서버에서 오류가 났어요.");
  await expect(checked).toHaveAttribute("datetime", firstTime);
  await capturePanel(page, "stale-empty");
  await retry(source).click();
  await expect(source).toContainText("조회된 공시가 없어요.");
  await expect(source).not.toContainText("지난번");
  await expect(checked).toHaveCount(0);
  await expect(retry(source)).toHaveCount(0);
  expect(db.counts()).toEqual({ market: 2, disclosures: 7 });
});

test("a new batch aborts previous disclosure and news reads and ignores their late payloads", async ({ page }) => {
  await page.addInitScript(({ code, date, newsSelect }) => {
    const fetch = window.fetch;
    window.fetch = (input, options) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
      if (url.searchParams.get("stock_code") !== `eq.${code}`) return fetch(input, options);
      const disclosure = url.pathname.endsWith("/disclosures") && url.searchParams.getAll("filed_on").includes(`lte.${date}`);
      const news = url.pathname.endsWith("/news_articles") && url.searchParams.get("select") === newsSelect &&
        url.searchParams.get("article_date") === `eq.${date}`;
      if (!disclosure && !news) return fetch(input, options);
      options?.signal?.addEventListener("abort", () => {
        document.documentElement.dataset[news ? "fixtureNewsAborted" : "fixtureAborted"] = "true";
      }, { once: true });
      return fetch(input, { ...options, signal: undefined });
    };
  }, { code: firstStock, date: latest, newsSelect: eventNewsSelect });
  let newBatch = false;
  let attempt = 0;
  let newsAttempt = 0;
  const waiting = deferred();
  const waitingNews = deferred();
  const release = deferred();
  await mockContext(page, async (route, url, fixture) => {
    if (isChart(url) && newBatch) {
      const charts = eventChartRows(firstStock);
      for (const chart of charts) chart.batch_id = chart.payload.batch_id = "next-error-evidence-batch";
      return route.fulfill({ json: charts });
    }
    if (isLatestDisclosure(url)) {
      attempt += 1;
      if (newBatch) return route.fulfill({ json: [row(firstStock, latest, "새 배치 가상 공시")] });
      if (attempt === 2) {
        waiting.resolve();
        await release.promise;
        return route.fulfill({ json: [row(firstStock, latest, "늦게 도착한 이전 배치 가상 공시")] });
      }
    }
    if (isNewsOn(url, latest)) {
      const [article] = eventNews(firstStock, latest);
      newsAttempt += 1;
      if (newBatch) return route.fulfill({ json: [{ ...article, title: "새 배치 가상 뉴스" }] });
      if (newsAttempt === 2) {
        waitingNews.resolve();
        await release.promise;
        return route.fulfill({ json: [{ ...article, title: "늦게 도착한 이전 배치 가상 뉴스" }] });
      }
    }
    return route.fulfill({ json: fixture });
  });
  await page.goto(`/stocks/${firstStock}`);
  await openEvent(page);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await expect(news(page)).toContainText("삼성전자 가상 뉴스 1");
  await focusRefresh(page);
  await Promise.all([waiting.promise, waitingNews.promise]);
  await expect(disclosures(page)).toContainText("새로 확인하는 중이에요.");
  newBatch = true;
  await focusRefresh(page);
  await expect(page.locator("html")).toHaveAttribute("data-fixture-aborted", "true");
  await expect(page.locator("html")).toHaveAttribute("data-fixture-news-aborted", "true");
  await expect(disclosures(page)).toContainText("새 배치 가상 공시");
  await expect(news(page)).toContainText("새 배치 가상 뉴스");
  const deliveredLate = [isLatestDisclosure, (url: URL) => isNewsOn(url, latest)].map(matches =>
    page.waitForResponse(response => matches(new URL(response.url()))));
  release.resolve();
  await Promise.all(deliveredLate.map(async response => (await response).finished()));
  await expect(disclosures(page)).toContainText("새 배치 가상 공시");
  await expect(disclosures(page)).not.toContainText("이전 배치 가상 공시");
  await expect(retry(disclosures(page))).toHaveCount(0);
  await expect(news(page)).toContainText("새 배치 가상 뉴스");
  await expect(news(page)).not.toContainText("이전 배치 가상 뉴스");
  await expect(retry(news(page))).toHaveCount(0);
});
