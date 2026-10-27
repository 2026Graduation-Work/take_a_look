import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

// 스크린샷으로 보유 종목 불러오기: 업로드 → 확인 표 → 수정 → 목록에 넣기 → 저장.
// CI에서 모델(약 24MB)을 돌리지 않도록, 글자 인식 워커(/ocr/v1/worker-entry)만 시험 화면의 인식 고정값(tests/fixtures/holdings-ocr/ocr)을
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
  await context.route(/\/ocr\/v1\/worker-entry/, (route) => route.fulfill({ contentType: "text/javascript", body: fakeWorker }));
  await page.route(/\/rest\/v1\/stocks\?select=code%2Cname/, (route) => route.fulfill({ json: MASTER }));
  await finishDemo(page);
  await page.goto("/portfolio");

  await expect(page.getByText("캡처는 이 기기 안에서만 읽고 어디에도 보내지 않아요.", { exact: false })).toBeVisible();
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("heading", { name: "읽은 내용을 확인해 주세요" })).toBeVisible();
  const review = page.getByRole("list", { name: "읽은 보유 종목" });
  await expect(review.getByRole("listitem")).toHaveCount(5);
  await expect(review.getByLabel("두산에너빌리티 수량")).toHaveValue("120");
  await expect(review.getByLabel("두산에너빌리티 평균 매입가")).toHaveValue("19,870");
  await expect(review.getByText("계산한 값").first()).toBeVisible();
  await expect(page.getByText(/다루지 않는 종목\(ETF, 해외 주식 등\): .*KODEX 200/)).toBeVisible();
  // 저장 전에는 아무것도 저장하지 않는다
  const before = await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"));

  await review.getByLabel("현대차 수량").fill("-1");
  await expect(review.getByLabel("현대차 수량")).toHaveValue("-1");
  await page.getByRole("button", { name: "목록에 넣기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "현대차의 수량은" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  await review.getByLabel("현대차 수량").fill("9");
  await review.getByLabel("두산에너빌리티 평균 매입가").fill("-100");
  await expect(review.getByLabel("두산에너빌리티 평균 매입가")).toHaveValue("-100");
  await page.getByRole("button", { name: "목록에 넣기" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "두산에너빌리티의 평균 매입가는" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  await review.getByLabel("두산에너빌리티 평균 매입가").fill("19870");
  await page.getByRole("button", { name: "목록에 넣기" }).click();
  await expect(page.getByRole("status").filter({ hasText: "5종목을 목록에 넣었어요" })).toContainText("새 값으로 바꿨어요");
  expect(await page.evaluate(() => localStorage.getItem("takealook.holdings.v1"))).toBe(before);
  await expect(page.getByLabel("현대차 수량", { exact: true })).toHaveValue("9");
  await expect(page.getByLabel("두산에너빌리티 평균 매입가", { exact: true })).toHaveValue("19,870");

  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "저장했어요" })).toBeVisible();
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem("takealook.holdings.v1")!));
  expect(saved.find((row: { code: string }) => row.code === "034020")).toEqual({ code: "034020", name: "두산에너빌리티", quantity: 120, avgBuyPrice: 19870 });
  expect(saved.find((row: { code: string }) => row.code === "005380").quantity).toBe(9);
});

// 화면 CSP는 처음 연 문서 것이 화면 이동 내내 쓰인다. 대시보드에서 메뉴로 들어와도 워커가 막히지 않아야 한다(#393)
test("스크린샷: 대시보드 → 계정 메뉴 → 보유 종목으로 이동해도 읽는다", async ({ page, context }) => {
  await context.route(/\/ocr\/v1\/worker-entry/, (route) => route.fulfill({ contentType: "text/javascript", body: fakeWorker }));
  await page.route(/\/rest\/v1\/stocks\?select=code%2Cname/, (route) => route.fulfill({ json: MASTER }));
  await finishDemo(page);
  await page.getByLabel(/계정 메뉴/).click();
  await page.getByRole("link", { name: "보유 종목", exact: true }).click();
  await expect(page).toHaveURL(/\/portfolio$/);
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("heading", { name: "읽은 내용을 확인해 주세요" })).toBeVisible();
});

test("스크린샷: 읽는 도구를 못 받으면 새로고침을 안내한다", async ({ page, context }) => {
  await context.route(/\/ocr\/v1\/worker-entry/, (route) => route.abort());
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("alert").filter({ hasText: "읽는 도구" })).toHaveText("읽는 도구를 불러오지 못했어요. 새로고침한 뒤 다시 올리거나 직접 입력해 주세요.");
});

test("스크린샷: 글자를 거의 못 읽으면 또렷한 캡처를, 글자는 읽었는데 종목이 없으면 다른 화면을 안내한다", async ({ page, context }) => {
  let items = "[]";
  await context.route(/\/ocr\/v1\/worker-entry/, (route) =>
    route.fulfill({ contentType: "text/javascript", body: fakeWorker.replace(/const items = .*;\n/, `const items = ${items};\n`) }));
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("alert").filter({ hasText: "글자를" })).toHaveText("글자를 거의 읽지 못했어요. 글자가 또렷하게 보이는 캡처로 다시 올리거나 직접 입력해 주세요.");

  items = JSON.stringify(["계좌 요약", "총 평가금액", "주문 가능 금액", "입출금"].map((text, i) => ({ text, score: 0.99, poly: [[0, i * 40], [200, i * 40], [200, i * 40 + 30], [0, i * 40 + 30]] })));
  await page.reload(); // 워커를 새로 받게
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("alert").filter({ hasText: "종목을 찾지 못했어요" })).toHaveText("종목을 찾지 못했어요. 보유 종목이 보이는 화면을 다시 올리거나 직접 입력해 주세요.");
});

