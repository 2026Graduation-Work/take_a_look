import { chromium } from "@playwright/test";
const [base, out] = process.argv.slice(2);
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 390, height: 844 } })).newPage();
p.on("dialog", (d) => void d.accept());
await p.goto(base + "/login", { waitUntil: "networkidle", timeout: 180000 });
await p.getByRole("button", { name: "데모로 둘러보기" }).click();
await p.getByRole("button", { name: "시작하기" }).click();
await p.getByRole("button", { name: "데모 응답" }).click();
await p.waitForTimeout(1500);
await p.screenshot({ path: `${out}/step-demo.png` });
for (const name of ["다음", "완료", "다음", "저장하고 시작"]) {
  const btn = p.getByRole("button", { name, exact: true });
  if (await btn.count()) { await btn.first().click({ timeout: 15000 }).catch(async (e) => { await p.screenshot({ path: `${out}/fail-${name}.png` }); console.log("click fail", name, e.message.split("\n")[0]); }); await p.waitForTimeout(1500); }
}
await p.waitForURL(base + "/", { timeout: 20000 });
const saved = await p.evaluate(() => localStorage.getItem("takealook.holdings.v1"));
console.log("saved holdings:", saved);
await p.goto(base + "/stocks/005380", { waitUntil: "networkidle", timeout: 180000 });
await p.waitForTimeout(2000);
const price = Number((await p.locator("span.text-4xl").first().textContent()).replace(/[^0-9]/g, ""));
const avg = Math.round(price / 1.14 / 100) * 100;
console.log("price", price, "avg", avg);
// 보유 화면에서 평단을 넣은 것과 같은 상태: 현대차 평단 = 현재가 / 1.14(약 +14%)
await p.evaluate((avg) => {
  const rows = JSON.parse(localStorage.getItem("takealook.holdings.v1") || "[]").filter((r) => r.code !== "005380");
  rows.push({ code: "005380", name: "현대차", quantity: 5, avgBuyPrice: avg });
  localStorage.setItem("takealook.holdings.v1", JSON.stringify(rows));
}, avg);
await p.goto(base + "/stocks/005380", { waitUntil: "networkidle", timeout: 180000 });
await p.waitForTimeout(2500);
const cp = p.getByText("평균 매입가보다", { exact: false });
console.log("N05 count:", await cp.count(), (await cp.count()) ? await cp.first().textContent() : "");
const head = p.locator("section").filter({ hasText: "체크포인트" }).first();
await p.screenshot({ path: `${out}/n05-390-full.png`, fullPage: true });
if (await cp.count()) { await cp.first().scrollIntoViewIfNeeded(); await p.evaluate(() => window.scrollBy(0, -300)); await p.waitForTimeout(300); await p.screenshot({ path: `${out}/n05-390.png` }); }
console.log("overflowX", await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth));
await b.close();
