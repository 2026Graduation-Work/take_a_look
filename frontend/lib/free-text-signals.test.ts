import assert from "node:assert/strict";
import test from "node:test";
import { extractFreeTextSignals, freeTextReadings } from "./free-text-signals.ts";

test("자유 답 키워드 → 보조값, 지운 판정은 빠지고, 판정이 없으면 빈 값", () => {
  const text = "남들 다 버는데 나만 뒤처지는 것 같아요. 마이너스 나면 잠을 못 자요.";
  assert.deepEqual(extractFreeTextSignals(text), { fomo_index: 0.8, panic_sell_tendency: 0.75 });
  assert.deepEqual(extractFreeTextSignals(text, ["panic_sell_tendency"]), { fomo_index: 0.8 });
  assert.deepEqual(extractFreeTextSignals("장기로 모아 가고 싶어요"), {});
  assert.deepEqual(freeTextReadings({ panic_sell_tendency: 0.75, unknown: 1 }), [{ field: "panic_sell_tendency", label: "손실 걱정" }]);
  assert.deepEqual(freeTextReadings({}), []);
});
