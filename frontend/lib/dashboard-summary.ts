import { SIGNAL_WORD } from "./copy-glossary.ts";
import type { SignalLight } from "./types";

const NEGATIVE: readonly SignalLight[] = ["negative", "strong_negative"];

export function dashboardSummary({
  holdings,
  holdingCount,
  strongCount,
}: {
  holdings: { name: string; signal: SignalLight }[];
  holdingCount: number; // 신호가 없는 종목 포함
  strongCount: number;
}): string {
  if (holdingCount === 0) return `오늘 모델 신호가 강한 종목은 ${strongCount}개예요.`;
  if (holdings.length === 0) return "보유 종목의 게시된 신호가 아직 없어요.";
  const negative = holdings.filter(({ signal }) => NEGATIVE.includes(signal)).map(({ name }) => name);
  if (negative.length === 0) return `${holdings.length < holdingCount ? "신호를 확인한 보유 종목" : "보유 종목"} 중 ${SIGNAL_WORD.down} 신호는 없어요.`;
  if (negative.length <= 2) return `${negative.join(", ")}에 ${SIGNAL_WORD.down} 신호가 있어요.`;
  return `보유 종목 중 ${negative.length}종목에 ${SIGNAL_WORD.down} 신호가 있어요.`;
}
