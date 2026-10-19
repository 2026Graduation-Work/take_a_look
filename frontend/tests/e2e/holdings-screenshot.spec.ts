import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 스크린샷으로 보유 종목 불러오기: 업로드 → 확인 표 → 수정 → 목록에 넣기 → 저장.
// CI에서 모델(약 24MB)을 받지 않도록, 글자 인식 워커만 시험 화면의 인식 고정값(tests/fixtures/holdings-ocr/ocr)을
// 돌려주는 가짜 워커로 바꾼다. 해석 규칙과 화면은 실제 코드 그대로다.
const FIXTURE = "tests/fixtures/holdings-ocr";
const lines: { text: string; score: number; x0: number; y0: number; x1: number; y1: number }[] =
  JSON.parse(readFileSync(`${FIXTURE}/ocr/B-dark-390.json`, "utf8"));
const answers = JSON.parse(readFileSync(`${FIXTURE}/answers.json`, "utf8"));
const MASTER = [...new Map(Object.values<{ holdings: { code: string; name: string }[] }>(answers)
  .flatMap(({ holdings }) => holdings.map(({ code, name }) => [code, { code, name }]))).values()];

const fakeWorker = `
const items = ${JSON.stringify(lines.map(({ text, score, x0, y0, x1, y1 }) => ({ text, score, poly: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] })))};
self.onmessage = ({ data }) => {
  const payload = data.type === "predict" ? [{ items }] : { summary: {}, modelConfig: {} };
  self.postMessage({ kind: "worker-transport-response", status: "success", requestId: data.requestId, payload });
};`;

test("스크린샷: 읽은 값을 확인하고 고친 뒤 목록에 넣고 저장한다", async ({ page, context }) => {
  await context.route(/cdn\.jsdelivr\.net\/npm\/@paddleocr/, (route) => route.fulfill({ contentType: "text/javascript", body: fakeWorker }));
  await page.route(/\/rest\/v1\/stocks\?select=code%2Cname/, (route) => route.fulfill({ json: MASTER }));
  await finishDemo(page);
  await page.goto("/portfolio");

  await expect(page.getByText("사진은 이 기기 안에서만 읽고 어디에도 보내지 않아요.")).toBeVisible();
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("heading", { name: "읽은 내용을 확인해 주세요" })).toBeVisible();
  const review = page.getByRole("list", { name: "읽은 보유 종목" });
  await expect(review.getByRole("listitem")).toHaveCount(5);
  await expect(review.getByLabel("두산에너빌리티 수량")).toHaveValue("120");
  await expect(review.getByLabel("두산에너빌리티 평균 매입가")).toHaveValue("19870");
  await expect(review.getByText("계산한 값").first()).toBeVisible();
  await expect(page.getByText(/다루지 않는 종목\(ETF, 해외 주식 등\): .*KODEX 200/)).toBeVisible();
  // 저장 전에는 아무것도 저장하지 않는다
  const before = await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"));

  await review.getByLabel("현대차 수량").fill("9");
  await page.getByRole("button", { name: "목록에 넣기" }).click();
  await expect(page.getByRole("status").filter({ hasText: "5종목을 목록에 넣었어요" })).toContainText("새 값으로 바꿨어요");
  expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  await expect(page.getByLabel("현대차 수량", { exact: true })).toHaveValue("9");
  await expect(page.getByLabel("두산에너빌리티 평균 매입가", { exact: true })).toHaveValue("19870");

  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.holdings.v1")!));
  expect(saved.find((row: { code: string }) => row.code === "034020")).toEqual({ code: "034020", name: "두산에너빌리티", quantity: 120, avgBuyPrice: 19870 });
  expect(saved.find((row: { code: string }) => row.code === "005380").quantity).toBe(9);
});

test("스크린샷: 종목을 못 찾으면 다시 올리거나 직접 입력하라고 안내한다", async ({ page, context }) => {
  await context.route(/cdn\.jsdelivr\.net\/npm\/@paddleocr/, (route) =>
    route.fulfill({ contentType: "text/javascript", body: fakeWorker.replace(/const items = .*;\n/, "const items = [];\n") }));
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("alert").filter({ hasText: "종목을 찾지 못했어요" })).toHaveText("종목을 찾지 못했어요. 보유 종목이 보이는 화면을 다시 올리거나 직접 입력해 주세요.");
});
