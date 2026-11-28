import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { finishDemo } from "./demo-steps";
import { mockSupabaseAuth } from "./supabase-mock";

const demoKey = "takealook.demo-reading-history.v1";
const hint = "다른 종목에서도 숫자가 어느 기간의 값인지, 무엇과 비교했는지 살펴봐요.";
const basis = "/stocks/000660";
const invite = (page: Page) => page.getByRole("button", { name: "같이 읽기", exact: true });
const replay = (page: Page) => page.getByRole("button", { name: "가이드", exact: true });
const message = (page: Page) => page.getByRole("dialog").filter({
  has: page.getByRole("button", { name: "안내 닫기", exact: true }),
});
const activePanel = (page: Page) => page.locator("[data-reading-panel]:not([hidden])");
const next = (page: Page) => message(page).getByRole("button", { name: "다음", exact: true });
const previous = (page: Page) => message(page).getByRole("button", { name: "이전", exact: true });
const close = (page: Page) => message(page).getByRole("button", { name: "안내 닫기", exact: true });

async function open(page: Page, url = basis) {
  await page.goto(url);
  await expect(replay(page)).toBeVisible();
}

async function introStop(page: Page, tab: string) {
  await expect(message(page)).toBeVisible();
  await expect(activePanel(page)).toHaveAttribute("data-reading-panel", tab);
  await expect(page.locator(`#stock-tab-${tab}.driver-active-element`)).toHaveAttribute("aria-selected", "true");
}

async function orderStop(page: Page) {
  await expect(message(page).getByRole("heading", { name: "이 순서로 살펴봐요" })).toBeVisible();
  await expect(message(page).getByText("읽는 순서", { exact: true })).toBeVisible();
  await expect(message(page).getByText(/\d+\s*\/\s*\d+/)).toHaveCount(0);
  await expect(previous(page)).toHaveCount(0);
  await expect(page.locator("[data-reading-tablist].driver-active-element")).toBeInViewport();
  await expect(activePanel(page)).toHaveAttribute("data-reading-panel", "overview");
}

async function stop(page: Page, tab: string, target: string) {
  await expect(message(page)).toBeVisible();
  await expect(activePanel(page)).toHaveAttribute("data-reading-panel", tab);
  await expect(activePanel(page).locator(`.driver-active-element[data-reading-target="${target}"]`)).toBeVisible();
}

async function advanceUntil(page: Page, goal: Locator) {
  const heading = message(page).getByRole("heading");
  const done = message(page).getByRole("button", { name: "완료", exact: true });
  for (let attempt = 0; attempt < 24; attempt++) {
    const title = await heading.innerText();
    if (await goal.isVisible()) return;
    if (await done.isVisible()) break;
    await next(page).click();
    await expect(heading).not.toHaveText(title);
  }
  throw new Error("안내에서 요청한 단계가 표시되지 않았어요.");
}

async function finish(page: Page) {
  const done = message(page).getByRole("button", { name: "완료", exact: true });
  await advanceUntil(page, done);
  await done.click();
  await expect(message(page)).toHaveCount(0);
}

