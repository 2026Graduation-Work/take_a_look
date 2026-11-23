import { expect, test } from "@playwright/test";
import { TERM_INFO } from "../../lib/copy-glossary";

test("이용 안내는 로그인 없이 열리고 용어 모음은 용어 파일을 가나다순으로 보인다", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("link", { name: "이용 안내" })).toHaveCount(0);
  await page.getByRole("button", { name: /이메일로 시작/ }).click();
  await expect(page.getByRole("link", { name: "이용 안내" })).toHaveCount(0);
  await page.getByRole("tab", { name: "회원가입" }).click();
  await page.getByRole("link", { name: "이용 안내" }).click();
  await expect(page).toHaveURL(/\/guide$/);
  await expect(page.getByRole("heading", { level: 1, name: "이용 안내" })).toBeVisible();
  const toc = page.getByRole("navigation", { name: "목차" }).getByRole("link");
  await expect(toc).toHaveCount(6);
  await toc.nth(4).click();
  await expect(page).toHaveURL(/#terms$/);
  const labels = Object.values(TERM_INFO).map(({ label }) => label).sort((a, b) => a.localeCompare(b, "ko"));
  await expect(page.locator("#terms dt")).toHaveText(labels);
  await expect(page.locator("#notes")).toContainText("투자 판단과 책임은 투자자 본인에게 있어요.");
});

test("개인정보 처리방침은 로그인 없이 열리고, 하단과 가입 화면에서 간다", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(page.getByRole("heading", { level: 1, name: "개인정보 처리방침" })).toBeVisible();
  for (const text of ["Supabase", "Vercel", "fourmi103@g.skku.edu", "계정 삭제", "어디에도 보내지 않아요"]) {
    await expect(page.locator("main")).toContainText(text);
  }
  await expect(page.locator("footer").getByRole("link", { name: "개인정보 처리방침" })).toBeVisible();
  await page.goto("/login");
  await page.getByRole("button", { name: "이메일로 시작" }).click();
  await page.getByRole("tab", { name: "회원가입" }).click();
  await expect(page.getByRole("link", { name: "개인정보 처리방침" })).toHaveAttribute("href", "/privacy");
});
