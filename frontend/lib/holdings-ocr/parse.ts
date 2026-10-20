// 보유 화면 캡처에서 읽은 글자(글자 + 위치)를 보유 종목으로 바꾸는 규칙. 결정론이고 LLM을 쓰지 않는다.
// 같은 입력이면 늘 같은 결과다. 규칙 번호는 PR 설명과 같다.
//  1) 종목명: 종목 마스터와 맞춘다(공백 무시, 6자리 코드, 비슷한 글자 허용). 줄바꿈된 긴 이름은 아래 줄과 합쳐 본다
//  2) 한 종목 이름부터 다음 종목 이름 전까지의 숫자를 그 종목 것으로 본다
//  3) 표 머리(보유수량, 평가금액, 평가손익, 평균단가 등)가 있으면 열 위치로, 없으면 'N주'와 '원', '±손익(수익률%)' 모양으로 읽는다
//  4) 수량은 정수만(소수면 해외 소수점 주식으로 보고 뺀다). 평균 매입가 열이 없으면 (평가금액 − 평가손익) ÷ 수량을 원 단위로 반올림
//  5) 마스터에 없는 이름(ETF, ETN, 해외 주식)은 '다루지 않는 종목'으로 따로 둔다. 지수, 합계 줄은 버린다
//  6) 여러 장은 종목 코드로 합친다(수량을 더하지 않는다). 같은 종목의 숫자가 다르면 '확인 필요'

import type { OcrLine } from "./recognize";

export interface StockRef {
  code: string;
  name: string;
}

export type CheckField = "name" | "quantity" | "avgBuyPrice";

export interface ParsedHolding {
  code: string;
  name: string;
  quantity: number | null;
  avgBuyPrice: number | null;
  avgComputed: boolean; // 평균 매입가를 평가금액과 평가손익으로 계산했다
  check: CheckField[]; // 자신 없는 칸(사용자 확인 필요)
}

export interface ParseResult {
  holdings: ParsedHolding[];
  unsupported: string[];
}

const LOW_SCORE = 0.9; // 인식 확신이 이보다 낮은 숫자는 '확인 필요'
const ETF_PREFIX = /^(KODEX|TIGER|KBSTAR|RISE|ACE|SOL|ARIRANG|HANARO|KOSEF|PLUS|KIWOOM|TIMEFOLIO|WOORI|BNK|TREX|FOCUS|마이티|파워|히어로즈|1Q)(?![a-z])|ETN|ETF/i;
const NOT_A_NAME = /^(합계|총합계|소계|총평가|평가손익|종목명|KOSPI|KOSDAQ|코스피|코스닥|국내주식|해외주식|장종료|장마감|S&P)/i;
const HEADERS: [keyof Columns, RegExp][] = [
  ["avg", /평균단가|평균가|평균매입가|매입단가|매입가|평단/],
  ["qty", /보유수량|잔고수량|수량/],
  ["value", /평가금액|평가금/],
  ["pnl", /평가손익|^손익$/],
  ["rate", /수익률/],
  ["price", /현재가/],
];

type Columns = { avg: number; qty: number; value: number; pnl: number; rate: number; price: number };
type Key = keyof Columns;
type Line = OcrLine & { compact: string };
type Anchor = { lines: Line[]; ref: StockRef | null; label: string; fuzzy: boolean; y0: number; x0: number };

const compact = (text: string) => text.normalize("NFC").replace(/\s+/g, "");
const midX = (line: OcrLine) => (line.x0 + line.x1) / 2;
const median = (values: number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
};

function editDistance(a: string, b: string): number {
  const row = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i++) {
    let previous = row[0];
    row[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const current = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (a[i - 1] === b[j - 1] ? 0 : 1));
      previous = current;
    }
  }
  return row[b.length];
}

