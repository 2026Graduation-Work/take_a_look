import { expect, test, type Page } from "@playwright/test";

// DESIGN.md 0-1 ①: 누르는 것은 44px 이상. 문장 안 글자 링크와 세그먼트 탭(3장 예외)은 뺀다.
async function smallTargets(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("a, button, summary, input, select, textarea")]
      .filter((el) => {
        const box = el.getBoundingClientRect();
        if (!box.width || !box.height || box.height >= 44) return false;
        if (el instanceof HTMLInputElement && ["radio", "checkbox"].includes(el.type)) return false; // 라벨 전체가 누르는 곳
        if (el.closest(".segmented")) return false;
        return !(el.tagName === "A" && getComputedStyle(el).display === "inline" && el.closest("p"));
      })
      .map((el) => `${(el.textContent || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 20)} ${Math.round(el.getBoundingClientRect().height)}px`),
  );
}

test("모든 화면의 누르는 것이 44px 이상이다(390 폭)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const found: Record<string, string[]> = {};
  const check = async (name: string) => {
    await page.waitForLoadState("networkidle");
    const small = await smallTargets(page);
    if (small.length) found[name] = small;
  };

  await page.goto("/login");
  await check("login");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await check("survey-welcome");
  await page.getByRole("button", { name: "시작하기" }).click();
  await check("survey-question");
  await page.getByRole("button", { name: /데모 응답/ }).click();
  await page.getByRole("button", { name: "완료" }).click();
  await check("survey-result");
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await check("holdings");
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL("/");
  await check("dashboard");
  for (const path of ["/portfolio", "/profile", "/performance", "/stocks/005930"]) {
    await page.goto(path);
    await check(path);
  }
  expect(found).toEqual({});
});
