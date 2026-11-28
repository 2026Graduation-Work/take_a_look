import { expect, test } from "@playwright/test";
import { BEGINNER_TIPS } from "../../lib/beginner-tips";
import { finishDemo } from "./demo-steps";

const first = BEGINNER_TIPS[0];
const habit = BEGINNER_TIPS.find(tip => tip.category === "투자 습관")!;

async function headingTextX(page: import("@playwright/test").Page) {
  return page.locator("main h1").first().evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return Math.round(range.getBoundingClientRect().x);
  });
}

test("안내 세 화면의 제목은 같은 시작선에서 시작한다", async ({ page }) => {
  for (const width of [1280, 390]) {
    await page.setViewportSize({ width, height: 900 });
    const xs = [];
    for (const path of ["/guide", "/tips", "/glossary"]) {
      await page.goto(path);
      xs.push(await headingTextX(page));
    }
    expect(new Set(xs).size).toBe(1);
  }
});

test("데스크톱은 상세에서도 같은 주제 바를 유지하고 목록 필터를 복원한다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/tips?category=habits");
  const navigation = page.getByRole("navigation", { name: "알고 계셨나요? 주제" });
  await expect(navigation).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("투자 습관");
  const navBox = await navigation.boundingBox();
  const listBox = await page.getByRole("list", { name: "알고 계셨나요? 목록", exact: true }).boundingBox();
  expect(navBox!.y + navBox!.height).toBeLessThanOrEqual(listBox!.y);
  await expect(page.getByText(/개 중 .*번부터/)).toHaveCount(0);
  await page.getByRole("link", { name: habit.title, exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === `/tips/${habit.id}` && url.searchParams.get("category") === "habits");
  await expect(navigation).toBeVisible();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(habit.title);
  const detailNavBox = await navigation.boundingBox();
  const articleBox = await page.getByRole("article").boundingBox();
  expect(detailNavBox!.y + detailNavBox!.height).toBeLessThanOrEqual(articleBox!.y);
  await page.getByRole("link", { name: "알고 계셨나요? 목록", exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === "/tips" && url.searchParams.get("category") === "habits");
  await expect(page.getByRole("link", { name: habit.title, exact: true })).toBeVisible();
});

test("전체 목록에서 읽은 팁은 전체 선택을 유지하며 직접 주소도 열 수 있다", async ({ page }) => {
  await page.goto("/tips");
  await page.getByRole("link", { name: first.title, exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === `/tips/${first.id}`);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(first.title);
  await expect(page.getByRole("link", { name: "원래 화면으로 돌아가기", exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "알고 계셨나요? 목록", exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === "/tips" && [null, "all"].includes(url.searchParams.get("category")));
});

test("제목, 요약, 설명, 계산식과 출처를 접기 없이 한 본문에서 읽는다", async ({ page }) => {
  await page.goto(`/tips/${first.id}`);
  const article = page.getByRole("article");
  await expect(article.getByRole("heading", { level: 1 })).toHaveText(first.title);
  await expect(article).toContainText(first.summary);
  for (const line of first.detail) await expect(article).toContainText(line);
  await expect(article).toContainText(first.formula!);
  await expect(article).toContainText(first.inService!);
  await expect(article).toContainText(first.checkedAt);
  await expect(article.locator("details")).toHaveCount(0);
  const withSource = BEGINNER_TIPS.find(tip => tip.sources.some(source => source.url))!;
  await page.goto(`/tips/${withSource.id}`);
  for (const source of withSource.sources.filter(source => source.url)) {
    await expect(page.getByRole("article").getByRole("link", { name: source.label, exact: true })).toHaveAttribute("href", source.url!);
  }
});

test("모바일은 상세 위에 주제 선택을 유지하고 320px에서도 가로로 넘치지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tips?category=habits");
  const subject = page.getByRole("navigation", { name: "알고 계셨나요? 주제" });
  await expect(subject).toBeVisible();
  await expect(subject.getByRole("link", { name: "투자 습관" })).toHaveAttribute("aria-current", "true");
  const subjectBox = await subject.boundingBox();
  const headingBox = await page.getByRole("heading", { level: 1 }).boundingBox();
  expect(subjectBox!.y + subjectBox!.height).toBeLessThanOrEqual(headingBox!.y);
  await page.getByRole("link", { name: habit.title, exact: true }).click();
  await expect(subject).toBeVisible();
  await expect(subject.getByRole("link", { name: "투자 습관" })).toHaveAttribute("aria-current", "true");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(subject).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
  }
  await subject.getByRole("link", { name: "계산 착각" }).click();
  await expect(page).toHaveURL(url => url.pathname === "/tips" && url.searchParams.get("category") === "calculation");
});

