import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

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
