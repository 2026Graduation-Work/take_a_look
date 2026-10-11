import { chromium } from "@playwright/test";
const [base, out] = process.argv.slice(2);
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
p.on("dialog", (d) => void d.accept());
await p.goto(base + "/login", { waitUntil: "networkidle", timeout: 180000 });
await p.getByRole("button", { name: "데모로 둘러보기" }).click();
await p.getByRole("button", { name: "시작하기" }).click();
await p.getByRole("button", { name: "데모 응답" }).click();
await p.waitForTimeout(800);
await p.getByRole("button", { name: "완료" }).click();
await p.waitForTimeout(1500);
for (const w of [390, 1280]) { await p.setViewportSize({ width: w, height: 900 }); await p.waitForTimeout(500); await p.screenshot({ path: `${out}/qa-profile-${w}.png` }); }

for (const name of ["다음", "저장하고 시작"]) { const x = p.getByRole("button", { name, exact: true }); if (await x.count()) { await x.first().click(); await p.waitForTimeout(800); } }
for (const path of ["/", "/stocks/005930"]) for (const w of [390, 1280]) {
  await p.setViewportSize({ width: w, height: 900 });
  await p.goto(base + path, { waitUntil: "networkidle", timeout: 180000 }); await p.waitForTimeout(1500);
  if (path !== "/") { const t = p.getByRole("tab", { name: "누가 사고팔았나" }); if (await t.count()) await t.click(); await p.waitForTimeout(500); }
  await p.screenshot({ path: `${out}/qa-${path === "/" ? "dashboard" : "detail"}-${w}.png`, fullPage: true });
  console.log(path, w, "overflowX", await p.evaluate(() => document.documentElement.scrollWidth - innerWidth));
}
await b.close();
