// usage: node demo-shots.mjs <baseUrl> <prefix> <outDir> [paths...]
import { chromium } from "@playwright/test";
const [base, prefix, out, ...paths] = process.argv.slice(2);
const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
const p = await ctx.newPage();
p.on("dialog", (d) => void d.accept());
const sizes = [];
p.on("response", async (r) => {
  if (r.url().includes("latest_chart_signal_snapshots") || r.url().includes("/rest/v1/")) {
    try { const body = await r.body(); sizes.push([r.url().split("/rest/v1/")[1]?.slice(0, 90), body.length, r.headers()["content-encoding"] || ""]); } catch {}
  }
});
await p.goto(base + "/login", { waitUntil: "networkidle", timeout: 180000 });
await p.getByRole("button", { name: "데모로 둘러보기" }).click();
await p.getByRole("button", { name: "시작하기" }).click();
for (let n = 1; n <= 16; n++) { await p.getByText(`질문 ${n}/16`).waitFor(); await p.locator("fieldset input").first().check(); }
await p.getByLabel("6개월~2년").check();
await p.getByText("마무리 2/3").waitFor();
await p.getByLabel("SPAC", { exact: false }).check();
await p.getByRole("button", { name: "다음", exact: true }).click();
await p.getByRole("button", { name: "완료" }).click();
await p.getByRole("button", { name: "다음", exact: true }).click();
await p.getByRole("button", { name: "저장하고 시작" }).click();
await p.waitForURL(base + "/");
for (const path of paths.length ? paths : ["/"]) {
  for (const width of [390, 1280]) {
    await p.setViewportSize({ width, height: width === 390 ? 844 : 900 });
    sizes.length = 0;
    await p.goto(base + path, { waitUntil: "networkidle", timeout: 180000 });
    await p.waitForTimeout(2500);
    const name = `${prefix}-${path === "/" ? "dashboard" : path.replace(/\//g, "_").replace(/^_/, "")}-${width}.png`;
    await p.screenshot({ path: `${out}/${name}`, fullPage: true });
    const overflow = await p.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    let cover = "";
    if (width === 390) {
      await p.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await p.waitForTimeout(600);
      await p.screenshot({ path: `${out}/${name.replace(".png", "-bottom.png")}` });
      cover = await p.evaluate(() => {
        const bar = document.querySelector(".tab-bar")?.getBoundingClientRect();
        const foot = [...document.querySelectorAll("footer, [role=contentinfo]")].at(-1)?.getBoundingClientRect();
        const clipped = [...document.querySelectorAll("body *")].filter((el) => el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX === "visible").length;
        return bar && foot ? `tabTop=${Math.round(bar.top)} footBottom=${Math.round(foot.bottom)} covered=${foot.bottom > bar.top} clipped=${clipped}` : `no bar/footer clipped=${clipped}`;
      });
    }
    let colAlign = "";
    if (width === 1280 && path === "/") colAlign = await p.evaluate(() => {
      const heads = [...document.querySelectorAll("h2")].filter((h) => ["내 보유 종목의 오늘 신호", "오늘 신호가 강한 종목"].includes(h.textContent?.trim() ?? ""));
      const rows = heads.map((h) => { const head = h.parentElement.getBoundingClientRect(); const card = h.parentElement.nextElementSibling?.getBoundingClientRect(); return [Math.round(head.top), Math.round(head.height), Math.round(card?.top ?? -1)]; });
      return JSON.stringify(rows);
    });
    console.log(name, "overflowX", overflow, cover, colAlign);
    if (width === 1280 && path === "/") for (const [u, n, enc] of sizes) console.log("  req", n, enc, u);
  }
}
await b.close();
