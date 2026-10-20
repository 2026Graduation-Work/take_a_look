// 형태별 정확도 표(맞은 수/전체): node tests/fixtures/holdings-ocr/accuracy.ts
// 규칙을 고칠 때 본 화면(조정용)과 보지 않은 화면(검증용, *-v2)을 따로 센다.
import { readFileSync } from "node:fs";
import { parseHoldings, type StockRef } from "../../../lib/holdings-ocr/parse.ts";

const DIR = new URL(".", import.meta.url);
type Answer = { form: string; holdout?: boolean; widths: number[]; holdings: (StockRef & { quantity: number; avgBuyPrice: number; avgSource: "computed" | "label" })[]; unsupported: string[] };
const answers: Record<string, Answer> = JSON.parse(readFileSync(new URL("answers.json", DIR), "utf8"));
const MASTER: StockRef[] = [
  ...new Map<string, StockRef>(Object.values(answers).flatMap((screen) => screen.holdings.map(({ code, name }) => [code, { code, name }]))).values(),
  { code: "005935", name: "삼성전자우" }, { code: "000150", name: "두산" }, { code: "323410", name: "카카오뱅크" },
  { code: "005385", name: "현대차우" }, { code: "003550", name: "LG" }, { code: "000880", name: "한화" }, { code: "055550", name: "신한지주" },
];

const table = new Map<string, { name: number; qty: number; avg: number; total: number; extra: number; unsupported: number; unsupportedTotal: number }>();
const misses: string[] = [];
for (const [id, expected] of Object.entries(answers)) for (const width of expected.widths) {
  const result = parseHoldings(JSON.parse(readFileSync(new URL(`ocr/${id}-${width}.json`, DIR), "utf8")), MASTER);
  const key = expected.form.startsWith("P-") ? `${expected.form} 폰 캡처` : `${expected.form} ${expected.holdout ? "검증용" : "조정용"}`;
  const row = table.get(key) ?? { name: 0, qty: 0, avg: 0, total: 0, extra: 0, unsupported: 0, unsupportedTotal: 0 };
  for (const answer of expected.holdings) {
    row.total++;
    const found = result.holdings.find((holding) => holding.code === answer.code);
    if (!found) { misses.push(`${id}-${width} ${answer.name}: 종목 못 찾음`); continue; }
    row.name++;
    if (found.quantity === answer.quantity) row.qty++; else misses.push(`${id}-${width} ${answer.name}: 수량 ${found.quantity} (정답 ${answer.quantity})`);
    if (found.avgBuyPrice === answer.avgBuyPrice) row.avg++; else misses.push(`${id}-${width} ${answer.name}: 평균 매입가 ${found.avgBuyPrice} (정답 ${answer.avgBuyPrice})`);
  }
  row.extra += result.holdings.filter((holding) => !expected.holdings.some((answer) => answer.code === holding.code)).length;
  row.unsupportedTotal += expected.unsupported.length;
  const plain = (name: string) => name.replace(/\s+/g, ""); // 인식이 띄어쓰기를 빼먹는 것은 틀린 것으로 세지 않는다
  // 앱이 긴 이름을 말줄임(…)으로 자른 것은 앞부분이 맞으면 맞은 것으로 센다
  const same = (got: string, name: string) => { const cut = plain(got).replace(/(\.{2,}|…)$/, ""); return cut === plain(name) || (cut.length >= 4 && plain(name).startsWith(cut)); };
  row.unsupported += expected.unsupported.filter((name) => result.unsupported.some((got) => same(got, name))).length;
  table.set(key, row);
}
console.log("| 형태 | 종목명 | 수량 | 평균 매입가 | 잘못 넣은 종목 | 다루지 않는 종목 표시 |\n|---|---|---|---|---|---|");
for (const [key, row] of [...table].sort()) console.log(`| ${key} | ${row.name}/${row.total} | ${row.qty}/${row.total} | ${row.avg}/${row.total} | ${row.extra} | ${row.unsupported}/${row.unsupportedTotal} |`);
console.log(misses.length ? `\n틀린 예\n${misses.map((miss) => `- ${miss}`).join("\n")}` : "\n틀린 예 없음");