for (const { turnover, typeLabel, order } of [
  { turnover: -0.5, typeLabel: "추종형", order: ["overview", "trading", "news", "model", "company"] },
  { turnover: 0.5, typeLabel: "독립 분석형", order: ["overview", "model", "company", "news", "trading"] },
]) {
  test(`성향에 맞춰 첫 안내 뒤 각 탭의 소개에서 확인 사항으로 이어져요 (${turnover})`, async ({ page }) => {
    await finishDemo(page);
    await page.evaluate((ratio) => {
      const key = "takealook.ips-profile.v1";
      const profile = JSON.parse(localStorage.getItem(key)!);
      for (const axis of profile.style_axes.axes) axis.ratio = axis.axis_id === "turnover" ? ratio : 0;
      localStorage.setItem(key, JSON.stringify(profile));
    }, turnover);
    await open(page);
    await expect(invite(page)).toHaveCount(0);
    await expect(message(page)).toHaveCount(0);
    const tabs = page.getByRole("tablist", { name: "종목 상세" }).getByRole("tab");
    const names = (await tabs.allTextContents()).map((name) => name.trim());
    expect(await tabs.evaluateAll((elements) => elements.map(({ id }) => id.slice("stock-tab-".length)))).toEqual(order);

    await page.getByRole("button", { name: "모델 신호 설명 보기" }).click();
    await expect(page.getByRole("region", { name: "모델 신호 설명" })).toBeVisible();
    await replay(page).click();
    await orderStop(page);
    await expect(message(page)).toContainText(typeLabel);
    await expect(message(page)).not.toContainText("정보의 정확성");
    const targets: Record<string, string[]> = {
      overview: ["overview-summary", "overview-cohort", "overview-range"],
      model: ["model-histogram", "model-bars", "model-price-mood"],
      trading: ["trading-total"],
      news: ["news-chart", "news-periods"],
      company: ["company-metric", "company-earnings", "company-debt", "company-valuation"],
    };
    for (const [chapterIndex, chapter] of order.entries()) {
      const steps = targets[chapter];
      await next(page).click();
      await introStop(page, chapter);
      await expect(message(page).getByRole("heading")).toHaveText(names[chapterIndex]);
      await expect(message(page).getByText(`${names[chapterIndex]} 1/${steps.length + 1}`, { exact: true })).toBeVisible();
      if (chapterIndex === 1) {
        await previous(page).click();
        await stop(page, "overview", "overview-range");
        await expect(message(page).getByText("한눈에 보기 4/4", { exact: true })).toBeVisible();
        await next(page).click();
        await introStop(page, chapter);
      }
      for (const [index, target] of steps.entries()) {
        await next(page).click();
        await stop(page, chapter, target);
        await expect(message(page).getByText(`${names[chapterIndex]} ${index + 2}/${steps.length + 1}`, { exact: true })).toBeVisible();
        if (target === "overview-summary") await expect(page.getByRole("region", { name: "모델 신호 설명" })).toHaveCount(0);
        if (target === "overview-cohort") await expect(message(page)).toContainText("모델이 상승 쪽으로 본 정도와 평소 주가의 흔들림");
        if (target === "overview-range") await expect(message(page)).toContainText("수익률이 과거 사례마다 많이 달랐다는 뜻");
        if (target === "trading-total") await expect(message(page)).toContainText("매수나 매도가 한쪽에 몰렸는지");
        if (target === "model-histogram") await expect(message(page)).toContainText("이익과 손실 중 어느 쪽 사례가 많았는지");
        if (target === "model-price-mood") await expect(message(page)).toContainText("평균 거래 가격 대비 위치");
        if (target === "news-chart") await expect(message(page)).toContainText("점이 위로 갈수록 기사 표현이 긍정적이었어요.");
        if (target === "company-metric") {
          await expect(message(page)).toContainText("코스피 중간값은 여러 업종을 포함한 기준");
          await expect(message(page)).not.toContainText(/104\.8%|96\.3%/);
        }
      }
    }
    await previous(page).click();
    const lastChapter = order.at(-1)!;
    const previousTarget = targets[lastChapter].at(-2);
    if (previousTarget) await stop(page, lastChapter, previousTarget);
    else await introStop(page, lastChapter);
    await close(page).click();
    await expect(message(page)).toHaveCount(0);
    await expect(replay(page)).toBeFocused();
  });
}

test("첫 방문 안내 줄 없이 가이드로 언제든 다시 시작해요", async ({ page }) => {
  await finishDemo(page);
  await open(page);
  await expect(invite(page)).toHaveCount(0);
  await open(page, "/stocks/005930");
  await expect(invite(page)).toHaveCount(0);
  await expect(page.getByText(hint)).toHaveCount(0);

  await replay(page).click();
  await orderStop(page);
  await expect(close(page)).toHaveText("");
  await expect(close(page).locator("svg")).toBeVisible();
  const heading = message(page).getByRole("heading");
  await expect(heading).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close(page)).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(next(page)).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close(page)).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await introStop(page, "overview");
  await expect(message(page).getByText("한눈에 보기 1/4", { exact: true })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await orderStop(page);
  await page.keyboard.press("Escape");
  await expect(replay(page)).toBeFocused();
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await page.getByRole("tab", { name: "회사 상태" }).click();
  await expect(page.getByRole("tabpanel", { name: "회사 상태" })).toBeVisible();
});

test("안내 페이지에서 다시 시작하고 뒤로 이동하면 강조와 잠금이 사라져요", async ({ page }) => {
  await finishDemo(page);
  await open(page);
  await page.goto("/guide");
  await page.getByRole("link", { name: "종목 상세 가이드" }).click();
  await orderStop(page);
  await page.goBack();
  await expect(page).toHaveURL("/guide");
  await expect(page.locator(".driver-overlay")).toHaveCount(0);
  await expect(page.locator("[inert]")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "종목 상세 가이드" })).toBeVisible();
});

test("로그아웃 상태에서도 이용 안내의 종목 상세 안내를 시작할 수 있어요", async ({ page }) => {
  await page.goto("/guide");
  await page.getByRole("link", { name: "종목 상세 가이드" }).click();
  await orderStop(page);
  await expect(message(page)).not.toContainText(/진단 결과|추종형|독립 분석형|적극 축적형|자산 보존형/);
  await expect(message(page)).toContainText("성향에 따라 순서가 달라져요.");
  await close(page).click();
  await expect(invite(page)).toHaveCount(0);
  await expect(replay(page)).toBeFocused();
});

