import { expect, test } from "@playwright/test";
import { TERM_INFO } from "../../lib/copy-glossary";

// 이용 안내: 로그인 없이 열리고, 목차가 각 절로 가고, 용어 모음은 ⓘ와 같은 출처를 가나다순으로 보인다
test("이용 안내는 로그인 없이 열리고 용어 모음은 용어 파일을 가나다순으로 보인다", async ({ page }) => {
  await page.goto("/login");
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
