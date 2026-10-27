import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const profile = JSON.parse(readFileSync("../schema/profiling_output.v1_1.example.json", "utf8"));
const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
const rows = snapshots.map((payload: typeof snapshots[number]) => ({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon,
  payload: { ...payload, inference: { ...payload.inference,
    scores: payload.horizon === 5 ? { down: .8, neutral: .1, up: .1 } : { down: .1, neutral: .1, up: .8 },
  } },
}));

async function ready(page: Page) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript((value) => {
    localStorage.setItem("takealook.demo-session.v1", JSON.stringify({ userId: "demo_minji", displayName: "김민지", signedInAt: new Date().toISOString() }));
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(value));
    localStorage.setItem("takealook.holdings.v1", JSON.stringify([{ code: "005930", name: "삼성전자", quantity: 12, avgBuyPrice: null }]));
  }, profile);
}

async function charts(page: Page, beforeCloses?: (horizon: number) => Promise<void>) {
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", async route => {
    const url = new URL(route.request().url());
    const select = url.searchParams.get("select") ?? "";
    const horizon = Number(url.searchParams.get("horizon")?.replace("eq.", "") ?? 20);
    if (select.includes("close:payload")) {
      await beforeCloses?.(horizon);
      return route.fulfill({ json: [{ stock_code: "005930", close: 275000, as_of: "2026-09-21", status: "available", scores: horizon === 5 ? { down: .8, neutral: .1, up: .1 } : { down: .1, neutral: .1, up: .8 } }] });
    }
    if (select.includes("scores:")) return route.fulfill({ json: [] });
    return route.fulfill({ json: rows });
  });
}

test("M01: demo holdings can select a public stock outside the four examples and reject unknown names", async ({ page }) => {
  await ready(page);
  await page.route("**/rest/v1/stocks?**", route => route.fulfill({ json: [
    { code: "000660", name: "SK하이닉스" }, { code: "005930", name: "삼성전자" },
  ] }));
  await page.goto("/portfolio");
  const search = page.getByRole("combobox", { name: "종목 검색", exact: true });
  await search.fill("SK하이닉스");
  await expect(page.locator("datalist option[value='SK하이닉스']")).toHaveCount(1);
  await search.press("Enter");
  await expect(page.getByRole("textbox", { name: "SK하이닉스 수량", exact: true })).toBeFocused();
  await search.fill("000660");
  await search.press("Enter");
  await expect(page.getByRole("textbox", { name: "SK하이닉스 수량", exact: true })).toHaveCount(1);
  await search.fill("없는종목QA");
  await search.press("Enter");
  await expect(page.getByRole("alert").filter({ hasText: "찾는 종목" })).toBeVisible();
});

