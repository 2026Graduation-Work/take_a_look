import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

const SESSION_KEY = "takealook.demo-session.v1";
const PROFILE_KEY = "takealook.ips-profile.v1";
const HOLDINGS_KEY = "takealook.holdings.v1";
const ANSWERS_KEY = "takealook.survey-answers.v1";

// 김민지 mock(추종형)과 다른 "적극 축적형"이 나와야 대시보드·상세가 설문 결과를 쓰는지 가려진다.
const BANK = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "lib/profiling/style-questions.json"), "utf8"),
) as {
  likert: { options: { value: number; label: string }[] };
  questions: { id: string; text: string; direction: number; short: boolean }[];
};
const LIKERT_LABEL = new Map(BANK.likert.options.map(({ value, label }) => [value, label]));
const ANSWER_LABEL = new Map(
  BANK.questions
    .filter(({ short }) => short)
    .map(({ text, direction }) => [text, LIKERT_LABEL.get(3 + 2 * direction)!]),
);

async function answerCurrentQuestion(page: Page): Promise<void> {
  const group = page.locator("fieldset");
  const text = (await group.locator("legend").innerText()).trim();
  const label = ANSWER_LABEL.get(text);
  if (!label) throw new Error(`문항 정의에 없는 문항: ${text}`);
  await group.getByLabel(label, { exact: true }).check();
  await page.getByRole("button", { name: "다음", exact: true }).click();
}

async function startDemo(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await expect(page).toHaveURL(/\/survey$/);
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toBeVisible();
  await expect(page.getByRole("list", { name: "시작 단계" })).toContainText("1 성향2 보유 종목3 시작");
}

test.beforeEach(({ page }) => page.on("dialog", (dialog) => void dialog.accept()));

