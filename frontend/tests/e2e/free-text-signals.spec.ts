import { expect, test } from "@playwright/test";

test("자유 답 판정을 쉼표로 이은 글자로 보여 주고 그대로 저장한다", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  const done = page.getByRole("button", { name: "완료", exact: true });
  for (let i = 0; i < 25 && !(await done.isVisible()); i++) await page.getByRole("button", { name: "다음", exact: true }).click();
  await done.click();
  await expect(page.getByText("자유 답에서 읽은 것")).toBeVisible();
  await expect(page.getByText("남보다 늦을까 조급함, 손실 걱정")).toBeVisible();
  await expect(page.getByRole("button", { name: /지우기/ })).toHaveCount(0);
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByRole("heading", { name: "지금 가진 주식이 있나요?" })).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.ips-profile.v1") ?? "{}"));
  expect(saved.free_text_signal.extracted_signals).toEqual({ fomo_index: 0.8, panic_sell_tendency: 0.75 });

  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await page.goto("/profile");
  await expect(page.getByText("남보다 늦을까 조급함, 손실 걱정")).toBeVisible();
  await expect(page.getByRole("button", { name: /지우기/ })).toHaveCount(0);
});