// 규칙 1: 정확히 같은 이름 → 6자리 코드 → 비슷한 이름(3자 이상, 짧으면 1자, 6자 이상이면 2자까지 다름, 가장 가까운 것이 하나일 때만)
function matchName(text: string, byName: Map<string, StockRef>, byCode: Map<string, StockRef>, names: string[]): { ref: StockRef; fuzzy: boolean } | null {
  const key = text.toUpperCase();
  const exact = byName.get(key);
  if (exact) return { ref: exact, fuzzy: false };
  const code = key.match(/(?<!\d)(\d{6})(?!\d)/)?.[1];
  if (code && byCode.has(code)) return { ref: byCode.get(code)!, fuzzy: false };
  if (key.length < 3 || /^[\d.,+\-−%()원주]+$/.test(key)) return null;
  const limit = key.length >= 6 ? 2 : 1;
  let best: string | null = null;
  let bestDistance = limit + 1;
  let tie = false;
  for (const name of names) {
    if (Math.abs(name.length - key.length) > limit) continue;
    const distance = editDistance(key, name);
    if (distance < bestDistance) [best, bestDistance, tie] = [name, distance, false];
    else if (distance === bestDistance) tie = true;
  }
  return best && !tie ? { ref: byName.get(best)!, fuzzy: true } : null;
}

// 주를 추로 읽는 일이 있어 받아 준다(낮은 확신이면 확인 필요로 남는다)
const QTY = /^([\d,.]+)[주추쥬]$/;
const WITH_RATE = /^([+\-−]?[\d,]+)원?\(([+\-−]?[\d.]+)%\)$/;

// 금액(원 단위 정수). '1.205.000'처럼 쉼표를 점으로 읽은 것도 받는다
function parseAmount(text: string): number | null {
  const body = text.replace(/원$/, "").replace(/−/g, "-");
  if (!/^[+-]?\d{1,3}([.,]\d{3})*$|^[+-]?\d+$/.test(body)) return null;
  return Number(body.replace(/[.,]/g, ""));
}

const HEADER_WORDS: [string, Key][] = [["평가손익", "pnl"], ["평가금액", "value"], ["보유수량", "qty"], ["평균단가", "avg"], ["매입단가", "avg"], ["수익률", "rate"], ["현재가", "price"]];

function headerKey(text: string): Key | null {
  for (const [key, pattern] of HEADERS) if (pattern.test(text)) return key;
  return null;
}

// 표 머리를 잘못 읽어도(평간손일) 한 글자씩 다르게 읽은 것까지는 가장 가까운 머리로 본다. 비기면 버린다
function fuzzyHeaderKey(text: string): Key | null {
  const exact = headerKey(text);
  if (exact || text.length < 3) return exact;
  const scored = HEADER_WORDS.map(([word, key]) => ({ key, distance: editDistance(text, word) })).sort((a, b) => a.distance - b.distance);
  const limit = text.length >= 4 ? 2 : 1;
  return scored[0].distance <= limit && scored[1].distance > scored[0].distance ? scored[0].key : null;
}

