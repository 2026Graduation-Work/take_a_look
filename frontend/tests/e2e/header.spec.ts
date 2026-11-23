import { expect, test, type Page } from "@playwright/test";
import { finishDemo } from "./demo-steps";

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
    await page.goto("/login");
    const signedOut = [await logoBox(page)];
    await page.goto("/guide");
    signedOut.push(await logoBox(page));
    await expect(page.locator("header").getByRole("link")).toHaveCount(1);

    await finishDemo(page);
    await page.setViewportSize({ width, height: 900 });
    const base = await logoBox(page);
    for (const box of signedOut) {
      expect(box.logo?.width).toBe(base.logo?.width);
      expect(box.logo?.height).toBe(base.logo?.height);
      expect(box.logo?.x).toBe(base.logo?.x);
    }
    for (const path of ["/stocks/005930", "/portfolio", "/profile", "/performance", "/guide", "/survey", "/없는-주소"]) {
      await page.goto(path);
      const box = await logoBox(page);
      expect(box.logo, path).toEqual(base.logo);
      if (width === 1280) expect(box.height, path).toBe(base.height);
    }
  });
}
