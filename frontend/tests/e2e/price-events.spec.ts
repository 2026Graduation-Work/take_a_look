import assert from "node:assert/strict";
import { join } from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";
import type { DatedClose } from "../../lib/price-events";
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
const selected = (page: Page) => panel(page).locator("p[aria-live=polite]");
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
const isMarket = (url: URL) => url.pathname.endsWith("/market_status");
const isDisclosure = (url: URL) => url.pathname.endsWith("/disclosures");
const isChart = (url: URL) => url.pathname.endsWith("/latest_chart_signal_snapshots");
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
  const previous = page.viewportSize();
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await panel(page).screenshot({ path: join(directory, `${name}-${width}.png`) });
  }
  if (previous) await page.setViewportSize(previous);
}

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
  await expect(disclosures(page)).toContainText("자료를 보낸 서버에서 오류가 났어요.");
  await capturePanel(page, "initial-failure");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await disclosures(page).getByRole("button", { name: "다시 확인" }).click();
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
  expect(db.counts()).toEqual({ market: 1, disclosures: 4 });

  await dateButton(page, middle).click();
  await expect(kospi(page)).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await dateButton(page, oldest).click();
  await expect(kospi(page)).toContainText("+0.75%");
  await expect(disclosures(page)).toContainText("조회된 공시가 없어요.");
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
  await expect(page.getByRole("img", { name: "최근 주가 흐름", exact: true })).toBeVisible();
  await expect(panel(page)).toContainText("이 차트에는 변동일을 고르는 기준이 없어요.");
  await capturePanel(page, "missing-basis");
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
  const chart = page.getByRole("img", { name: "최근 주가 흐름", exact: true });
  const unavailable = "가격 기록의 개수나 날짜가 맞지 않아 변동일을 확인할 수 없어요.";
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
    await expect(panel(page)).toContainText(copy);
    await page.getByRole("tab", { name: "1주", exact: true }).click();
    await expect(chart(page)).toBeVisible();
    await expect(page.getByRole("button", { name: /^차트에서 / })).toHaveCount(0);
    if (name === "invalid-basis") await capturePanel(page, name);
    if (name === "no-moves") {
      await expect(panel(page)).toContainText("일부 거래일은 비교하지 못했어요.");
      await panel(page).getByText("계산 근거", { exact: true }).click();
      await expect(panel(page)).toContainText("59일을 비교했어요.");
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
  await expect(disclosures(page)).toContainText("조회된 공시가 없어요.");
  await expect(disclosures(page)).toContainText("수집 범위를 확인하지 못했어요.");
  await expect(kospi(page)).toContainText("코스피 0.00%");
  await dateButton(page, middle).press("Enter");
  await expect(kospi(page)).toContainText("이날 코스피 등락률이 자료에 없어요.");
  await dateButton(page, oldest).press("Enter");
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
  const publicRows = disclosures(page);
  const partialCoverage = "형식이 맞지 않는 공시는 뺐어요. 조회 한도에 도달해 공시가 더 있는지 확인하지 못했어요.";
  await expect(publicRows).toContainText(partialCoverage);
  await expect(publicRows).not.toContainText(invalid.title);
  await expect(publicRows.getByRole("link")).toHaveCount(3);
  await publicRows.getByRole("button", { name: "더 보기(46)" }).click();
  await expect(publicRows.getByRole("link")).toHaveCount(49);
  await dateButton(page, middle).click();
  await expect(publicRows).toContainText("받은 자료의 형식이 맞지 않아 표시할 수 없어요.");
  await expect(publicRows.getByRole("link")).toHaveCount(0);
  await expect(retry(publicRows)).toBeVisible();
  await dateButton(page, latest).click();
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
    await dateButton(page, date).click();
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

test("a new batch aborts the previous request and ignores its late payload", async ({ page }) => {
  await page.addInitScript(({ code, date }) => {
    const fetch = window.fetch;
    window.fetch = (input, options) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, location.href);
      if (!url.pathname.endsWith("/disclosures") || url.searchParams.get("stock_code") !== `eq.${code}` ||
          !url.searchParams.getAll("filed_on").includes(`lte.${date}`)) return fetch(input, options);
      options?.signal?.addEventListener("abort", () => {
        document.documentElement.dataset.fixtureAborted = "true";
      }, { once: true });
      return fetch(input, { ...options, signal: undefined });
    };
  }, { code: firstStock, date: latest });
  let newBatch = false;
  let attempt = 0;
  const waiting = deferred();
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
    return route.fulfill({ json: fixture });
  });
  await page.goto(`/stocks/${firstStock}`);
  await expect(disclosures(page)).toContainText("삼성전자 가상 공시 1");
  await focusRefresh(page);
  await waiting.promise;
  await expect(disclosures(page)).toContainText("새로 확인하는 중이에요.");
  newBatch = true;
  await focusRefresh(page);
  await expect(page.locator("html")).toHaveAttribute("data-fixture-aborted", "true");
  await expect(disclosures(page)).toContainText("새 배치 가상 공시");
  const deliveredLate = page.waitForResponse(response => isLatestDisclosure(new URL(response.url())));
  release.resolve();
  await (await deliveredLate).finished();
  await expect(disclosures(page)).toContainText("새 배치 가상 공시");
  await expect(disclosures(page)).not.toContainText("이전 배치 가상 공시");
  await expect(retry(disclosures(page))).toHaveCount(0);
});
