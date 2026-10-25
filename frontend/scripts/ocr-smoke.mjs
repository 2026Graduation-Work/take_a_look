// 캡처 불러오기 스모크: 실제 글자 읽기 엔진으로 세 경로 × 합성 캡처 A, B를 읽어 본다(#393).
//   a: /portfolio 주소를 직접 연다   b: 대시보드 → 계정 메뉴 → 보유 종목(화면 이동)   c: 설문 흐름의 보유 단계
// 화면 CSP는 처음 연 문서 것이 화면 이동 내내 쓰여서 b, c가 a와 다르게 막힐 수 있다. 그래서 경로를 나눠 본다.
// 엔진과 모델(약 55MB)을 받고 읽는 데 경로마다 수십 초 걸려 CI e2e에는 넣지 않고(CI는 가짜 워커로 같은 이동을 본다),
// 배포 뒤에 손으로 돌린다. 사용: node scripts/ocr-smoke.mjs [기준 주소, 기본 운영]
import { chromium } from "@playwright/test";

const BASE = process.argv[2] ?? "https://takealook-skku.vercel.app";
const IMAGES = { A: "tests/fixtures/holdings-ocr/A-light-1280.png", B: "tests/fixtures/holdings-ocr/B-dark-390.png" };

async function toHoldingsStep(page) {
  await page.goto(`${BASE}/`);
  await page.getByRole("button", { name: "데모로 둘러보기" }).click();
  await page.getByRole("button", { name: "시작하기" }).click();
  await page.getByRole("button", { name: /데모 응답/ }).first().click();
  for (let i = 0; i < 40; i++) {
    if (await page.getByRole("heading", { name: "지금 가진 주식이 있나요?" }).isVisible()) return;
    const done = page.getByRole("button", { name: "완료", exact: true });
    // 제출 중에는 버튼이 같은 이름으로 눌린 채 남는다. 짧게 눌러 보고 화면이 바뀌면 다음 차례에 다시 본다
    await (await done.isVisible() ? done : page.getByRole("button", { name: "다음", exact: true })).click({ timeout: 2_000 }).catch(() => {});
  }
}

async function toDashboard(page) {
  await toHoldingsStep(page);
  await page.getByRole("button", { name: "저장하고 시작" }).click();
  await page.waitForURL(/\/$/);
}

const PATHS = {
  a: async (page) => { await toDashboard(page); await page.goto(`${BASE}/portfolio`); },
  b: async (page) => { await toDashboard(page); await page.getByLabel(/계정 메뉴/).click(); await page.getByRole("link", { name: "보유 종목" }).click(); await page.waitForURL(/\/portfolio$/); },
  c: toHoldingsStep,
};

const browser = await chromium.launch();
let failed = 0;
for (const [path, open] of Object.entries(PATHS)) {
  for (const [name, image] of Object.entries(IMAGES)) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const blocked = [];
    page.on("requestfailed", (request) => blocked.push(`${request.url().slice(0, 90)} ${request.failure()?.errorText}`));
    const started = Date.now();
    await open(page);
    await page.getByLabel("보유 종목 화면 캡처 파일").setInputFiles(image);
    const result = await Promise.race([
      page.getByRole("heading", { name: "읽은 내용을 확인해 주세요" }).waitFor({ timeout: 240_000 }).then(() => "review"),
      page.getByRole("alert").filter({ hasText: /못했어요|다루지 않아요/ }).waitFor({ timeout: 240_000 }).then(() => page.getByRole("alert").filter({ hasText: /못했어요|다루지 않아요/ }).innerText()),
    ]).catch((error) => `timeout ${error.message.slice(0, 60)}`);
    const rows = result === "review" ? await page.getByRole("list", { name: "읽은 보유 종목" }).getByRole("listitem").count() : 0;
    if (result !== "review") failed++;
    console.log(`${path} ${name}: ${result === "review" ? `성공 ${rows}종목` : `실패 ${result}`} (${Math.round((Date.now() - started) / 1000)}초)${blocked.length ? `\n  ${blocked.join("\n  ")}` : ""}`);
    await page.close();
  }
}
await browser.close();
process.exit(failed ? 1 : 0);