test("기록이 깨졌거나 저장을 거부해도 종목 상세와 안내를 읽을 수 있어요", async ({ page }) => {
  await finishDemo(page);
  await page.evaluate((key) => localStorage.setItem(key, "{"), demoKey);
  await open(page);
  await expect(invite(page)).toHaveCount(0);
  await page.addInitScript((key) => {
    const read = Storage.prototype.getItem;
    const write = Storage.prototype.setItem;
    Storage.prototype.getItem = function (name) {
      if (name === key) throw new DOMException("blocked", "SecurityError");
      return read.call(this, name);
    };
    Storage.prototype.setItem = function (name, value) {
      if (name === key) throw new DOMException("blocked", "SecurityError");
      return write.call(this, name, value);
    };
  }, demoKey);
  await open(page);
  await replay(page).click();
  await orderStop(page);
  await close(page).click();
  await expect(replay(page)).toBeFocused();
  await expect(invite(page)).toHaveCount(0);
  await page.getByRole("tab", { name: "시장 분위기" }).click();
  await expect(page.getByRole("tabpanel", { name: "시장 분위기" })).toBeVisible();
});

test("로그인 계정은 데모 기록과 분리되고 예전 프로필에 진단 유형을 지어내지 않아요", async ({ page }) => {
  await finishDemo(page);
  await open(page);
  await expect(invite(page)).toHaveCount(0);
  await page.locator("header summary", { hasText: "김민지" }).click();
  await page.getByRole("button", { name: "로그아웃" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL("/login");
  expect(await page.evaluate((key) => localStorage.getItem(key), demoKey)).toBeNull();

  const profile = JSON.parse(readFileSync(path.resolve(process.cwd(), "../schema/profiling_output.example.json"), "utf8"));
  await mockSupabaseAuth(page, { profile });
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이름").fill("읽는 법 테스터");
  await page.getByLabel("이메일").fill("reading@example.com");
  await page.getByLabel("비밀번호").fill("demo-only-123");
  for (const box of await page.getByRole("checkbox").all()) await box.check();
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL("/");
  await page.evaluate((key) => localStorage.setItem(key, '{"status":"dismissed"}'), demoKey);
  await page.route("**/rest/v1/users?**", (route) => {
    if (new URL(route.request().url()).searchParams.get("select") !== "id") return route.fallback();
    return route.fulfill({ status: 400, json: { message: "개인화 상세 조회 실패" } });
  });
  await open(page, "/stocks/005930");
  await expect(invite(page)).toHaveCount(0);
  await replay(page).click();
  await orderStop(page);
  await expect(message(page)).toContainText("성향에 따라 순서가 달라져요.");
});

test("자료가 없는 종목은 미제공 상태가 있는 패널을 가리켜요", async ({ page }) => {
  await finishDemo(page);
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", (route) => route.fulfill({ json: [] }));
  await open(page, "/stocks/035420");
  await replay(page).click();
  await orderStop(page);
  const chapters = [
    { tab: "overview", label: "한눈에 보기", target: "overview-summary", text: "지금은 표시할 모델 신호가 없어요." },
    { tab: "trading", label: "누가 사고팔았나", target: "trading-heading" },
    { tab: "news", label: "시장 분위기", target: "news-heading", text: "뉴스가 모이면 이곳에서 기사 분위기의 흐름을 볼 수 있어요." },
    { tab: "model", label: "모델이 본 이유", target: "model-heading" },
    { tab: "company", label: "회사 상태", target: "company-heading" },
  ];
  for (const { tab, label, target, text } of chapters) {
    await next(page).click();
    await introStop(page, tab);
    await expect(message(page).getByText(`${label} 1/2`, { exact: true })).toBeVisible();
    await next(page).click();
    await stop(page, tab, target);
    await expect(message(page).getByText(`${label} 2/2`, { exact: true })).toBeVisible();
    if (text) await expect(message(page)).toContainText(text);
  }
});

for (const width of [320, 390, 1280]) {
  test(`동작 줄이기와 ${width}px에서 대상과 말풍선의 버튼이 보여요`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 660 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await finishDemo(page);
    await open(page);
    await replay(page).click();
    await orderStop(page);
    await expect(page.locator("body")).toHaveClass(/driver-simple/);

    const tabRail = page.locator("[data-reading-tablist]");
    const tabLayout = () => tabRail.evaluate((rail) => {
      const bounds = rail.getBoundingClientRect();
      const tabs = [...rail.querySelectorAll('[role="tab"]')].map((tab) => tab.getBoundingClientRect());
      return {
        rows: new Set(tabs.map(({ top }) => top)).size,
        allInRail: tabs.every(({ left, right, top, bottom }) =>
          left >= bounds.left && right <= bounds.right && top >= bounds.top && bottom <= bounds.bottom),
      };
    });
    for (const [phase, label] of [
      ["order", "읽는 순서"],
      ["overview-intro", "한눈에 보기 1/4"],
      ["focus", "한눈에 보기 2/4"],
    ]) {
      await advanceUntil(page, message(page).getByText(label, { exact: true }));
      await expect(message(page)).toBeInViewport({ ratio: 1 });
      await expect(next(page)).toBeInViewport({ ratio: 1 });
      await expect(close(page)).toBeInViewport({ ratio: 1 });
      if (width === 320 && phase === "order") {
        await expect.poll(tabLayout).toMatchObject({ rows: 2, allInRail: true });
      }
      if (width === 320 && phase === "focus") await expect.poll(tabLayout).toMatchObject({ rows: 1 });
      for (const button of [next(page), previous(page)]) {
        if (!await button.isVisible()) continue;
        const box = (await button.boundingBox())!;
        expect(box.width).toBeGreaterThanOrEqual(44);
        expect(box.height).toBeGreaterThanOrEqual(44);
        expect((await button.locator("span").boundingBox())!.height).toBe(32);
      }
      if (width !== 390 || phase === "overview-intro") {
        await testInfo.attach(`reading-${phase}-${width}`, {
          body: await page.screenshot(),
          contentType: "image/png",
        });
      }
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    if (width === 320) {
      await previous(page).click();
      await introStop(page, "overview");
      await previous(page).click();
      await orderStop(page);
      await expect.poll(tabLayout).toMatchObject({ rows: 2, allInRail: true });
    }
    await page.keyboard.press("Escape");
    await expect(replay(page)).toBeFocused();
    if (width === 320) await expect.poll(tabLayout).toMatchObject({ rows: 1 });

    if (width !== 390) {
      await replay(page).click();
      for (const [chapter, target, shot] of [
        ["overview", "overview-summary", "overview-1"],
        ["overview", "overview-cohort", "overview-2"],
        ["overview", "overview-range", "overview-3"],
        ["trading", "tab-button", "trading-intro"],
        ["trading", "trading-total", "trading"],
        ["news", "news-chart", "news-chart"],
        ["news", "news-periods", "news-periods"],
        ["model", "model-histogram", "model-histogram"],
        ["model", "model-bars", "model-bars"],
        ["model", "model-price-mood", "model-price-mood"],
        ["company", "company-metric", "company"],
        ["company", "company-earnings", "company-earnings"],
        ["company", "company-debt", "company-debt"],
        ["company", "company-valuation", "company-valuation"],
      ]) {
        const highlight = target === "tab-button"
          ? page.locator(`#stock-tab-${chapter}.driver-active-element`)
          : activePanel(page).locator(`.driver-active-element[data-reading-target="${target}"]`);
        await advanceUntil(page, highlight);
        if (target === "tab-button") await introStop(page, chapter);
        else await stop(page, chapter, target);
        await expect(message(page)).toBeInViewport({ ratio: 1 });
        await expect(highlight).toBeInViewport({ ratio: 1 });
        await expect.poll(async () => {
          const [bubble, anchor] = await Promise.all([message(page).boundingBox(), highlight.boundingBox()]);
          if (!bubble || !anchor) return `${shot}: 대상이나 말풍선이 보이지 않아요.`;
          const overlaps = bubble.y + bubble.height > anchor.y && anchor.y + anchor.height > bubble.y &&
            bubble.x + bubble.width > anchor.x && anchor.x + anchor.width > bubble.x;
          return overlaps ? { shot, bubble, anchor } : null;
        }).toBeNull();
        await expect(message(page).getByRole("button", { name: /^(다음|완료)$/ })).toBeInViewport({ ratio: 1 });
        await testInfo.attach(`reading-${shot}-${width}`, {
          body: await page.screenshot(),
          contentType: "image/png",
        });
      }
      await page.keyboard.press("Escape");
      await expect(replay(page)).toBeFocused();
    }
  });
}

test("안내 도중 화면을 좁혀도 강조 대상과 말풍선이 함께 보여요", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/guide");
  await page.getByRole("link", { name: "종목 상세 가이드" }).click();
  await advanceUntil(page, activePanel(page).locator('.driver-active-element[data-reading-target="news-heading"]'));
  await stop(page, "news", "news-heading");

  const target = activePanel(page).locator('[data-reading-target="news-heading"]');
  await expect(target).toBeInViewport({ ratio: 1 });
  await page.setViewportSize({ width: 320, height: 660 });
  await expect(target).toBeInViewport({ ratio: 1 });
  await expect(message(page)).toBeInViewport({ ratio: 1 });
});
