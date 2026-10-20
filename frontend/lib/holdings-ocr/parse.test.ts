import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { mergeResults, parseHoldings, type StockRef } from "./parse.ts";

// 시험 화면(tests/fixtures/holdings-ocr, 가짜 수치)을 실제 인식 모듈로 읽은 고정값으로 해석 규칙만 검사한다. CI는 모델을 받지 않는다.
const DIR = new URL("../../tests/fixtures/holdings-ocr/", import.meta.url);
type Answer = { form: string; holdout?: boolean; widths: number[]; holdings: (StockRef & { quantity: number; avgBuyPrice: number; avgSource: "computed" | "label" })[]; unsupported: string[] };
const answers: Record<string, Answer> = JSON.parse(readFileSync(new URL("answers.json", DIR), "utf8"));
const ocr = (id: string) => JSON.parse(readFileSync(new URL(`ocr/${id}.json`, DIR), "utf8"));

// 정답 종목 + 헷갈리기 쉬운 실제 종목(로고 글자 '두산', 비슷한 이름 '삼성전자우', '카카오뱅크' 등)
const MASTER: StockRef[] = [
  ...new Map<string, StockRef>(Object.values(answers).flatMap((screen) => screen.holdings.map(({ code, name }) => [code, { code, name }]))).values(),
  { code: "005935", name: "삼성전자우" },
  { code: "000150", name: "두산" },
  { code: "323410", name: "카카오뱅크" },
  { code: "377300", name: "카카오페이" },
  { code: "005385", name: "현대차우" },
  { code: "003550", name: "LG" },
  { code: "000880", name: "한화" },
];

for (const id of Object.keys(answers)) for (const width of answers[id].widths) {
  test(`${id}-${width}: 종목, 수량, 평균 매입가와 다루지 않는 종목`, () => {
    const result = parseHoldings(ocr(`${id}-${width}`), MASTER);
    const expected = answers[id];
    assert.deepEqual(
      result.holdings.map(({ code, quantity, avgBuyPrice, avgComputed }) => ({ code, quantity, avgBuyPrice, avgComputed })),
      expected.holdings.map(({ code, quantity, avgBuyPrice, avgSource }) => ({ code, quantity, avgBuyPrice, avgComputed: avgSource === "computed" })),
    );
    // 띄어쓰기는 인식이 빼먹기도 하고, 폰 앱은 긴 이름을 말줄임으로 자른다(앞 4자 이상 맞으면 같은 이름)
    const plain = (name: string) => name.replace(/\s+/g, "");
    const same = (got: string, name: string) => plain(got) === plain(name) || (plain(got).length >= 4 && plain(name).startsWith(plain(got)));
    assert.equal(result.unsupported.length, expected.unsupported.length);
    for (const name of expected.unsupported) assert.ok(result.unsupported.some((got) => same(got, name)), name);
  });
}

test("규칙 1: 줄바꿈된 긴 이름과 6자리 코드, 비슷한 글자", () => {
  const line = (text: string, y0: number, x0 = 20) => ({ text, score: 0.99, x0, y0, x1: x0 + 200, y1: y0 + 40 });
  const result = parseHoldings([line("한화에어로스", 100), line("페이스", 145), line("3주", 190), line("삼성전자 005930", 400), line("12주", 445), line("셀트리욘", 700), line("5주", 745)], [
    { code: "012450", name: "한화에어로스페이스" }, { code: "005930", name: "삼성전자" }, { code: "068270", name: "셀트리온" },
  ]);
  assert.deepEqual(result.holdings.map(({ code, quantity, check }) => [code, quantity, check.includes("name")]), [
    ["012450", 3, false], ["005930", 12, false], ["068270", 5, true],
  ]);
});

test("규칙 4, 5: 소수점 수량은 다루지 않는 종목, 평균 매입가가 없으면 확인 필요", () => {
  const line = (text: string, y0: number, x0 = 20) => ({ text, score: 0.99, x0, y0, x1: x0 + 200, y1: y0 + 40 });
  const result = parseHoldings([line("애플", 100), line("0.015819주", 145), line("삼성전자", 400), line("7주", 445)], [{ code: "005930", name: "삼성전자" }]);
  assert.deepEqual(result.unsupported, ["애플"]);
  assert.deepEqual(result.holdings, [{ code: "005930", name: "삼성전자", quantity: 7, avgBuyPrice: null, avgComputed: false, check: ["avgBuyPrice"] }]);
});

test("규칙 6: 여러 장은 코드로 합치고 수량을 더하지 않으며, 다르면 확인 필요", () => {
  const one = { code: "005930", name: "삼성전자", quantity: 10, avgBuyPrice: 70000, avgComputed: false, check: [] };
  const merged = mergeResults([{ holdings: [one], unsupported: ["KODEX 200"] }, { holdings: [{ ...one, quantity: 12 }], unsupported: ["KODEX 200"] }]);
  assert.deepEqual(merged, { holdings: [{ ...one, check: ["quantity"] }], unsupported: ["KODEX 200"] });
  assert.equal(mergeResults([{ holdings: [one], unsupported: [] }, { holdings: [one], unsupported: [] }]).holdings[0].check.length, 0);
});
