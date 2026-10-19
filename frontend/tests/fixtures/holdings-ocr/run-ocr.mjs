// 시험 화면을 실제 인식 모듈(lib/holdings-ocr/recognize.ts)로 읽어 ocr/<화면>.json에 저장한다.
// 단위 테스트는 이 고정값을 쓰므로 CI는 모델을 받지 않는다. 모델이나 전처리를 바꾸면 다시 돌린다.
// 사용: pnpm dev --port 3100 을 띄운 뒤 node tests/fixtures/holdings-ocr/run-ocr.mjs [--mobile]
//   --mobile: 휴대폰 에뮬레이션(390폭, CPU 4배 느리게)으로 한 장 처리 시간만 잰다
import { chromium, devices } from "@playwright/test";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";

const BASE = process.env.BASE ?? "http://localhost:3100";
const DIR = new URL(".", import.meta.url);
const mobile = process.argv.includes("--mobile");
const files = readdirSync(DIR).filter((name) => name.endsWith(".png")).sort();

const browser = await chromium.launch();
const context = await browser.newContext(mobile ? devices["Pixel 7"] : {});
const page = await context.newPage();
// 앱의 로그인 확인을 지나가도록 데모 세션과 성향을 넣는다(e2e performance.spec과 같은 방식)
const profile = JSON.parse(readFileSync(new URL("../../../../schema/profiling_output.v1_1.example.json", import.meta.url), "utf8"));
await page.addInitScript((value) => {
  localStorage.setItem("takealook.demo-session.v1", JSON.stringify({ userId: "demo-ocr", displayName: "테스트", signedInAt: new Date().toISOString() }));
  localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(value));
}, profile);
page.on("console", (message) => message.type() === "error" && console.error("console:", message.text().slice(0, 300)));
await page.route("**/ocr-fixture/*", (route) =>
  route.fulfill({ contentType: "image/png", body: readFileSync(new URL(route.request().url().split("/").pop(), DIR)) }));
await page.goto(`${BASE}/dev-ocr`);
await page.waitForFunction(() => typeof window.ocrFile === "function");
if (mobile) {
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
}
mkdirSync(new URL("ocr/", DIR), { recursive: true });
// 첫 장은 모델 받기와 초기화가 섞이므로 따로 잰다
const warm = Date.now();
await page.evaluate((name) => window.ocrFile(`/ocr-fixture/${name}`), files[0]);
console.log(`first call (model download + init + 1 image): ${Date.now() - warm}ms`);
for (const name of mobile ? files.filter((f) => f.includes("-390")) : files) {
  const { lines, ms } = await page.evaluate((file) => window.ocrFile(`/ocr-fixture/${file}`), name);
  console.log(`${name}\t${ms}ms\t${lines.length} lines`);
  if (!mobile) writeFileSync(new URL(`ocr/${name.replace(".png", ".json")}`, DIR), `${JSON.stringify(lines.map((line) => ({ ...line, score: Number(line.score.toFixed(3)), x0: Math.round(line.x0), y0: Math.round(line.y0), x1: Math.round(line.x1), y1: Math.round(line.y1) })), null, 1)}\n`);
}
await browser.close();
