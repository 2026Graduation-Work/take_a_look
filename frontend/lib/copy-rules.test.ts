import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { test } from "node:test";
import * as glossary from "./copy-glossary.ts";
import { SIGNAL_WORD } from "./copy-glossary.ts";
import { contributionWord } from "./display.ts";
import { FORBIDDEN_COPY } from "./copy-rules.ts";

const ROOT = path.resolve(import.meta.dirname, "..");

// 검사하지 않는 파일과 이유.
const EXCLUDED = new Set([
  "lib/copy-rules.ts", // 금지 표현 목록 자체
  "lib/providers/sentiment-fixture.ts", // 실제 기사 제목(외부 데이터)이라 우리 문구가 아니다
  "lib/profiling/bit.ts", // composite 등 분류 계산의 정의 파일(화면 문구 없음)
  "lib/storage-keys.ts", // 옛 저장 키(signallab.*) 이전 코드 — 2027-02 이후 제거
]);


function sourceFiles(dir: string): string[] {
  return readdirSync(path.join(ROOT, dir), { withFileTypes: true, recursive: true })
    .filter((entry) => entry.isFile() && /\.tsx?$/.test(entry.name) && !entry.name.includes(".test."))
    .map((entry) => path.relative(ROOT, path.join(entry.parentPath, entry.name)))
    .filter((file) => !EXCLUDED.has(file));
}

// 주석은 사용자에게 보이지 않으므로 지운다. 줄 번호를 지키려고 블록 주석의 줄바꿈은 남긴다.
function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, ""))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, "$1");
}

test("사용자 노출 문구에 금지 표현이 없다", () => {
  const hits: string[] = [];
  for (const file of [...sourceFiles("app"), ...sourceFiles("lib")]) {
    const raw = readFileSync(path.join(ROOT, file), "utf8");
    const lines = stripComments(raw).split("\n");
    lines.forEach((line, index) => {
      for (const { pattern, reason, allowIn } of FORBIDDEN_COPY) {
        if (allowIn?.includes(file)) continue;
        if (pattern.test(line)) hits.push(`${file}:${index + 1} ${reason} — ${line.trim()}`);
      }
    });
  }
  assert.deepEqual(hits, []);
});

test("금지 표현 목록이 대표 문장을 잡는다", () => {
  const caught = (text: string) => FORBIDDEN_COPY.some(({ pattern }) => pattern.test(text));
  for (const text of [
    "지금 사세요",
    "지금 파세요",
    "비중을 낮게 가져가는 것을 권장합니다",
    "신규 진입은 신중히",
    "오를 것으로 보입니다",
    "적중률 61%",
    "정확도 64%",
    "정확도 {auc}",
    "기여도 12.0%",
    "기여도 {share}",
    "합이 100%가 아닐 수 있어요 · 기여도 = 비중 %",
    "오늘의 추천 종목",
    "넛지",
    "H10 · 10거래일 후",
    "68% 신뢰구간",
    "Supabase 조회값",
    "composite +0.2",
    "psych_greed_fear_axis +0.94",
    "prob_up 0.61",
    "Pompian 행동투자자 유형(BIT)",
    "시그널랩 로그인",
    "SignalLab",
    "signallab",
    "KRX · 2025.12.30 · 실데이터",
    "모델 신호 상방",
    "005930 · KOSPI",
    "강한 하방",
    "데이터를 불러오지 못했습니다.",
    "함께 반영합니다.",
    "코스피보다 저평가된 편",
    "PER이 낮아 싸요",
  ]) {
    assert.ok(caught(text), text);
  }
  assert.ok(!caught("과거 유사 신호 중 상승 비율 61%"));
  assert.ok(!caught("하락 점수를 높였어요. 영향 비중 12.0%"));
  assert.ok(!caught("getSupabaseClient()"));
  assert.ok(!caught("const h10 = agreement.h10"));
  assert.ok(!caught("signalLabel"));
  assert.ok(!caught("전체 피처 기여도 기준값이 올바르지 않아요."));
});

test("신호 방향 이름(상승·하락)은 확률·전망 금지 규칙에 걸리지 않는다", () => {
  const caught = (text: string) => FORBIDDEN_COPY.filter(({ pattern }) => pattern.test(text)).map(({ reason }) => reason);
  for (const text of [...Object.values(SIGNAL_WORD), `강한 ${SIGNAL_WORD.up}`,
    contributionWord(0.12, SIGNAL_WORD.down, 1), `보유 4종목 중 ${SIGNAL_WORD.down} 신호는 없어요.`]) {
    assert.deepEqual(caught(text), [], text);
  }
});

// DESIGN.md 0장 "문장 끝 규칙": 보조 설명 문장은 "~요."로 끝낸다. 라벨·짧은 구는 '요'로 끝나지 않으니 걸리지 않는다
test("쉬운 말 사전의 설명 문장은 마침표로 끝난다", () => {
  const LABELS = new Set(Object.values(glossary.AGREEMENT_ANSWER)); // 질문("기간마다 같은 방향인가요?")에 답하는 짧은 말
  const strings: string[] = [];
  const walk = (value: unknown) => {
    if (typeof value === "string") strings.push(value);
    else if (value && typeof value === "object") Object.values(value).forEach(walk);
  };
  walk(Object.values(glossary).filter((value) => typeof value !== "function"));
  const bad = strings.filter((text) => /요$/.test(text) && !LABELS.has(text));
  assert.deepEqual(bad, []);
  assert.ok(strings.includes(glossary.SHORT_HORIZON_NOTE) && glossary.SHORT_HORIZON_NOTE.endsWith("요."));
});

// DESIGN.md '용어 설명 단계': 모든 용어에 쉬운 이름, 정의 한 문장, 읽는 법이 있다. 라벨 괄호에는 약어만
test("용어 사전의 모든 용어에 쉬운 이름, 정의, 읽는 법이 있다", () => {
  for (const [key, term] of Object.entries(glossary.TERM_INFO)) {
    assert.ok(term.label && !/\((?![A-Zσ]+\))/.test(term.label), `${key} 라벨 괄호는 약어만: ${term.label}`);
    assert.match(term.define, /^[^.]+요\.$/, `${key} 정의는 한 문장`);
    assert.match(term.read, /요\.$/, `${key} 읽는 법`);
  }
  assert.equal(glossary.compareLine(27.9, 11.23, "코스피", "배"), "코스피 중간값 11.2배보다 높아요.");
  assert.equal(glossary.compareLine(11.5, 11.23, "코스피", "배"), "코스피 중간값 11.2배와 비슷해요.");
});
