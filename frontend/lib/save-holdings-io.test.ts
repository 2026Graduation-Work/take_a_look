import assert from "node:assert/strict";
import { test } from "node:test";
import type { SupabaseClient } from "@supabase/supabase-js";
import { loadAccountHoldings, saveHoldings } from "./save-holdings.ts";

const holding = { code: "005930", name: "삼성전자", quantity: 10, avgBuyPrice: null };
function fakeClient({ unknown = false, upsertError = false, readError = false, switchAccount = false } = {}) {
  const calls: string[] = [];
  const filters: unknown[][] = [];
  let authReads = 0;
  const client = {
    auth: { getUser: async () => ({ data: { user: { id: switchAccount && authReads++ > 0 ? "auth-b" : "auth-a" } }, error: null }) },
    from(table: string) {
      let write = false;
      const query = {
        select() { return query; },
        eq(...args: unknown[]) { filters.push(args); return query; },
        not(...args: unknown[]) { filters.push(args); return query; },
        in() { return query; },
        order() { return query; },
        maybeSingle: async () => ({ data: { id: "app-a" }, error: null }),
        update() { write = true; calls.push("disable"); return query; },
        upsert: async () => {
          calls.push("upsert");
          return { error: upsertError ? { message: "write failed" } : null };
        },
        then(resolve: (value: unknown) => void) {
          resolve({ data: table === "stocks" ? (unknown ? [] : [{ code: "005930" }]) :
            [{ stock_code: "005930", quantity: 10, avg_buy_price: null, stocks: { name: "삼성전자" } }],
          error: !write && readError ? { message: "read failed" } : null });
        },
      };
      return query;
    },
  } as unknown as SupabaseClient;
  return { client, calls, filters };
}

test("계정 보유는 DB에서 읽으며 조회 오류와 계정 전환을 빈 목록으로 처리하지 않는다", async () => {
  const { client, filters } = fakeClient();
  assert.deepEqual(await loadAccountHoldings("auth-a", client), [holding]);
  assert.ok(filters.some(([key, value]) => key === "user_id" && value === "app-a"));
  await assert.rejects(loadAccountHoldings("auth-b", client), /계정이 바뀌/);
  await assert.rejects(loadAccountHoldings("auth-a", fakeClient({ readError: true }).client), /조회 실패/);
  await assert.rejects(loadAccountHoldings("auth-a", fakeClient({ switchAccount: true }).client), /계정이 바뀌/);
});

test("보유 저장은 입력 검증과 upsert 성공 전에 기존 보유를 비활성화하지 않는다", async (t) => {
  const writes: string[] = [];
  const original = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", { configurable: true, value: {
    localStorage: { setItem: () => writes.push("cache") }, dispatchEvent: () => undefined,
  } });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, "window", original);
    else Reflect.deleteProperty(globalThis, "window");
  });
  const invalid = fakeClient();
  await assert.rejects(saveHoldings([{ ...holding, quantity: 0 }], "supabase", "auth-a", invalid.client));
  assert.deepEqual(invalid.calls, []);
  const unknown = fakeClient({ unknown: true });
  await assert.rejects(saveHoldings([holding], "supabase", "auth-a", unknown.client), /마스터/);
  assert.deepEqual(unknown.calls, []);
  const failed = fakeClient({ upsertError: true });
  await assert.rejects(saveHoldings([holding], "supabase", "auth-a", failed.client), /저장 실패/);
  assert.deepEqual(failed.calls, ["upsert"]);
  assert.deepEqual(writes, []);
  const ok = fakeClient();
  await saveHoldings([holding], "supabase", "auth-a", ok.client);
  assert.deepEqual(ok.calls, ["upsert", "disable"]);
  assert.ok(ok.filters.some(([key, operator, value]) => key === "stock_code" && operator === "in" && value === "(005930)"));
  const empty = fakeClient();
  await saveHoldings([], "supabase", "auth-a", empty.client);
  assert.deepEqual(empty.calls, ["disable"]);
  const beforeSwitch = writes.length;
  await assert.rejects(saveHoldings([holding], "supabase", "auth-a", fakeClient({ switchAccount: true }).client), /계정이 바뀌/);
  assert.equal(writes.length, beforeSwitch, "계정이 바뀌면 이전 계정 보유를 브라우저 캐시에 쓰지 않는다");
});
