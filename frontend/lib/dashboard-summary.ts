// 대시보드 맨 위 한 줄 요약. 결정론 문장 템플릿(LLM을 쓰지 않는다): 같은 입력 → 같은 문장.

import { SIGNAL_WORD } from "./copy-glossary.ts";
import type { SignalLight } from "./types";

const NEGATIVE: readonly SignalLight[] = ["negative", "strong_negative"];

export function dashboardSummary({
  holdings,
  holdingCount,
  strongCount,
}: {
  holdings: { name: string; signal: SignalLight }[]; // 오늘 신호가 있는 보유 종목
  holdingCount: number; // 등록한 보유 종목 수(신호가 없는 종목 포함)
  strongCount: number; // "오늘 신호가 강한 종목" 목록 길이
}): string {
  if (holdingCount === 0) return `오늘 모델 신호가 강한 종목은 ${strongCount}개예요.`;
  const negative = holdings.filter(({ signal }) => NEGATIVE.includes(signal)).map(({ name }) => name);
  if (negative.length === 0) return `보유 종목 중 ${SIGNAL_WORD.down} 신호는 없어요.`;
  // 1~2종목은 이름을 바로, 3종목부터는 개수로
  if (negative.length <= 2) return `${negative.join(", ")}에 ${SIGNAL_WORD.down} 신호가 있어요.`;
  return `보유 종목 중 ${negative.length}종목에 ${SIGNAL_WORD.down} 신호가 있어요.`;
}