test("new user: 환영 -> 16문항 -> 결과 -> 보유 종목 1개 -> 대시보드 맵 -> 상세 -> logout", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => {
    const select = new URL(route.request().url()).searchParams.get("select") ?? "";
    if (!select.includes("close:payload")) return route.fallback();
    return route.fulfill({ json: [{ stock_code: "005930", close: 275000, as_of: "2026-09-21", status: "available",
      scores: { down: 0.1, neutral: 0.1, up: 0.8 } }] });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Take a Look 시작" })).toBeVisible();
  await expect(page.getByText(/이메일로 시작|계정 기능이 아직 연결되지 않았어요/).first()).toBeVisible();
  await expect(page.getByText("데모 계정")).toHaveCount(0);

  await startDemo(page);
  await expect(page.getByText("데모 계정")).toBeVisible();
  await assertNoHorizontalOverflow(page, 390, 844);
  await page.setViewportSize({ width: 1024, height: 900 });
  await page.getByRole("button", { name: "시작하기" }).click();

  for (let number = 1; number <= 16; number += 1) {
    await expect(page.getByText(`질문 ${number}/16`)).toBeVisible();
    await answerCurrentQuestion(page);
    if (number === 3) {
      await expect(page.getByText("질문 4/16")).toBeVisible();
      await page.getByRole("button", { name: "이전" }).click();
      await expect(page.getByText("질문 3/16")).toBeVisible();
      await expect(page.locator("fieldset input:checked")).toHaveCount(1);
      await page.getByRole("button", { name: "다음", exact: true }).click();
    }
    if (number === 8) {
      await expect(page.getByText("질문 9/16")).toBeVisible();
      await page.reload();
      await expect(page.getByText("저장해 둔 응답을 불러왔어요", { exact: false })).toBeVisible();
      await expect(page.getByText("질문 9/16")).toBeVisible();
    }
  }

  await expect(page.getByText("마무리 1/3")).toBeVisible();
  await page.getByLabel("6개월~2년").check();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByText("마무리 2/3")).toBeVisible();
  await page.getByLabel("SPAC", { exact: false }).check();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByText("마무리 3/3")).toBeVisible();
  await page.getByRole("button", { name: "완료" }).click();

  await expect(page.getByRole("heading", { name: "적극 축적형" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "적극 축적형" })).toBeFocused();
  await expect(page.getByRole("status")).toContainText("투자 성향 진단을 마쳤어요");
  await expect(page.getByRole("alert")).not.toContainText(BANK.questions[0].text);
  await expect(page.getByRole("button", { name: "추가 질문 8개" })).toBeVisible();
  await expectStoredOnboardingData(page, { session: true, profile: false });
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByRole("heading", { name: "지금 가진 주식이 있나요?" })).toBeVisible();
  await expectStoredOnboardingData(page, { session: true, profile: true });
  const storedTypes = await page.evaluate((key) => {
    const profile = JSON.parse(localStorage.getItem(key) ?? "{}");
    return profile.style_axes.axes.map((axis: { ratio: number; question_count: number }) => [
      axis.ratio,
      axis.question_count,
    ]);
  }, PROFILE_KEY);
  expect(storedTypes).toEqual(Array(8).fill([1, 2]));

  await expect(page.getByText("예시로 넣어 뒀어요, 바꿔도 돼요.")).toBeVisible();
  for (const name of ["삼성전자", "카카오", "셀트리온", "현대차"]) {
    await page.getByRole("button", { name: `${name} 삭제` }).click();
  }
  await page.getByLabel("종목 검색").fill("삼성전자");
  await page.getByLabel("종목 검색").press("Enter");
  await expect(page.getByLabel("삼성전자 수량")).toBeFocused();
  await page.getByLabel("삼성전자 수량").fill("10");
  await expect(page.getByRole("heading", { name: "넣은 종목 1개" })).toBeVisible();
  await page.getByRole("button", { name: "저장하고 시작" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("보유 종목 중 하락 신호는 없어요.");
  await expect(page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" }).getByRole("listitem")).toHaveCount(1);
  await expect(page.getByRole("listitem", { name: /삼성전자,.*평가금액 275만원/ })).toBeVisible();
  await expect(page.getByText("종가가 없는 종목은 매입금액 기준")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "신호가 강한 종목" })).toBeVisible();
  await expect(page.getByText("데모 계정")).toBeVisible();
  await expect(page.getByText("적극 축적형", { exact: true })).toBeVisible();
  await expect(page.getByText("추종형", { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("적극 축적형", { exact: true })).toBeVisible();
  await assertNoHorizontalOverflow(page, 390, 844);

  await page.setViewportSize({ width: 1024, height: 900 });
  const header = page.locator("header");
  await expect(header.getByRole("navigation", { name: "주요 화면" })).toHaveCount(0);
  await expect(header.getByRole("link", { name: "이용 안내" })).toBeHidden();
  await expect(header.getByText("적극 축적형")).toHaveCount(0);
  const accountMenu = header.locator("summary", { hasText: "김민지" });
  await accountMenu.click();
  await expect(header.locator("details :is(a, button):visible")).toHaveText(["보유 종목", "내 투자 성향", "이용 안내", "계정 설정", "로그아웃"]);
  await expect(header.getByRole("link", { name: "내 성향 다시 진단" })).toHaveCount(0);
  await expect(header.getByRole("button", { name: "로그아웃" })).toBeVisible();
  await accountMenu.click();

  await page.locator("[data-stock-row]").first().click();
  await expect(page).toHaveURL(/\/stocks\/(005930|005380|068270)$/);
  const stockTabs = page.getByRole("tablist", { name: "종목 상세" });
  await expect(stockTabs.getByRole("tab", { selected: true })).toHaveText("한눈에 보기");
  await expect(page.getByText("데모 계정")).toBeVisible();
  const overview = page.getByRole("tabpanel", { name: "한눈에 보기" });
  await expect(overview.getByRole("heading", { name: "최근 주가" })).toBeVisible();
  await overview.getByRole("button", { name: /^모델 예측/ }).click();
  await expect(page.getByRole("tabpanel", { name: "모델 예측" }).getByRole("heading", { name: /^모델 신호/ })).toBeVisible();

  await page.locator("footer").getByRole("link", { name: "모델 성적표" }).click();
  await expect(page).toHaveURL(/\/performance$/);
  await expect(page.getByRole("heading", { name: "A/B 비교" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "시장 분위기 지표를 더하면 예측이 나아질까요?" })).toBeVisible();

  await page.locator("header summary", { hasText: "김민지" }).click();
  await page.getByRole("button", { name: "로그아웃" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "로그아웃" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expectStoredOnboardingData(page, { session: false, profile: false });
  expect(browserErrors).toEqual([]);
});

test("new user: 보유 종목을 모두 지우고 '보유 없이 시작' -> 대시보드 빈 상태", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await startDemo(page);
  await page.getByRole("button", { name: "시작하기" }).click();
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await assertNoHorizontalOverflow(page, 390, 844);
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  for (const name of ["삼성전자", "카카오", "셀트리온", "현대차"]) {
    await page.getByRole("button", { name: `${name} 삭제` }).click();
  }
  await page.getByRole("button", { name: "보유 없이 시작" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("오늘 모델 신호가 강한 종목은 1개예요.");
  await expect(page.getByText("관심 가는 종목을 검색해 보세요")).toBeVisible();
  await page.goto("/survey");
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toHaveCount(0);
  await expect(page.getByText("질문 1/16")).toBeVisible();
  expect(browserErrors).toEqual([]);
});

// 2027-02 이후 제거: 옛 서비스명 저장 키(signallab.*) 이전
test("옛 저장 키(signallab.*)로 저장된 데모 상태가 새로고침 후 새 키로 옮겨지고 유지된다", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await startDemo(page);
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).not.toContainText("불러오는 중");
  const heading = await page.getByRole("heading", { level: 1 }).innerText();

  const before = await page.evaluate((keys) => {
    const values: Record<string, string | null> = {};
    for (const key of keys) {
      values[key] = localStorage.getItem(key);
      localStorage.setItem(key.replace("takealook.", "signallab."), values[key] ?? "");
      localStorage.removeItem(key);
    }
    return values;
  }, [SESSION_KEY, PROFILE_KEY, HOLDINGS_KEY, ANSWERS_KEY]);
  expect(Object.values(before).every((value) => value !== null)).toBe(true);

  await page.reload();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(heading);
  const after = await page.evaluate(() =>
    Object.fromEntries(
      Object.keys(localStorage)
        .filter((key) => key.startsWith("signallab.") || key.startsWith("takealook."))
        .map((key) => [key, localStorage.getItem(key)]),
    ),
  );
  expect(after).toEqual(before);
  expect(browserErrors).toEqual([]);
});

function collectBrowserErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`page: ${error.message}`));
  return errors;
}

