import assert from "node:assert/strict";
import test from "node:test";
import { detectChanges, disclosureHow, type ChangeInput } from "./daily-changes.ts";

const scores = (down: number, neutral: number, up: number) => ({ down, neutral, up });
const base: ChangeInput = {
  stocks: [{ code: "005380", name: "현대차" }, { code: "035720", name: "카카오" }, { code: "068270", name: "셀트리온" }, { code: "005930", name: "삼성전자" }],
  batchIds: ["b2", "b1"],
  signals: [
    { stock_code: "005380", batch_id: "b2", pack: "p", status: "available", scores: scores(0.2, 0.2, 0.6) },
    { stock_code: "005380", batch_id: "b1", pack: "p", status: "available", scores: scores(0.6, 0.2, 0.2) },
    { stock_code: "005930", batch_id: "b2", pack: "p", status: "available", scores: scores(0.6, 0.2, 0.2) },
    { stock_code: "005930", batch_id: "b1", pack: "p", status: "available", scores: scores(0.6, 0.2, 0.2) },
  ],
  sentiment: [
    { stock_code: "068270", track: "live", sentiment_date: "2026-10-07", sentiment_mean: 0.35 },
    { stock_code: "068270", track: "live", sentiment_date: "2026-10-08", sentiment_mean: -0.22 },
    { stock_code: "068270", track: "historical", sentiment_date: "2026-10-08", sentiment_mean: 0.5 }, // 같은 날은 Live 우선
  ],
  supply: [
    { stock_code: "035720", trade_date: "2026-10-07", foreign_investor: -165941, institution: -81776 },
    { stock_code: "035720", trade_date: "2026-10-08", foreign_investor: 108469, institution: -182066 },
  ],
  disclosures: [{ stock_code: "005930", kind: "earnings", title: "연결재무제표기준영업(잠정)실적(공정공시)", filed_on: "2026-10-08" }],
};

test("신호 전환 → 수급 전환 → 뉴스 부호 전환 순, 최대 3줄", () => {
  assert.deepEqual(detectChanges(base).map(({ name, text }) => `${name} ${text}`), [
    "현대차 4주 신호 상승으로",
    "카카오 외국인 순매수로",
    "셀트리온 뉴스 분위기 부정으로",
  ]);
});

test("주의 유형 공시는 신호 전환 다음으로 올라오고, 바뀐 것이 없으면 빈 목록", () => {
  const caution = { ...base, disclosures: [...base.disclosures, { stock_code: "005930", kind: "inquiry", title: "조회공시 답변", filed_on: "2026-10-08" }] };
  assert.equal(detectChanges(caution)[1].text, "새 공시 2건: 조회공시 답변");
  assert.deepEqual(detectChanges({ ...base, signals: [], sentiment: [], supply: [], disclosures: [] }), []);
});

test("모델(pack)이 바뀐 배치끼리는 신호 전환으로 보지 않는다", () => {
  const swapped = { ...base, signals: base.signals.map((row) => (row.batch_id === "b1" ? { ...row, pack: "old" } : row)) };
  assert.ok(!detectChanges(swapped).some(({ text }) => text.startsWith("4주 신호")));
});

test("공시 줄: 제목에 분류명이 있으면 분류명 생략(띄어쓰기 무시), 없으면 붙인다", () => {
  assert.equal(disclosureHow("기업설명회", "기업설명회(IR)개최(안내공시)"), "기업설명회(IR)개최(안내공시)");
  assert.equal(disclosureHow("조회 공시", "조회공시 답변"), "조회공시 답변");
  assert.equal(disclosureHow("실적 발표", "연결재무제표기준영업(잠정)실적(공정공시)"), "실적 발표 · 연결재무제표기준영업(잠정)실적(공정공시)");
});

test("같은 종목의 여러 변화는 한 줄로 합치고, 줄 수는 종목 기준으로 센다", () => {
  const both = { ...base, supply: [
    { stock_code: "035720", trade_date: "2026-10-07", foreign_investor: -165941, institution: 81776 },
    { stock_code: "035720", trade_date: "2026-10-08", foreign_investor: 108469, institution: -182066 },
  ] };
  const lines = detectChanges(both);
  assert.equal(lines.length, 3);
  assert.equal(lines.find(({ code }) => code === "035720")!.text, "외국인 순매수로, 기관 순매도로");
});