test("스크린샷: ETF만 읽히면 다루지 않는 종목이라고 이름과 함께 알리고, 읽은 글자를 접어서 보여 준다", async ({ page, context }) => {
  const etfLines: typeof lines = JSON.parse(readFileSync(`${FIXTURE}/ocr/P-A-etf-393.json`, "utf8"));
  const items = JSON.stringify(etfLines.map(({ text, score, x0, y0, x1, y1 }) => ({ text, score, poly: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] })));
  await context.route(/\/ocr\/v1\/worker-entry/, (route) =>
    route.fulfill({ contentType: "text/javascript", body: fakeWorker.replace(/const items = .*;\n/, `const items = ${items};\n`) }));
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/P-A-etf-393.png`);
  const alert = page.getByRole("alert").filter({ hasText: "아직 다루지 않아요" });
  await expect(alert).toContainText("읽은 5개 종목은 ETF나 해외 주식이라 Take a Look이 아직 다루지 않아요.");
  await expect(alert).toContainText("KODEX 은행");
  const raw = page.locator("details", { hasText: "읽은 글자 보기" });
  await expect(raw).not.toHaveAttribute("open", "");
  await raw.locator("summary").click();
  await expect(raw.getByText("SOL 조선TO", { exact: true })).toBeVisible(); // 표형은 긴 이름이 두 줄로 나뉘어 읽힌다
});

// 기다림 표시: 처음엔 1/3(받은 바이트 % 막대), 두 번째부터는 읽는 도구를 다시 받지 않고 1단계를 건너뛴다
test("스크린샷: 처음 불러오기는 1/3 준비 막대를 보이고, 두 번째 불러오기는 1단계를 건너뛴다", async ({ page, context }) => {
  // 받기를 1.5초 늦춰 300ms 안에 끝나지 않게 한다(300ms 안이면 표시하지 않는다)
  await context.route(/\/ocr\/v1\/worker-entry/, async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await route.fulfill({ contentType: "text/javascript", body: fakeWorker });
  });
  await page.route(/\/rest\/v1\/stocks\?select=code%2Cname/, (route) => route.fulfill({ json: MASTER }));
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(page.getByRole("status").filter({ hasText: /^1\/3 읽는 도구 준비\(처음 한 번, 약 55MB\)/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "읽은 내용을 확인해 주세요" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("takealook.ocr-assets.v1"))).not.toBeNull();

  // 새 탭(같은 브라우저): 1단계 글자가 한 번도 나오지 않는다
  const second = await context.newPage();
  await second.route(/\/rest\/v1\/stocks\?select=code%2Cname/, (route) => route.fulfill({ json: MASTER }));
  await second.goto("/portfolio");
  await second.evaluate(() => {
    (window as unknown as { seen: string[] }).seen = [];
    new MutationObserver(() => (window as unknown as { seen: string[] }).seen.push(document.body.innerText)).observe(document.body, { subtree: true, childList: true, characterData: true });
  });
  await second.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await expect(second.getByRole("heading", { name: "읽은 내용을 확인해 주세요" })).toBeVisible();
  const seen = await second.evaluate(() => (window as unknown as { seen: string[] }).seen.join("\n"));
  expect(seen).not.toContain("1/3 읽는 도구 준비");
});

test("스크린샷: 10초가 넘으면 '조금 더 걸리고 있어요'와 취소, 취소하면 직접 입력을 그대로 쓴다", async ({ page, context }) => {
  // 글자 찾기 요청에 답하지 않는 워커
  const stuck = fakeWorker.replace('const payload = data.type === "predict"', 'if (data.type === "predict") return;\n  const payload = data.type === "predict"');
  await context.route(/\/ocr\/v1\/worker-entry/, (route) => route.fulfill({ contentType: "text/javascript", body: stuck }));
  await page.clock.install();
  await finishDemo(page);
  await page.goto("/portfolio");
  await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(`${FIXTURE}/B-dark-390.png`);
  await page.clock.fastForward(1000);
  await expect(page.getByRole("status").filter({ hasText: "2/3 사진에서 글자 찾기" })).toBeVisible();
  await expect(page.getByText("조금 더 걸리고 있어요.")).toHaveCount(0);
  await page.clock.fastForward(10_000);
  await expect(page.getByText("조금 더 걸리고 있어요.")).toBeVisible();
  await page.getByRole("button", { name: "취소", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "불러오기를 취소했어요" })).toBeVisible();
  await expect(page.getByRole("button", { name: "캡처로 불러오기" })).toBeEnabled();
  await expect(page.getByLabel("종목 검색")).toBeEditable();
});