async function assertNoHorizontalOverflow(
  page: Page,
  width: number,
  height: number,
): Promise<void> {
  await page.setViewportSize({ width, height });
  await page.waitForFunction(
    () =>
      document.documentElement.scrollWidth <=
      document.documentElement.clientWidth,
    undefined,
    { timeout: 2_000 },
  );
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content).toBeLessThanOrEqual(dimensions.viewport);
}

async function expectStoredOnboardingData(
  page: Page,
  present: { session: boolean; profile: boolean },
): Promise<void> {
  const stored = await page.evaluate(
    ({ sessionKey, profileKey }) => ({
      session: localStorage.getItem(sessionKey),
      profile: localStorage.getItem(profileKey),
    }),
    { sessionKey: SESSION_KEY, profileKey: PROFILE_KEY },
  );
  expect(Boolean(stored.session)).toBe(present.session);
  expect(Boolean(stored.profile)).toBe(present.profile);
}

test("설문 이전/다음 왕복: 답한 문항에서만 다음이 켜지고, 결과·보유 종목에서도 이전으로 돌아간다", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await startDemo(page);
  const note = page.getByText("맞고 틀린 답은 없어요", { exact: false });
  const start = page.getByRole("button", { name: "시작하기" });
  expect((await note.boundingBox())!.y).toBeLessThan((await start.boundingBox())!.y);
  await start.click();

  const next = page.getByRole("button", { name: "다음", exact: true });
  const back = page.getByRole("button", { name: "이전" });
  await expect(page.getByText("답은 자동으로 저장돼요")).toHaveCount(0);
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await expect(back).toBeDisabled();
  await expect(next).toBeDisabled();
  const [backBox, nextBox] = [await back.boundingBox(), await next.boundingBox()];
  expect(backBox!.x).toBeLessThan(nextBox!.x);
  expect(backBox!.height).toBe(nextBox!.height);

  await page.locator("fieldset input").first().check();
  await page.locator("fieldset input").nth(1).check();
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page.getByText("질문 2/16")).toBeVisible();
  await answerCurrentQuestion(page);
  await expect(page.getByText("질문 3/16")).toBeVisible();
  await expect(next).toBeDisabled();
  await back.click();
  await back.click();
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page.getByText("질문 2/16")).toBeVisible();
  await next.click();
  await expect(page.getByText("질문 3/16")).toBeVisible();
  await expect(next).toBeDisabled();

  await page.getByRole("button", { name: /데모 응답/ }).click();
  await expect(page.getByText("마무리 3/3")).toBeVisible();
  await page.getByRole("button", { name: "완료" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveAttribute("data-bit-type", /.+/);
  await expect(page.getByRole("button", { name: /다음: / })).toHaveCount(0);
  await back.click();
  await expect(page.getByText("마무리 3/3")).toBeVisible();
  await page.getByRole("button", { name: "완료" }).click();
  await next.click();
  await expect(page.getByRole("heading", { name: "지금 가진 주식이 있나요?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "저장하고 시작" })).toBeVisible();
  await back.click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveAttribute("data-bit-type", /.+/);
  expect(browserErrors).toEqual([]);
});

test("다시 진단: 대시보드 성향 한 줄 → 결과 → 다시 진단(지난 답 채워진 채 1번부터) → 완료 → 저장 → 대시보드", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await startDemo(page);
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL("/");

  await expect(page.getByText("목록에서 빼 둔 종목")).toHaveCount(0);
  await page.getByRole("link", { name: /내 투자 성향: 추종형/ }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole("heading", { name: "추종형" })).toBeVisible();
  await page.getByRole("button", { name: "다시 진단" }).click();

  await expect(page).toHaveURL(/\/survey$/);
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toHaveCount(0);
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await expect(page.locator("fieldset input:checked")).toHaveCount(1);
  const next = page.getByRole("button", { name: "다음", exact: true });
  for (let number = 1; number < 16 + 3; number += 1) await next.click();
  await expect(page.getByText("마무리 3/3")).toBeVisible();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "저장" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("heading", { name: "지금 가진 주식이 있나요?" })).toHaveCount(0);

  await page.goto("/survey");
  await page.getByRole("button", { name: "처음부터 새로 하기" }).click();
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await expect(page.locator("fieldset input:checked")).toHaveCount(0);
  expect(browserErrors).toEqual([]);
});
