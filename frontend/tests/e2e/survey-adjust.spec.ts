import { expect, test } from "@playwright/test";

// 설문 → 결과 → 5칸 조정 → 유형이 바뀜 → 추가 질문만 이어서 답하기
test("결과 화면: 5칸을 눌러 조정하고, 추가 질문은 남은 문항만 묻는다", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  await page.getByRole("button", { name: "완료", exact: true }).click();

  const type = page.locator("h1[data-bit-type]");
  await expect(type).toBeVisible();
  const before = await type.getAttribute("data-bit-type");
  // 0~100 점수와 드래그 막대는 없다
  await expect(page.locator('input[type="range"]')).toHaveCount(0);
  await expect(page.locator("section.surface")).not.toContainText(/100/);

  await page.getByRole("button", { name: "직접 조정하기" }).click();
  const adjust = page.locator("#style-axes-adjust");
  await expect(adjust.getByRole("radiogroup")).toHaveCount(8);
  // 보유 기간 '짧게' 끝 칸, 손실 감수 '손실 감수' 끝 칸, 모아 담기 '모아 담음' 끝 칸 → 적극 축적형
  await adjust.getByRole("radiogroup", { name: /^보유 기간/ }).getByRole("radio").nth(0).click();
  await adjust.getByRole("radiogroup", { name: /^손실 감수/ }).getByRole("radio").nth(4).click();
  // 키보드: 모아 담기는 방향키로 끝 칸까지
  const concentration = adjust.getByRole("radiogroup", { name: /^모아 담기/ });
  await concentration.getByRole("radio", { checked: true }).focus();
  for (let i = 0; i < 4; i += 1) await page.keyboard.press("ArrowRight");
  await expect(concentration.getByRole("radio").nth(4)).toHaveAttribute("aria-checked", "true");
  await expect(concentration.getByRole("radio").nth(4)).toBeFocused();
  await expect(type).toHaveAttribute("data-bit-type", "ACCUMULATOR");
  expect(before).not.toBe("ACCUMULATOR");
  await expect(page.getByText("단기 매매 쪽이 강해요").first()).toBeVisible();

  await adjust.getByRole("button", { name: "초기화" }).click();
  await expect(type).toHaveAttribute("data-bit-type", before!);
  await adjust.getByRole("button", { name: "접기" }).click();
  await expect(adjust).toHaveCount(0);

  // 추가 질문: 16문항 답은 그대로, 남은 8문항만
  await page.getByRole("button", { name: "추가 질문 8개" }).click();
  for (let number = 1; number <= 8; number += 1) {
    await expect(page.getByText(`추가 질문 ${number}/8`)).toBeVisible();
    await expect(page.locator("fieldset input:checked")).toHaveCount(0);
    await page.locator("fieldset label").nth(2).click();
    await page.getByRole("button", { name: number === 8 ? "완료" : "다음", exact: true }).click();
  }
  await expect(type).toBeVisible();
  await expect(page.getByRole("button", { name: /추가 질문/ })).toHaveCount(0);
  const answered = await page.evaluate(() => Object.keys(JSON.parse(localStorage.getItem("takealook.survey-draft.v1") ?? "{}").style ?? {}).length);
  expect(answered).toBe(24);
});