test("M02: a one-week dashboard signal opens the same model, band and feature basis in detail", async ({ page }) => {
  await ready(page);
  await charts(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "1주", exact: true }).click();
  const tile = page.getByRole("listitem", { name: /^삼성전자,.*앞으로 1주 하락 신호$/ });
  await expect(tile).toBeVisible();
  await tile.click();
  await expect(page.getByRole("heading", { name: /^모델 신호 하락\s*앞으로 1주$/ })).toBeVisible();
  const band = snapshots.find((p: typeof snapshots[number]) => p.horizon === 5).distribution.histogram.central_68;
  const glance = page.locator('section[aria-labelledby="glance-title"]');
  await expect(glance).toContainText(`${Math.abs(band.low).toFixed(1)}%`);
  await page.getByRole("tab", { name: "4주", exact: true }).click();
  await expect(page.getByRole("heading", { name: /^모델 신호 상승\s*앞으로 4주$/ })).toBeVisible();
  await page.getByRole("link", { name: "대시보드", exact: true }).click();
  await expect(page.getByRole("tab", { name: "4주", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("M02: searched stock rows use the selected horizon before opening detail", async ({ page }) => {
  await ready(page);
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => {
    const select = new URL(route.request().url()).searchParams.get("select") ?? "";
    return route.fulfill({ json: select.includes("scores:") ? [] : rows.map((row: typeof rows[number]) => ({
      ...row, stock_code: "035720", payload: { ...row.payload, stock_code: "035720" },
    })) });
  });
  await page.goto("/");
  await page.getByRole("tab", { name: "1주", exact: true }).click();
  await page.getByRole("searchbox").fill("카카오");
  const row = page.locator('[data-stock-row="035720"]');
  await expect(row).toContainText("1주,");
  await expect(row).toContainText("하락");
  await row.click();
  await expect(page.getByRole("heading", { name: /^모델 신호 하락\s*앞으로 1주$/ })).toBeVisible();
});

for (const width of [320, 390, 430]) test(`M03: chart labels remain readable without page overflow at ${width}px`, async ({ page }) => {
  await charts(page);
  await page.setViewportSize({ width, height: 844 });
  await page.goto("/stocks/005930");
  const chart = page.getByRole("img", { name: /^최근 60거래일 주가 흐름/ });
  await expect(chart).toBeVisible();
  const fontSizes = await chart.locator("text").evaluateAll(nodes => nodes.map(node => {
    const text = node as SVGTextElement;
    return parseFloat(getComputedStyle(text).fontSize) * (text.getScreenCTM()?.a ?? 1);
  }));
  expect(Math.min(...fontSizes)).toBeGreaterThanOrEqual(13);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test("M04: pending public portfolio reads never show fixture signals or invented money", async ({ page }) => {
  await ready(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await charts(page, () => pending);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "내 포트폴리오", exact: true })).toBeVisible();
  try {
    await expect(page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" })).toHaveCount(0);
    await expect(page.getByLabel("보유 종목 신호 불러오는 중", { exact: true })).toBeVisible();
  } finally { release(); }
  await expect(page.getByRole("listitem", { name: /^삼성전자,.*평가금액 330만원.*앞으로 4주 상승 신호$/ })).toBeVisible();
});

test("M04: switching horizon hides the previous period until its own read completes", async ({ page }) => {
  await ready(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await charts(page, horizon => horizon === 5 ? pending : Promise.resolve());
  await page.goto("/");
  await expect(page.getByRole("listitem", { name: /^삼성전자,.*앞으로 4주 상승 신호$/ })).toBeVisible();
  await page.getByRole("tab", { name: "1주", exact: true }).click();
  try {
    await expect(page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" })).toHaveCount(0);
  } finally { release(); }
  await expect(page.getByRole("listitem", { name: /^삼성전자,.*앞으로 1주 하락 신호$/ })).toBeVisible();
});

test("M06: clicked sentiment tooltip stays within the visible scrolled chart and closes with Escape", async ({ page }) => {
  test.skip(process.env.TAL_SENTIMENT_E2E !== "1", "requires the server-side full-period sentiment fixture");
  await ready(page);
  await charts(page);
  await page.goto("/stocks/005930");
  await page.getByRole("tab", { name: "시장 분위기", exact: true }).click();
  const timeline = page.getByLabel("감성 시점 탐색", { exact: true });
  await timeline.scrollIntoViewIfNeeded();
  const dots = timeline.locator("circle[data-sentiment-mood], circle[data-sentiment-few]");
  await expect(dots.first()).toBeAttached();
  for (const dot of [dots.nth(await dots.count() - 2), dots.first()]) {
    await dot.evaluate(element => element.scrollIntoView({ block: "center", inline: "center" }));
    const target = (await dot.boundingBox())!;
    await page.mouse.click(target.x + target.width / 2, target.y + target.height / 2);
    const tooltip = page.locator("#sentiment-panel .recharts-tooltip-wrapper");
    await expect(tooltip).toBeVisible();
    const [tip, bounds] = await Promise.all([tooltip.boundingBox(), timeline.boundingBox()]);
    expect(tip!.x).toBeGreaterThanOrEqual(bounds!.x - 1);
    expect(tip!.x + tip!.width).toBeLessThanOrEqual(bounds!.x + bounds!.width + 1);
    await page.keyboard.press("Escape");
    await expect(tooltip).not.toBeVisible();
  }
});

test("M04: an empty public read does not claim there are no downward signals", async ({ page }) => {
  await ready(page);
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: [] }));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("보유 종목의 게시된 신호가 아직 없어요.");
  await expect(page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" })).toHaveCount(0);
});

test("M04: failed public reads show retry and recover without fixture signals", async ({ page }) => {
  await ready(page);
  let failing = true;
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => {
    const select = new URL(route.request().url()).searchParams.get("select") ?? "";
    if (select.includes("close:payload")) return failing
      ? route.fulfill({ status: 500, json: { message: "QA unavailable" } })
      : route.fulfill({ json: [{ stock_code: "005930", close: 275000, as_of: "2026-09-21", status: "available", scores: { down: .1, neutral: .1, up: .8 } }] });
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "보유 종목 신호를 불러오지 못했어요" })).toBeVisible();
  await expect(page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" })).toHaveCount(0);
  failing = false;
  await page.getByRole("button", { name: "다시 시도", exact: true }).click();
  await expect(page.getByRole("listitem", { name: /^삼성전자,.*평가금액 330만원.*앞으로 4주 상승 신호$/ })).toBeVisible();
});

test("M01: pending selection is cancelled when the query changes", async ({ page }) => {
  await ready(page);
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route("**/rest/v1/stocks?**", async route => { await pending; await route.fulfill({ json: [{ code: "000660", name: "SK하이닉스" }] }); });
  await page.goto("/portfolio");
  const search = page.getByPlaceholder("종목명 또는 코드", { exact: true });
  await search.fill("000660");
  await search.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "종목 목록" })).toBeVisible();
  await search.fill("다른 검색어");
  release();
  await expect(page.locator("datalist option[value='SK하이닉스']")).toHaveCount(1);
  await expect(page.getByRole("textbox", { name: "SK하이닉스 수량", exact: true })).toHaveCount(0);
  await expect(search).toHaveValue("다른 검색어");
});

test("M02: horizon still changes when storage is readable but writes fail", async ({ page }) => {
  await ready(page);
  await page.addInitScript(() => {
    const write = Storage.prototype.setItem;
    Storage.prototype.setItem = function(key, value) {
      if (key === "takealook.signal-horizon.v1") throw new DOMException("Storage is full", "QuotaExceededError");
      write.call(this, key, value);
    };
  });
  await charts(page);
  await page.goto("/");
  await page.getByRole("tab", { name: "1주", exact: true }).click();
  await expect(page.getByRole("tab", { name: "1주", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("listitem", { name: /^삼성전자,.*앞으로 1주 하락 신호$/ }).click();
  await expect(page.getByRole("heading", { name: /^모델 신호 하락\s*앞으로 1주$/ })).toBeVisible();
});
