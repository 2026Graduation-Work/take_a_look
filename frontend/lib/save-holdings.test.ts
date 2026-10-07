import assert from "node:assert/strict";
import { test } from "node:test";
import { costBasis, isValidHolding, parseSavedHoldings, type SavedHolding } from "./holdings-rules.ts";

const ok: SavedHolding = { code: "005930", name: "삼성전자", quantity: 15, avgBuyPrice: 71_200 };

test("보유 종목 검증: 정상 입력만 통과한다", () => {
  assert.equal(isValidHolding(ok), true);
  // 무상증자 등으로 평단이 0일 수 있다
  assert.equal(isValidHolding({ ...ok, avgBuyPrice: 0 }), true);
  // 평균 매입가는 모르면 비워 둘 수 있다
  assert.equal(isValidHolding({ ...ok, avgBuyPrice: null }), true);

  assert.equal(isValidHolding({ ...ok, quantity: 0 }), false, "수량 0은 보유가 아니다");
  assert.equal(isValidHolding({ ...ok, quantity: -1 }), false);
  assert.equal(isValidHolding({ ...ok, quantity: 1.5 }), false, "주식은 정수 단위");
  assert.equal(isValidHolding({ ...ok, quantity: Number.NaN }), false, "빈 입력은 NaN이 된다");
  assert.equal(isValidHolding({ ...ok, avgBuyPrice: -100 }), false);
  assert.equal(isValidHolding({ ...ok, code: "5930" }), false, "종목코드는 6자리");
  assert.equal(isValidHolding({ ...ok, code: "00593A" }), false);
  assert.equal(isValidHolding({ ...ok, name: "  " }), false);
});

test("저장본 파싱: 깨진 값은 버리고 빈 배열과 없음을 구분한다", () => {
  assert.equal(parseSavedHoldings(null), null, "저장한 적 없음");
  assert.deepEqual(parseSavedHoldings("[]"), [], "전부 지웠음 — 없음과 다르다");
  assert.equal(parseSavedHoldings("{"), null, "깨진 JSON");
  assert.equal(parseSavedHoldings('{"code":"005930"}'), null, "배열이 아님");

  const mixed = JSON.stringify([ok, { code: "005380" }, null, "x"]);
  assert.deepEqual(parseSavedHoldings(mixed), [ok], "모양이 맞는 항목만 남는다");
});

test("비중 단가: 최신 종가가 있으면 평가금액, 없으면 매입금액으로 센다", () => {
  assert.deepEqual(costBasis(71_200, 92_300), { price: 92_300, basis: "close" });
  assert.deepEqual(costBasis(null, 92_300), { price: 92_300, basis: "close" });
  assert.deepEqual(costBasis(71_200, undefined), { price: 71_200, basis: "avg_buy" });
  assert.deepEqual(costBasis(null, undefined), { price: 0, basis: "avg_buy" });
  const withNull = JSON.stringify([{ ...ok, avgBuyPrice: null }]);
  assert.deepEqual(parseSavedHoldings(withNull), [{ ...ok, avgBuyPrice: null }]);
});
