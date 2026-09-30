import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const snapshots = JSON.parse(readFileSync("../backend/analysis/chart/serving/previews/2026-09-21/snapshots.json", "utf8"));
const rows = snapshots.map((payload: { batch_id: string; stock_code: string; horizon: number }) => ({
  batch_id: payload.batch_id, stock_code: payload.stock_code, horizon: payload.horizon, payload,
}));

test("public preview uses the pinned batch and switches both horizons", async ({ page }) => {
  await page.route("**/rest/v1/chart_signal_snapshots?**", route => {
    expect(new URL(route.request().url()).searchParams.get("batch_id")).toBe(`eq.${rows[0].batch_id}`);
    return route.fulfill({ json: rows });
  });
  await page.goto("/stocks/005930");
  await expect(page.getByTestId("preview-provenance")).toHaveText(/연결 확인용 · 모델 검증 전 · 2026-09-21 기준/);
  await expect(page.getByRole("tab", { name: "4주 · 20거래일" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("heading", { name: "4주 · 20거래일 후 과거 수익률" })).toBeVisible();
  await page.getByRole("tab", { name: "1주 · 5거래일" }).click();
  await expect(page.getByRole("heading", { name: "1주 · 5거래일 후 과거 수익률" })).toBeVisible();
  await expect(page.getByText(/2주 뒤|상위 \d+%/)).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("failed public reads show retry, without restoring demo predictions", async ({ page }) => {
  let fail = true;
  await page.route("**/rest/v1/chart_signal_snapshots?**", route => route.fulfill(fail
    ? { status: 503, json: { message: "unavailable" } } : { json: rows }));
  await page.goto("/stocks/005930");
  // PostgREST retries transient 503 responses before exposing the error.
  await expect(page.getByText("차트를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요.", { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: /후 과거 수익률/ })).toHaveCount(0);
  fail = false;
  await page.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByTestId("preview-provenance")).toContainText("2026-09-21");
});
