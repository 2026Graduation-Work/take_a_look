import { expect, test, type Page } from "@playwright/test";

// 로그아웃·설문 전에는 어느 주소든 로그인·설문으로 보낸다. 데모 온보딩을 끝낸 사람 기준
async function finishDemo(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  for (let i = 0; i < 25; i++) {
    if (await page.getByRole("heading", { name: "지금 가진 주식이 있나요?" }).isVisible()) break;
    const done = page.getByRole("button", { name: "완료", exact: true });
    await (await done.isVisible() ? done : page.getByRole("button", { name: "다음", exact: true })).click();
  }
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await expect(page).toHaveURL(/\/$/);
}

// 페르소나 워크스루(2026-10): 없는 종목·주소에서 영어 기본 404만 보이고 돌아갈 길이 없었다.
for (const path of ["/stocks/999999", "/stocks/abc", "/no-such-page"]) {
  test(`없는 주소 ${path}는 한국어 안내와 대시보드 링크`, async ({ page }) => {
    await finishDemo(page);
    await page.goto(path);
    await expect(page.getByRole("heading", { name: "찾는 화면이 없어요" })).toBeVisible();
    await expect(page.getByText("This page could not be found")).toHaveCount(0);
    await expect(page.getByRole("link", { name: "대시보드로 가기" })).toHaveAttribute("href", "/");
  });
}
