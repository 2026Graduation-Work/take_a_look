import { expect, test, type Page } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 헤더 통일(10/20): 모든 화면의 로고 상자 크기와 위치, 헤더 높이가 대시보드와 같다(공용 BrandHeader)
async function logoBox(page: Page) {
  const header = page.locator("header").first();
  await expect(header).toBeVisible();
  const logo = await header.getByRole("link", { name: "대시보드" }).boundingBox();
  const bar = await header.boundingBox();
  return { logo, height: bar?.height };
}

for (const width of [1280, 390]) {
  test(`헤더: 모든 화면의 로고 상자와 헤더 높이가 대시보드와 같다(${width})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    // 로그인 전: 로그인, 이용 안내(로고만)
    await page.goto("/login");
    const signedOut = [await logoBox(page)];
    await page.goto("/guide");
    signedOut.push(await logoBox(page));
    await expect(page.locator("header").getByRole("link")).toHaveCount(1);

    await finishDemo(page);
    await page.setViewportSize({ width, height: 900 });
    const base = await logoBox(page); // 대시보드
    // 데모 배너가 위에 붙어 y가 배너 높이만큼 내려가므로 로그인 전 화면은 크기와 x만 비교한다
    for (const box of signedOut) {
      expect(box.logo?.width).toBe(base.logo?.width);
      expect(box.logo?.height).toBe(base.logo?.height);
      expect(box.logo?.x).toBe(base.logo?.x);
    }
    for (const path of ["/stocks/005930", "/portfolio", "/profile", "/performance", "/guide", "/survey", "/없는-주소"]) {
      await page.goto(path);
      const box = await logoBox(page);
      expect(box.logo, path).toEqual(base.logo);
      // 390에서 둘째 줄(검색, 설문 단계)이 붙는 화면은 높이가 다르다. 로고 줄 위치만 같으면 된다
      if (width === 1280) expect(box.height, path).toBe(base.height);
    }
  });
}
