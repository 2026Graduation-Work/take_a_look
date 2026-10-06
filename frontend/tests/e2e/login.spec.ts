import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { mockSupabaseAuth } from "./supabase-mock";

const EXAMPLE_PROFILE = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "../schema/profiling_output.v1_1.example.json"), "utf8"),
);

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
  await page.getByLabel("이름").fill("최중현");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page.getByRole("heading", { name: "Take a Look은 이렇게 도와줘요" })).toBeVisible();

  // 로그인 계정은 Supabase에 남으므로 확인 창 없이 바로 나간다(confirm-button ask=false).
  await page.getByRole("button", { name: /로그아웃|나가기/ }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
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

test("계정 삭제: 확인 창 → 로그인 화면, 같은 계정으로 다시 로그인할 수 없다", async ({ page }) => {
  await mockSupabaseAuth(page, { profile: EXAMPLE_PROFILE });
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByLabel("이름").fill("지울 사용자");
  await page.getByLabel("이메일").fill("delete-me@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "가입하고 시작" }).click();
  await expect(page).toHaveURL("/");

  await page.goto("/profile");
  await page.getByRole("button", { name: "계정 삭제" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "계정 삭제" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByLabel("이메일").fill("delete-me@example.com");
  await page.getByLabel("비밀번호").fill("secret123");
  await page.getByRole("button", { name: "로그인", exact: true }).click();
  await expect(page.locator("form p[role=alert]")).toBeVisible();
});
