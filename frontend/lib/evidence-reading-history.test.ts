import assert from "node:assert/strict";
import test, { type TestContext } from "node:test";
import {
  claimReadingHint,
  readReadingHistory,
  readingHistoryKey,
  recordReadingOutcome,
} from "./evidence-reading-history.ts";

function browserStorage(t: TestContext) {
  const values = new Map<string, string>();
  const previous = Object.getOwnPropertyDescriptor(globalThis, "window");
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
      },
    },
  });
  t.after(() => {
    if (previous) Object.defineProperty(globalThis, "window", previous);
    else Reflect.deleteProperty(globalThis, "window");
  });
  return values;
}

test("완료 뒤 다른 두 종목에서만 한 번씩 힌트를 보여요", (t) => {
  browserStorage(t);
  const key = readingHistoryKey("demo", "demo_minji");
  recordReadingOutcome(key, "005930", "dismissed");
  assert.equal(claimReadingHint(key, "000660"), false);
  recordReadingOutcome(key, "005930", "completed");
  assert.equal(claimReadingHint(key, "005930"), false);
  assert.equal(claimReadingHint(key, "000660"), true);
  assert.equal(claimReadingHint(key, "000660"), false);
  recordReadingOutcome(key, "000660", "completed");
  recordReadingOutcome(key, "000660", "dismissed");
  assert.equal(claimReadingHint(key, "005380"), true);
  assert.equal(claimReadingHint(key, "035720"), false);
});

test("다른 계정이나 손상된 기록에는 초대를 보여요", (t) => {
  const storage = browserStorage(t);
  const first = readingHistoryKey("supabase", "first");
  const second = readingHistoryKey("supabase", "second");
  recordReadingOutcome(first, "005930", "completed");
  storage.set(second, "{");
  assert.equal(readReadingHistory(first).status, "completed");
  assert.equal(readReadingHistory(second).status, "new");
  assert.equal(readReadingHistory(readingHistoryKey("demo", "first")).status, "new");
});

test("저장소 접근이 막혀도 현재 브라우저에서 안내를 마칠 수 있어요", () => {
  const key = readingHistoryKey("supabase", "blocked");
  assert.equal(readReadingHistory(key).status, "new");
  recordReadingOutcome(key, "005930", "completed");
  assert.equal(claimReadingHint(key, "000660"), true);
  assert.equal(claimReadingHint(key, "000660"), false);
});
