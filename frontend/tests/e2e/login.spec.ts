import { expect, test } from "@playwright/test";
import { mockSupabaseAuth } from "./supabase-mock";

test("이메일 회원가입 → 로그아웃 → 같은 계정으로 다시 로그인", async ({ page }) => {
  await mockSupabaseAuth(page);
  const email = "new-user@example.com";
  const password = "secret123";

  await page.goto("/login");
  await expect(page.getByText("초보 투자자를 위한 판단 근거 서비스")).toBeVisible();
  await expect(page.getByText("가입 없이 예시 사용자")).toHaveCount(0);
  await page.getByRole("button", { name: "이메일로 시작" }).click();

  // 이메일 화면: 워드마크 아래 제목 한 줄, 데모·로그인 링크 버튼 없음, 뒤로는 있음
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("로그인");
  await expect(page.getByRole("button", { name: "데모로 둘러보기" })).toHaveCount(0);
  await expect(page.getByText("로그인 링크")).toHaveCount(0);
  await page.getByRole("button", { name: "뒤로" }).click();
  await expect(page.getByRole("button", { name: "데모로 둘러보기" })).toBeVisible();
  await page.getByRole("button", { name: "이메일로 시작" }).click();

  await page.getByRole("tab", { name: "회원가입" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("회원가입");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toBeVisible();

  await page.getByRole("button", { name: /로그아웃|나가기/ }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill("wrong-pass");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator("form p[role=alert]")).toBeVisible();
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toBeVisible();
});
