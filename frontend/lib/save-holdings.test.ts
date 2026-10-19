import assert from "node:assert/strict";
import { test } from "node:test";
import { costBasis, digitsOnly, mergeImported, numberDraft, gainRatio, isValidHolding, parseSavedHoldings, parseWholeNumber, type SavedHolding } from "./holdings-rules.ts";

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
  assert.equal(isValidHolding({ ...ok, code: "00104K" }), true, "KRX 영문 포함 종목코드도 허용한다");
  assert.equal(isValidHolding({ ...ok, code: "00104k" }), false);
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

test("평단 대비 평가손익(#255): 평단·종가가 모두 있어야 계산한다", () => {
  assert.ok(Math.abs(gainRatio(50_000, 56_000)! - 0.12) < 1e-12);
  assert.ok(Math.abs(gainRatio(50_000, 45_000)! + 0.1) < 1e-12);
  // 평단을 모르거나 0(무상증자), 종가가 없으면 미제공
  assert.equal(gainRatio(null, 56_000), null);
  assert.equal(gainRatio(0, 56_000), null);
  assert.equal(gainRatio(50_000, undefined), null);
});

test("숫자 입력칸 정리(#278): 문자·지수 표기·NaN이 들어가지 않는다", () => {
  assert.equal(digitsOnly("10abc", 9), "10");
  assert.equal(digitsOnly("1,200", 9), "1200");
  assert.equal(digitsOnly("1.5", 9), "1"); // 15가 되면 안 된다
  assert.equal(digitsOnly("318,000.5", 12), "318000");
  assert.equal(digitsOnly("１２", 9), "12");
  assert.equal(numberDraft("1.5", 9), "1.5"); // 보여 주고 넣을 때 막는다
  assert.ok(Number.isNaN(parseWholeNumber(numberDraft("1.5", 9))));
  assert.equal(numberDraft("2,500주", 9), "2500");
  assert.equal(numberDraft("１２", 9), "12");
  assert.equal(digitsOnly("", 9), ""); // 지워도 NaN이 아니라 빈칸
  assert.equal(digitsOnly("12345678901234567890123", 12), "123456789012"); // 1e+22 대신 자릿수에서 멈춤
  assert.ok(Number.isSafeInteger(Number(digitsOnly("9".repeat(30), 12))));
  // 엄격 파싱: 앞 숫자만 읽지 않는다
  assert.ok(Number.isNaN(parseWholeNumber("10abc")));
  assert.equal(parseWholeNumber("1,200"), 1200);
  assert.equal(parseWholeNumber(" "), null);
});

test("스크린샷에서 읽은 목록 합치기: 이미 있는 종목은 새 값으로 바꾸고 이름을 알려 준다", () => {
  const rows: SavedHolding[] = [
    { code: "005930", name: "삼성전자", quantity: 10, avgBuyPrice: null },
    { code: "035720", name: "카카오", quantity: 3, avgBuyPrice: 50000 },
  ];
  const result = mergeImported(rows, [
    { code: "005930", name: "삼성전자", quantity: 37, avgBuyPrice: 71200 },
    { code: "000660", name: "SK하이닉스", quantity: 5, avgBuyPrice: 182500 },
  ]);
  assert.deepEqual(result.replaced, ["삼성전자"]);
  assert.deepEqual(result.rows.map(({ code, quantity }) => [code, quantity]), [["005930", 37], ["035720", 3], ["000660", 5]]);
});
