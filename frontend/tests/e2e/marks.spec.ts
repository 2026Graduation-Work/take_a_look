import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { mockSupabaseAuth } from "./supabase-mock";

const EXAMPLE_PROFILE = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "../schema/profiling_output.v1_1.example.json"), "utf8"),
);

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

// 관심 종목 추가 → 대시보드 표시 → 편집 화면에서 삭제 → 대시보드에서 사라짐, 메모 저장 → 다시 열면 표시 → 고치기·지우기
async function watchAndNote(page: Page) {
  await expect(page.getByRole("region", { name: "관심 종목" })).toHaveCount(0);
  await page.goto("/stocks/005930");
  await page.getByRole("button", { name: "관심 종목에 두기" }).click();
  await expect(page.getByRole("button", { name: /관심 종목 ✓/ })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "판단 메모 쓰기" }).click();
  await page.getByRole("textbox", { name: "내 판단 메모" }).fill("실적 발표 뒤에 다시 보기");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByText(/지난 메모 · \d{4}\.\d{2}\.\d{2}/)).toBeVisible();

  await page.goto("/");
  const watched = page.getByRole("region", { name: "관심 종목" });
  await expect(watched.getByRole("link", { name: /삼성전자/ })).toBeVisible();

  await page.goto("/stocks/005930");
  await expect(page.getByText("실적 발표 뒤에 다시 보기")).toBeVisible();
  await page.getByRole("button", { name: "고치기" }).click();
  await page.getByRole("textbox", { name: "내 판단 메모" }).fill("10월 말 실적 발표 뒤에 다시 보기");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await page.reload();
  await expect(page.getByText("10월 말 실적 발표 뒤에 다시 보기")).toBeVisible();
  await page.getByRole("button", { name: "지우기" }).click();
  await expect(page.getByText(/지난 메모/)).toHaveCount(0);

  await page.goto("/portfolio");
  await page.getByRole("button", { name: "삼성전자 관심 종목에서 삭제" }).click();
  await page.goto("/");
  await expect(page.getByRole("region", { name: "관심 종목" })).toHaveCount(0);
}

// 지우기·삭제·데모 로그아웃은 확인 창을 띄운다(DESIGN.md 0-1 ④). 테스트는 늘 "확인"을 누른다.
test.beforeEach(({ page }) => page.on("dialog", (dialog) => void dialog.accept()));

test("데모: 관심 종목·판단 메모가 브라우저에 남고 다시 읽힌다", async ({ page }) => {
  await demoReady(page);
  await watchAndNote(page);
});

test("로그인: 관심 종목·판단 메모가 Supabase에 저장되고 다시 읽힌다", async ({ page }) => {
  const { tables } = await mockSupabaseAuth(page, { profile: EXAMPLE_PROFILE });
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이메일").fill("marks@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/stocks/005930");
  await page.getByRole("button", { name: "관심 종목에 두기" }).click();
  await expect.poll(() => tables.watchlist.get("005930")?.is_active).toBe(true);
  await page.getByRole("button", { name: "판단 메모 쓰기" }).click();
  await page.getByRole("textbox", { name: "내 판단 메모" }).fill("DB에 남는 메모");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect.poll(() => tables.stock_notes.get("005930")?.note).toBe("DB에 남는 메모");

  // 브라우저 값을 지워도 Supabase에서 다시 읽어 온다
  await page.evaluate(() => {
    localStorage.removeItem("takealook.watchlist.v1");
    localStorage.removeItem("takealook.stock-notes.v1");
  });
  await page.goto("/");
  await expect(page.getByRole("region", { name: "관심 종목" }).getByRole("link", { name: /삼성전자/ })).toBeVisible();
  await page.goto("/stocks/005930");
  await expect(page.getByText("DB에 남는 메모")).toBeVisible();

  await page.getByRole("button", { name: "지우기" }).click();
  await expect.poll(() => tables.stock_notes.has("005930")).toBe(false);
  await page.getByRole("button", { name: /관심 종목 ✓/ }).click();
  await expect.poll(() => tables.watchlist.get("005930")?.is_active).toBe(false);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "관심 종목" })).toHaveCount(0);
});

test("로그인 + stock_notes 테이블 적용 전: 메모는 브라우저에 저장되고 다시 읽힌다", async ({ page }) => {
  await mockSupabaseAuth(page, { profile: EXAMPLE_PROFILE, notesTableMissing: true });
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이메일").fill("fallback@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/stocks/005930");
  await page.getByRole("button", { name: "판단 메모 쓰기" }).click();
  await page.getByRole("textbox", { name: "내 판단 메모" }).fill("테이블 없어도 남는 메모");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.locator("p[role=alert]")).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("테이블 없어도 남는 메모")).toBeVisible();
});