test("기존 이용 안내 팁 링크는 새 상세로 연결하고 일반 목차는 유지한다", async ({ page }) => {
  await page.goto(`/guide#tip-${first.id}`);
  await expect(page).toHaveURL(url => url.pathname === `/tips/${first.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(first.title);
  await page.goto("/guide#beginner-tips");
  await expect(page).toHaveURL(url => url.pathname === "/tips");
  await page.goto("/guide#terms");
  await expect(page).toHaveURL(/\/glossary$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("용어 모음");
  await page.goto("/guide#notes");
  await expect(page.locator("#notes")).toBeInViewport();
  await expect(page.locator("#notes")).toContainText("틀릴 수 있어요");
  await expect(page.getByText(first.title, { exact: true })).toHaveCount(0);
});

test("팁을 읽고 선택한 종목 탭으로 돌아오며 외부 복귀 주소는 허용하지 않는다", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await finishDemo(page);
  await page.goto("/stocks/005930");
  const tab = page.getByRole("tab", { name: "회사 상태", exact: true });
  await tab.click();
  await page.getByRole("region", { name: "알고 계셨나요?" }).getByRole("link", { name: "자세히 보기" }).click();
  await expect(page).toHaveURL(url => url.pathname === `/tips/${first.id}` && url.searchParams.get("returnTo")?.includes("/stocks/005930") === true);
  const back = page.getByRole("link", { name: /돌아가기/ });
  await back.click();
  await expect(page).toHaveURL(/\/stocks\/005930/);
  await expect(page.getByRole("tab", { name: "회사 상태", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.goto(`/tips/${first.id}?returnTo=${encodeURIComponent("//example.com")}`);
  await expect(page.getByRole("link", { name: /돌아가기/ })).toHaveCount(0);
});

test("안내 탭을 거쳐 팁을 읽어도 처음 보던 종목 화면과 선택 탭으로 돌아간다", async ({ page }) => {
  await finishDemo(page);
  await page.goto("/stocks/005930?tab=company");
  await expect(page.getByRole("tab", { name: "회사 상태", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.locator("summary[aria-label$='계정 메뉴']").click();
  await page.getByRole("link", { name: "이용 안내", exact: true }).click();
  const menus = page.getByRole("navigation", { name: "안내 메뉴" });
  await menus.getByRole("link", { name: "용어 모음", exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === "/glossary" && url.searchParams.get("returnTo") === "/stocks/005930?tab=company");
  await menus.getByRole("link", { name: "알고 계셨나요?", exact: true }).click();
  await page.getByRole("link", { name: first.title, exact: true }).click();
  const back = page.getByRole("link", { name: "원래 화면으로 돌아가기", exact: true });
  await expect(back).toHaveAttribute("href", "/stocks/005930?tab=company");
  await page.reload();
  await expect(back).toHaveAttribute("href", "/stocks/005930?tab=company");
  await back.click();
  await expect(page).toHaveURL(/\/stocks\/005930\?tab=company$/);
  await expect(page.getByRole("tab", { name: "회사 상태", exact: true })).toHaveAttribute("aria-selected", "true");
});

test("안내 링크를 새 탭으로 열어도 원래 화면의 위치 주소를 보존한다", async ({ page, context }) => {
  await finishDemo(page);
  await page.goto("/profile#account");
  await page.locator("summary[aria-label$='계정 메뉴']").click();
  const entry = page.getByRole("link", { name: "이용 안내", exact: true });
  await expect.poll(async () => new URL((await entry.getAttribute("href"))!, "http://localhost").searchParams.get("returnTo")).toBe("/profile#account");
  const other = await context.newPage();
  await other.goto((await entry.getAttribute("href"))!);
  await other.getByRole("navigation", { name: "안내 메뉴" }).getByRole("link", { name: "알고 계셨나요?", exact: true }).click();
  await other.getByRole("link", { name: first.title, exact: true }).click();
  await expect(other.getByRole("link", { name: "원래 화면으로 돌아가기", exact: true })).toHaveAttribute("href", "/profile#account");
  await other.close();
});

test("존재하지 않는 팁은 다른 팁으로 대체하지 않는다", async ({ page }) => {
  await page.goto("/tips/no-such-tip");
  await expect(page.getByRole("heading", { name: /찾|없/ })).toBeVisible();
  await expect(page.getByText(first.title, { exact: true })).toHaveCount(0);
});


test("번호로 다음 페이지를 읽고 돌아와도 같은 페이지와 팁 위치를 복원한다", async ({ page, context }) => {
  await page.goto("/tips?returnTo=%2Fportfolio");
  const readTip = BEGINNER_TIPS[11];
  const list = page.getByRole("list", { name: "알고 계셨나요? 목록", exact: true });
  await expect(list.getByRole("link")).toHaveCount(6);
  await expect(page.getByRole("button", { name: /더 보기/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: readTip.title, exact: true })).toHaveCount(0);
  const pager = page.getByRole("navigation", { name: "알고 계셨나요? 페이지", exact: true });
  await pager.getByRole("link", { name: "2페이지", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(url => url.pathname === "/tips" && url.searchParams.get("page") === "2" && url.searchParams.get("returnTo") === "/portfolio");
  await expect(pager.getByRole("link", { name: "2페이지", exact: true })).toHaveAttribute("aria-current", "page");
  const nextTip = page.getByRole("link", { name: readTip.title, exact: true });
  await expect(nextTip).toBeVisible();
  await nextTip.click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(readTip.title);
  await page.getByRole("link", { name: "알고 계셨나요? 목록", exact: true }).click();
  await expect(page).toHaveURL(url => url.pathname === "/tips" && url.searchParams.get("page") === "2" && url.hash === `#tip-${readTip.id}`);
  const restored = page.getByRole("link", { name: readTip.title, exact: true });
  await expect(restored).toBeInViewport();
  await expect(restored).toBeFocused();
  await page.reload();
  await expect(restored).toBeInViewport();
  await expect(restored).toBeFocused();
  const direct = await context.newPage();
  await direct.goto(page.url());
  await expect(direct.getByRole("link", { name: readTip.title, exact: true })).toBeInViewport();
  await expect(direct.getByRole("link", { name: readTip.title, exact: true })).toBeFocused();
  await direct.close();
  await expect(page.getByRole("link", { name: /돌아가기/ })).toHaveAttribute("href", "/portfolio");
});

test("페이지를 순서대로 읽으면 42개 팁이 중복이나 빠짐 없이 나타난다", async ({ page }) => {
  const titles: string[] = [];
  for (let current = 1; current <= 7; current++) {
    await page.goto(`/tips?page=${current}`);
    const list = page.getByRole("list", { name: "알고 계셨나요? 목록", exact: true });
    await expect(list.getByRole("link")).toHaveCount(6);
    titles.push(...await list.getByRole("heading", { level: 2 }).allTextContents());
  }
  expect(titles).toEqual(BEGINNER_TIPS.map(tip => tip.title));
  await expect(page.getByRole("navigation", { name: "알고 계셨나요? 페이지" }).getByRole("link", { name: "다음 페이지", exact: true })).toHaveCount(0);
});

test("모바일 페이지 번호는 넘치지 않고 주제를 바꾸면 첫 페이지로 돌아간다", async ({ page }) => {
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/tips?page=4&returnTo=%2Fperformance");
    const pager = page.getByRole("navigation", { name: "알고 계셨나요? 페이지", exact: true });
    await expect(pager).toBeVisible();
    await expect(pager.getByRole("link", { name: "4페이지", exact: true })).toHaveAttribute("aria-current", "page");
    expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
    for (const link of await pager.getByRole("link").all()) {
      const box = await link.boundingBox();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  }
  await page.getByRole("navigation", { name: "알고 계셨나요? 주제" }).getByRole("link", { name: "투자 습관" }).click();
  await expect(page).toHaveURL(url => url.searchParams.get("category") === "habits" && [null, "1"].includes(url.searchParams.get("page")) && url.searchParams.get("returnTo") === "/performance");
  await expect(page.getByRole("link", { name: habit.title, exact: true })).toBeVisible();
});

test("각 팁은 독립된 면과 간격으로 나뉘며 설명은 제목보다 들여쓴다", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.goto("/tips");
  const list = page.getByRole("list", { name: "알고 계셨나요? 목록", exact: true });
  const one = list.getByRole("link", { name: first.title, exact: true });
  const two = list.getByRole("link", { name: BEGINNER_TIPS[1].title, exact: true });
  const titleBox = await one.getByRole("heading").boundingBox();
  const summaryX = await one.locator("p").evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return range.getBoundingClientRect().x;
  });
  expect(summaryX - titleBox!.x).toBeGreaterThanOrEqual(8);
  const firstBox = (await one.boundingBox())!;
  const secondBox = (await two.boundingBox())!;
  expect(secondBox.y - firstBox.y - firstBox.height).toBeGreaterThanOrEqual(23);
});

test("존재하지 않는 페이지 번호를 넣어도 빈 목록 대신 유효한 페이지를 보여 준다", async ({ page }) => {
  await page.goto("/tips?page=999");
  await expect(page.getByRole("link", { name: BEGINNER_TIPS[41].title, exact: true })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "알고 계셨나요? 페이지" }).getByRole("link", { name: "7페이지", exact: true })).toHaveAttribute("aria-current", "page");
  await page.goto("/tips?page=not-a-number");
  await expect(page.getByRole("link", { name: first.title, exact: true })).toBeVisible();
});

test("중복 주소 값은 본문과 주제 바가 같은 첫 값을 사용한다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tips?category=habits&category=costs&returnTo=%2Fportfolio&returnTo=%2Fperformance");
  await expect(page.getByRole("navigation", { name: "알고 계셨나요? 주제" }).getByRole("link", { name: "투자 습관" })).toHaveAttribute("aria-current", "true");
  await expect(page.getByRole("link", { name: habit.title, exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: /돌아가기/ })).toHaveAttribute("href", "/portfolio");
});
