import { expect, test } from "@playwright/test";

// 설문 자유 답에서 키워드로 읽은 판정을 결과 화면에 보여 주고, 지우면 보조값에서 빠진 채 저장된다(성우 개선 포인트 3)
test("자유 답 판정을 보여 주고, 지운 판정은 저장된 보조값에 없다", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click(); // 데모 자유 답: "남들 다 버는데 … 잠을 못 자요"
  // 설문 끝(완료)까지 넘기고 결과 화면을 기다린다
  const done = page.getByRole("button", { name: "완료", exact: true });
  for (let i = 0; i < 25 && !(await done.isVisible()); i++) await page.getByRole("button", { name: "다음", exact: true }).click();
  await done.click();
  await expect(page.getByText("자유 답에서 이렇게 읽었어요")).toBeVisible();
  await expect(page.getByText("남보다 늦을까 조급함")).toBeVisible();
  await page.getByRole("button", { name: "손실 걱정 지우기" }).click();
  await expect(page.getByText("손실 걱정")).toHaveCount(0);
  await page.getByRole("button", { name: "다음", exact: true }).click();
  await expect(page.getByRole("heading", { name: "지금 가진 주식이 있나요?" })).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.ips-profile.v1") ?? "{}"));
  expect(saved.free_text_signal.extracted_signals).toEqual({ fomo_index: 0.8 });

  // 내 투자 성향에서도 글자 버튼으로 바로 지운다(상자 없이 글자)
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await page.goto("/profile");
  await page.getByRole("button", { name: "남보다 늦을까 조급함 지우기" }).click();
  await expect(page.getByText("자유 답에서 이렇게 읽었어요")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem("takealook.ips-profile.v1") ?? "{}").free_text_signal.extracted_signals)).toEqual({});
});
