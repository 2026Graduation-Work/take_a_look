import { expect, test } from "@playwright/test";
import { finishDemo } from "./demo-steps";

test("종목 상세는 주가, 개인화 안내, 분야별 근거를 이어서 읽을 수 있다", async ({ page }) => {
  await finishDemo(page);
  await page.evaluate(() => {
    const profile = JSON.parse(localStorage.getItem("takealook.ips-profile.v1")!);
    for (const axis of profile.style_axes.axes) axis.ratio = axis.axis_id === "turnover" ? 0.5 : 0;
    localStorage.setItem("takealook.ips-profile.v1", JSON.stringify(profile));
  });
  await page.goto("/stocks/000660");
  const tabs = page.getByRole("tablist", { name: "종목 상세" }).getByRole("tab");
  await expect(tabs).toHaveText(["한눈에 보기", "모델 예측", "거래 동향", "회사 상태", "뉴스"]);
  const overview = page.getByRole("tabpanel", { name: "한눈에 보기" });
  await expect(overview.getByRole("button", { name: /^회사 상태/ })).toContainText("104.8%");
  const price = overview.getByRole("region", { name: "최근 주가" });
  const checkpoint = overview.locator('section[aria-labelledby="checkpoint-title"]');
  await expect(price.getByRole("img", { name: "최근 주가 흐름" })).toBeVisible();
  await expect(checkpoint.getByText("설문에서 보유 기간이 짧은 쪽으로 답해 표시했어요.")).toBeVisible();
  await expect(page.getByText("설문 8가지 답", { exact: true })).toHaveCount(0);
  await expect(page.getByText("더 알아보기", { exact: true })).toHaveCount(0);

  const header = page.getByRole("region", { name: "SK하이닉스", exact: true });
  const name = header.getByRole("heading", { level: 1 });
  const quote = header.getByText("275,000원", { exact: true });
  const change = header.getByText("전일 대비 상승 ▲ 15,000원 (5.8%)", { exact: true });
  await expect(change).toBeVisible();
  for (const width of [1280, 1024, 1023, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const [nameBox, quoteBox, changeBox] = await Promise.all([name.boundingBox(), quote.boundingBox(), change.boundingBox()]);
    expect(quoteBox!.x).toBe(nameBox!.x);
    expect(quoteBox!.y).toBeGreaterThanOrEqual(nameBox!.y + nameBox!.height);
    if (width >= 1024) expect(changeBox!.x).toBeGreaterThan(quoteBox!.x + quoteBox!.width);
    const [chart, guide] = await Promise.all([price.boundingBox(), checkpoint.boundingBox()]);
    if (width >= 1024) {
      expect(chart!.y).toBe(guide!.y);
      expect(chart!.x + chart!.width).toBeLessThan(guide!.x);
    } else {
      expect(chart!.y + chart!.height).toBeLessThan(guide!.y);
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }

  await overview.getByRole("button", { name: /^거래 동향/ }).click();
  await expect(tabs.getByText("거래 동향", { exact: true })).toBeFocused();
  const trading = page.getByRole("tabpanel", { name: "거래 동향" });
  await expect(trading.getByRole("heading", { name: "얼마나 거래됐나" })).toBeVisible();
  await expect(trading.getByRole("heading", { name: "누가 사고팔았나" })).toBeVisible();

  await page.keyboard.press("ArrowRight");
  const company = page.getByRole("tabpanel", { name: "회사 상태" });
  await expect(company.getByRole("heading", { name: "매출과 이익" })).toBeVisible();
  await expect(company.getByRole("heading", { name: "자산과 빚" })).toBeVisible();
  await expect(company.getByRole("heading", { name: "주가와 비교" })).toBeVisible();
  await expect(company.getByText("104.8%", { exact: true }).last()).toBeVisible();
  await expect(company.getByText("2026.09.21 종가 기준", { exact: true })).toBeVisible();
  await expect(company.getByRole("heading", { name: "회사 발표" })).toBeVisible();
  await expect(company.getByRole("link", { name: "가상 공시 테스트" })).toHaveAttribute("href", /dart\.fss\.or\.kr/);
  await page.keyboard.press("End");
  const news = page.getByRole("tabpanel", { name: "뉴스" });
  await expect(news).toBeVisible();
  await expect(news.getByText("가상 공시 테스트")).toHaveCount(0);
  await page.keyboard.press("Home");

  await overview.getByRole("button", { name: /^모델 예측/ }).click();
  const model = page.getByRole("tabpanel", { name: "모델 예측" });
  const mood = model.getByRole("region", { name: "가격 흐름 분위기" });
  await expect(mood.getByRole("img")).toBeVisible();
  await mood.locator("summary").click();
  await expect(mood.getByText(/가격 흐름 분위기 점수/)).toBeVisible();
});

test("모델 신호가 없는 종목에서도 회사 발표와 뉴스에 접근할 수 있다", async ({ page }) => {
  await page.route("**/rest/v1/latest_chart_signal_snapshots?**", route => route.fulfill({ json: [] }));
  await page.goto("/stocks/035420");
  await expect(page.getByRole("heading", { name: "NAVER", exact: true })).toBeVisible();
  const tabs = page.getByRole("tablist", { name: "종목 상세" });
  await expect(tabs.getByRole("tab", { selected: true })).toHaveText("한눈에 보기");
  await tabs.getByRole("tab", { name: "모델 예측" }).click();
  await expect(page.getByRole("heading", { name: "모델 신호 미제공" })).toBeVisible();
  await tabs.getByRole("tab", { name: "회사 상태" }).click();
  await expect(page.getByRole("heading", { name: "회사 발표" })).toBeVisible();
  await tabs.getByRole("tab", { name: "뉴스" }).click();
  await expect(page.getByRole("heading", { name: "회사 발표" })).toHaveCount(0);
});
