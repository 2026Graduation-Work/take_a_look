// 대시보드 맨 위 한 줄 요약. 결정론 문장 템플릿(LLM을 쓰지 않는다): 같은 입력 → 같은 문장.

import type { SignalLight } from "./types";

const NEGATIVE: readonly SignalLight[] = ["negative", "strong_negative"];

export function dashboardSummary({
  holdingSignals,
  holdingCount,
  strongCount,
}: {
  holdingSignals: SignalLight[]; // 오늘 신호가 있는 보유 종목의 신호
  holdingCount: number; // 등록한 보유 종목 수(신호가 없는 종목 포함)
  strongCount: number; // "오늘 신호가 강한 종목" 목록 길이
}): string {
  if (holdingCount === 0) return `오늘 모델 신호가 강한 종목은 ${strongCount}개예요.`;
  const negative = holdingSignals.filter((signal) => NEGATIVE.includes(signal)).length;
  return negative > 0
    ? `보유 ${holdingCount}종목 중 ${negative}종목에 하방 신호가 있어요.`
    : `보유 ${holdingCount}종목 모두 하방 신호는 없어요.`;
}
