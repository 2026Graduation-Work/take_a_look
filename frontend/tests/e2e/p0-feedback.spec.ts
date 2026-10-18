import { expect, test, type Page } from "@playwright/test";
import { mockSupabaseAuth } from "./supabase-mock";

// 사전 참가자 P0(10/13, 실제 가입) 이해 문제 4건(#272)
test.beforeEach(({ page }) => page.on("dialog", (dialog) => void dialog.accept()));

async function demoReady(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL("/");
}

const signal = {
  stock_code: "005930", name: "삼성전자", close: 70_000, as_of: "2026-10-13", status: "available",
  scores: { down: 0.6, neutral: 0.2, up: 0.2 },
};

test("1. 신호 방향과 함께 '앞으로 4주'를 한 번씩 보여 미래 방향임을 보인다", async ({ page }) => {
  await page.route(/\/rest\/v1\/latest_chart_signal_snapshots/, (route) => route.fulfill({ json: [signal] }));
  await page.route(/\/rest\/v1\/stocks\?/, (route) =>
    route.fulfill({ json: [{ code: "005930", market: "KOSPI", risk_grade: 3, risk_flags: [] }] }));
  await demoReady(page);
  // 강한 신호 목록: 기간은 섹션 제목에 한 번, 방향은 묶음 제목. 줄에는 종목명·코드만
  const strong = page.getByRole("region", { name: "오늘 신호가 강한 종목" });
  await expect(strong.getByRole("heading", { name: "하락" })).toBeVisible();
  await expect(strong.getByRole("heading", { name: "상승" })).toHaveCount(0);
  await expect(page.locator('[data-stock-row="005930"]')).toHaveText("삼성전자005930");
  const tile = page.getByRole("list", { name: "보유 종목별 오늘 모델 신호" }).getByRole("listitem", { name: /삼성전자/ });
  await expect(tile).toHaveAccessibleName(/앞으로 4주 하락 신호/);
  // 보유 맵 아래는 색 범례만(설명 문장 없음), '틀릴 수 있다'는 맨 아래 면책 문구에
  await expect(page.getByText(/방향이에요|맞는다는 보장/)).toHaveCount(0);
  await expect(page.getByText(/참고 정보로 틀릴 수 있습니다/)).toBeVisible();
});

test("2. 첫 화면은 '판단은 내가, 근거는 여기서'를 먼저 말한다", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("판단은 내가, 근거는 여기서")).toBeVisible();
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await expect(page.getByText(/살 종목을 골라 주지 않아요/)).toBeVisible();
});

test("3. 다른 유형으로 바꾸면 근거 순서가 바뀌었는지 알려 준다", async ({ page }) => {
  await demoReady(page);
  await page.goto("/stocks/005930");
  const labels: Record<string, string> = { PRESERVER: "자산 보존형", FOLLOWER: "추종형", INDEPENDENT: "독립 분석형", ACCUMULATOR: "적극 축적형" };
  const mine = labels[(await page.locator("[data-bit-type]").getAttribute("data-bit-type"))!];
  await page.getByText("다른 유형이라면?").click();
  const note = page.locator("details p[aria-live=polite]");
  await page.getByRole("button", { name: mine }).click(); // 내 유형 그대로 → 순서 같음
  await expect(note).toHaveText("이 종목은 유형과 관계없이 같은 순서예요.");
  await page.getByRole("button", { name: mine === "추종형" ? "자산 보존형" : "추종형" }).click();
  await expect(note).toHaveText("근거 순서가 바뀌었어요.");
});

async function backStepsOneAtATime(page: Page) {
  await page.getByRole("button", { name: "시작하기" }).click();
  for (const number of [1, 2, 3]) {
    await expect(page.getByText(`질문 ${number}/16`)).toBeVisible();
    await page.locator("fieldset input").first().check();
    await page.getByRole("button", { name: "다음", exact: true }).click();
  }
  await expect(page.getByText("질문 4/16")).toBeVisible();
  await page.goBack();
  await expect(page.getByText("질문 3/16")).toBeVisible();
  await page.goBack();
  await expect(page.getByText("질문 2/16")).toBeVisible();
  // 화면의 "이전"과 브라우저 기록이 같은 길을 쓴다
  await page.getByRole("button", { name: "이전" }).click();
  await expect(page.getByText("질문 1/16")).toBeVisible();
  await page.goForward();
  await expect(page.getByText("질문 2/16")).toBeVisible();
  await page.goBack();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toBeVisible();
  await expect(page).toHaveURL(/\/survey$/);
}

test("4. 진단 중 브라우저 뒤로 가기는 한 단계씩 돌아간다(데모)", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await backStepsOneAtATime(page);
});

test("4. 진단 중 브라우저 뒤로 가기는 한 단계씩 돌아간다(가입)", async ({ page }) => {
  await mockSupabaseAuth(page);
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이름").fill("기록 사용자");
  await page.getByLabel("이메일").fill("history@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL(/\/survey$/);
  await backStepsOneAtATime(page);
});

test("4. 진단 완료 → 대시보드에서 뒤로 가기 두 번에 같은 화면에 갇히지 않는다(데모)", async ({ page }) => {
  await demoReady(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/$/);
  const urls: string[] = [];
  for (let i = 0; i < 2; i++) {
    await page.goBack();
    await page.waitForLoadState();
    urls.push(page.url());
  }
  // 대시보드로 되돌려 보내는 화면이 끼면 두 번 모두 "/"에 머문다
  expect(urls.some((url) => !/\/$/.test(new URL(url).pathname))).toBe(true);
});