export function parseHoldings(ocr: OcrLine[], master: StockRef[]): ParseResult {
  const byName = new Map(master.map((ref) => [compact(ref.name).toUpperCase(), ref]));
  const byCode = new Map(master.map((ref) => [ref.code, ref]));
  const names = [...byName.keys()];
  const lines: Line[] = ocr.map((line) => ({ ...line, text: line.text.trim(), compact: compact(line.text) })).filter((line) => line.compact);
  lines.sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0);
  const h = median(lines.map((line) => line.y1 - line.y0)) || 1;

  // 규칙 1: 이름 줄 찾기(아래 줄과 합쳐 보기 포함)
  const used = new Set<Line>();
  const anchors: Anchor[] = [];
  for (const line of lines) {
    if (used.has(line) || headerKey(line.compact) || NOT_A_NAME.test(line.compact) || !/[가-힣A-Za-z]/.test(line.compact)) continue;
    const near = (next: Line) =>
      next !== line && !used.has(next) && next.y0 > line.y0 + h * 0.5 && next.y0 < line.y1 + h * 0.8 && Math.abs(next.x0 - line.x0) < h * 0.6;
    // 줄바꿈된 이름의 뒷부분: 바로 아래, 같은 왼쪽 끝. 'N주'나 금액은 아니다('KODEX 20' + '0'처럼 한두 자리 숫자는 이름 조각)
    const below = lines.find((next) => near(next) && !QTY.test(next.compact) && (parseAmount(next.compact) === null || /^\d{1,2}$/.test(next.compact)) && !matchName(next.compact, byName, byCode, names));
    const single = matchName(line.compact, byName, byCode, names);
    const joined = below ? matchName(line.compact + below.compact, byName, byCode, names) : null;
    const pick = joined && (!single || single.fuzzy || !joined.fuzzy) ? { ...joined, lines: [line, below!] } : single ? { ...single, lines: [line] } : null;
    if (pick) {
      pick.lines.forEach((part) => used.add(part));
      anchors.push({ lines: pick.lines, ref: pick.ref, label: pick.ref.name, fuzzy: pick.fuzzy, y0: line.y0, x0: line.x0 });
      continue;
    }
    // 규칙 5: 마스터에 없는 종목 줄(ETF 이름 모양이거나 바로 아래에 'N주'가 있는 이름)
    const qtyBelow = lines.find((next) => QTY.test(next.compact) && next.y0 > line.y0 && next.y0 < line.y1 + h * 0.8 && Math.abs(next.x0 - line.x0) < h * 0.6);
    if (ETF_PREFIX.test(line.compact) || qtyBelow) {
      const parts = below && (ETF_PREFIX.test(line.compact) || /^\d{1,2}$/.test(below.compact)) ? [line, below] : [line];
      parts.forEach((part) => used.add(part));
      anchors.push({ lines: parts, ref: null, label: parts.map((part) => part.text).join(parts.length > 1 ? "" : " "), fuzzy: false, y0: line.y0, x0: line.x0 });
    }
  }
  // 같은 줄에 이름이 둘이면(원형 로고 글자 등) 긴 이름 하나만
  anchors.sort((a, b) => a.y0 - b.y0);
  for (let i = anchors.length - 1; i > 0; i--) {
    const [upper, lower] = [anchors[i - 1], anchors[i]];
    if (Math.abs(upper.y0 - lower.y0) < h) {
      const drop = compact(upper.label).length >= compact(lower.label).length ? i : i - 1;
      anchors.splice(drop, 1);
    }
  }

  // 표 머리 열(겹쳐 쓴 2줄 머리는 한 열로 묶는다)
  // 한두 글자씩 끊어 읽은 머리('보유' '수' '량')는 같은 열끼리 위에서 아래로 이어 붙인다
  const columns: { x0: number; x1: number; keys: Key[] }[] = [];
  const firstAnchor = anchors[0]?.y0 ?? Infinity;
  const band: Line[] = [];
  for (const line of lines.filter((candidate) => candidate.y1 <= firstAnchor && !used.has(candidate))) {
    const piece = line.compact.length <= 2 ? band.find((other) => other.compact.length <= 4 && Math.abs(midX(other) - midX(line)) < h * 1.5 && line.y0 - other.y1 < h) : undefined;
    if (piece && !headerKey(line.compact)) Object.assign(piece, { compact: piece.compact + line.compact, x0: Math.min(piece.x0, line.x0), x1: Math.max(piece.x1, line.x1), y1: line.y1 });
    else band.push({ ...line });
  }
  for (const header of band.filter((line) => fuzzyHeaderKey(line.compact))) {
    const key = fuzzyHeaderKey(header.compact)!;
    // 위아래로 겹쳐 쓴 머리(평가손익 / 수익률)만 한 열: 가로로 겹치는 머리끼리
    const column = columns.find((col) => Math.min(col.x1, header.x1) - Math.max(col.x0, header.x0) > 0);
    if (column) column.keys.push(key);
    else columns.push({ x0: header.x0, x1: header.x1, keys: [key] });
  }

  const spacing = median(anchors.slice(1).map((anchor, i) => anchor.y0 - anchors[i].y0)) || h * 4;
  const holdings: ParsedHolding[] = [];
  const unsupported: string[] = [];
  anchors.forEach((anchor, index) => {
    if (!anchor.ref) {
      // 앱이 긴 이름을 자른 말줄임(…, ..., 마지막 점 하나로 읽히기도 함)은 떼고 보인다
      const label = anchor.label.replace(/\s*[.…]+$/, "");
      if (!unsupported.includes(label)) unsupported.push(label);
      return;
    }
    // 규칙 2: 이 이름부터 다음 이름 전까지
    const top = anchor.y0 - h * 0.5;
    const bottom = Math.min(anchors[index + 1]?.y0 ?? Infinity, anchor.y0 + spacing) - h * 0.5;
    const region = lines.filter((line) => !used.has(line) && line.y0 >= top && line.y0 < bottom && !headerKey(line.compact));
    const values: Partial<Record<Key, { value: number; score: number }>> = {};
    let fraction = false;
    const set = (key: Key, value: number, score: number) => {
      if (!(key in values)) values[key] = { value, score };
    };
    // 규칙 3-a: 모양으로 아는 값
    for (const line of region) {
      const qty = line.compact.match(QTY);
      if (qty) {
        if (/\./.test(qty[1])) fraction = true;
        else set("qty", Number(qty[1].replace(/,/g, "")), line.score);
        continue;
      }
      const withRate = line.compact.match(WITH_RATE);
      if (withRate) set("pnl", parseAmount(withRate[1]) ?? Number.NaN, line.score);
      else if (columns.length === 0 && /원$/.test(line.compact) && parseAmount(line.compact) !== null) set("value", parseAmount(line.compact)!, line.score);
      // 부호 붙은 금액은 손익이다(수량, 가격, 평가금액에는 부호가 없다). '+537,600' '(22.6%)'처럼 두 조각으로 읽히거나 표 머리를 못 읽어도 쓴다
      else if (/^[+\-−]/.test(line.compact) && parseAmount(line.compact) !== null) set("pnl", parseAmount(line.compact)!, line.score);
    }
    // 규칙 3-b: 표 머리 열로 아는 값(같은 열에 머리가 2줄이면 위아래 순서로)
    for (const column of columns) {
      const cells = region
        .filter((line) => parseAmount(line.compact) !== null && (Math.abs(midX(line) - (column.x0 + column.x1) / 2) < h * 1.5 || Math.abs(line.x1 - column.x1) < h))
        .sort((a, b) => a.y0 - b.y0);
      cells.slice(0, column.keys.length).forEach((cell, i) => set(column.keys[i], parseAmount(cell.compact)!, cell.score));
    }
    if (fraction) {
      // 앱이 긴 이름을 자른 말줄임(…, ..., 마지막 점 하나로 읽히기도 함)은 떼고 보인다
      const label = anchor.label.replace(/\s*[.…]+$/, "");
      if (!unsupported.includes(label)) unsupported.push(label);
      return;
    }
    const check: CheckField[] = anchor.fuzzy || anchor.lines.some((line) => line.score < LOW_SCORE) ? ["name"] : [];
    const quantity = values.qty && values.qty.value > 0 ? values.qty.value : null;
    if (!quantity || values.qty!.score < LOW_SCORE) check.push("quantity");
    // 규칙 4: 평균 매입가
    let avgBuyPrice: number | null = null;
    let avgComputed = false;
    let avgScore = 1;
    if (values.avg) [avgBuyPrice, avgScore] = [values.avg.value, values.avg.score];
    else if (quantity && values.value && values.pnl && Number.isFinite(values.pnl.value)) {
      avgBuyPrice = Math.round((values.value.value - values.pnl.value) / quantity);
      avgComputed = true;
      avgScore = Math.min(values.value.score, values.pnl.score);
    }
    if (avgBuyPrice !== null && avgBuyPrice <= 0) avgBuyPrice = null;
    if (avgBuyPrice === null || avgScore < LOW_SCORE) check.push("avgBuyPrice");
    holdings.push({ code: anchor.ref.code, name: anchor.ref.name, quantity, avgBuyPrice, avgComputed, check });
  });
  return mergeResults([{ holdings, unsupported }]);
}

// 규칙 6: 여러 장을 종목 코드로 합친다. 수량을 더하지 않고, 숫자가 다르면 그 칸을 '확인 필요'로
export function mergeResults(results: ParseResult[]): ParseResult {
  const byCode = new Map<string, ParsedHolding>();
  for (const holding of results.flatMap((result) => result.holdings)) {
    const seen = byCode.get(holding.code);
    if (!seen) {
      byCode.set(holding.code, { ...holding, check: [...holding.check] });
      continue;
    }
    const flag = (field: CheckField) => !seen.check.includes(field) && seen.check.push(field);
    if (seen.quantity === null) seen.quantity = holding.quantity;
    else if (holding.quantity !== null && holding.quantity !== seen.quantity) flag("quantity");
    if (seen.avgBuyPrice === null) [seen.avgBuyPrice, seen.avgComputed] = [holding.avgBuyPrice, holding.avgComputed];
    else if (holding.avgBuyPrice !== null && holding.avgBuyPrice !== seen.avgBuyPrice) flag("avgBuyPrice");
  }
  const unsupported = [...new Set(results.flatMap((result) => result.unsupported))];
  return { holdings: [...byCode.values()], unsupported };
}
