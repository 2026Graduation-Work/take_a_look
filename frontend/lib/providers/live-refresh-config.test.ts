import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

test("종목 화면은 Supabase 뉴스가 주기적으로 갱신되도록 재검증한다", () => {
  const pageSource = readFileSync(new URL("../../app/stocks/[code]/page.tsx", import.meta.url), "utf8");

  assert.match(pageSource, /export const revalidate = 3600;/);
});
