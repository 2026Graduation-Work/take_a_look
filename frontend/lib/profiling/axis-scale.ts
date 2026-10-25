// 성향 축의 화면 이름과 방향 한 곳. 설문 결과, 내 투자 성향, 더 알아보기가 모두 여기서 가져온다.
// 극 이름 규칙: 오른쪽은 축 이름의 '더' 쪽, 극 이름은 결과(수익 기회)가 아니라 행동(손실도 감수)으로 쓴다.
// flip은 화면만 뒤집는다. 저장 값(ratio)과 채점은 style-questions.json의 극성 그대로다.
import type { StyleAxisId } from "../types";

export interface AxisScale {
  name: string; // 단어형 축 이름
  left: string; // 막대 아래 왼쪽 끝 한 단어
  right: string;
  leftSide: string; // 단계 말 "… 쪽"에 들어가는 행동
  rightSide: string;
  flip?: boolean; // 저장 값 +1이 화면 왼쪽이면 true
  words?: readonly [string, string, string, string, string]; // 단계 말을 따로 정한 축
}

// 5칸: −1~−0.6 / −0.6~−0.2 / −0.2~0.2 / 0.2~0.6 / 0.6~1. 경계값은 가운데 쪽 칸에 넣어 좌우가 대칭이다.
export const STAGE_COUNT = 5;
export const STAGE_CENTERS = [-1, -0.5, 0, 0.5, 1] as const;

export function stageIndex(value: number): number {
  if (value < -0.6) return 0;
  if (value < -0.2) return 1;
  if (value <= 0.2) return 2;
  if (value <= 0.6) return 3;
  return 4;
}

const shown = (axis: AxisScale, stored: number) => (axis.flip ? -stored : stored);

// 저장 값 → 화면 칸(0 = 왼쪽)
export function stageOf(axis: AxisScale, stored: number): number {
  return stageIndex(shown(axis, stored));
}

// 화면 칸 → 저장할 값(그 칸의 가운데)
export function storedForStage(axis: AxisScale, stage: number): number {
  const center = STAGE_CENTERS[stage];
  return axis.flip ? -center || 0 : center;
}

export function stageWord(axis: AxisScale, stage: number): string {
  if (axis.words) return axis.words[stage];
  return [
    `${axis.leftSide} 쪽이 강해요`,
    `${axis.leftSide} 쪽`,
    "중간",
    `${axis.rightSide} 쪽`,
    `${axis.rightSide} 쪽이 강해요`,
  ][stage];
}

// 8축. 극성(+1)은 style-questions.json axes의 positive_label 쪽이다.
export const STYLE_AXIS_SCALE: Record<StyleAxisId, AxisScale> = {
  market_participation: { name: "내 목표 중시", left: "시장 따라", right: "내 목표", leftSide: "시장 수익을 따라가는", rightSide: "내 목표를 앞세우는" },
  loss_tolerance: { name: "손실 감수", left: "원금 지킴", right: "손실 감수", leftSide: "원금을 지키는", rightSide: "손실도 감수하는" },
  turnover: { name: "보유 기간", left: "짧게", right: "길게", leftSide: "단기 매매", rightSide: "장기 보유", flip: true },
  concentration: { name: "모아 담기", left: "나눠 담음", right: "모아 담음", leftSide: "여러 종목에 나눠 담는", rightSide: "몇 종목에 모아 담는" },
  rule_adherence: { name: "규칙 지키기", left: "그때그때", right: "규칙대로", leftSide: "그때그때 바꾸는", rightSide: "정한 규칙을 지키는", flip: true },
  information_reliance: { name: "주변 영향", left: "직접 판단", right: "주변 따름", leftSide: "직접 확인해 판단하는", rightSide: "주변 분위기를 따르는" },
  urgency: { name: "서두름", left: "기다림", right: "서두름", leftSide: "여유 있게 기다리는", rightSide: "서둘러 결정하는" },
  drawdown_reaction: { name: "하락 때 팔기", left: "들고 감", right: "팔고 나옴", leftSide: "떨어져도 들고 가는", rightSide: "떨어지면 파는" },
};

// 3축 요약(profiling-rules.ts threeAxisSummary의 −1~1 평균). 투자 기간은 turnover와 같은 방향으로 뒤집는다.
export const SUMMARY_SCALE = {
  riskTaking: { name: "위험 감수", left: "적게", right: "많이", leftSide: "원금을 지키는", rightSide: "손실도 감수하는" },
  sensitivity: { name: "흔들림 민감도", left: "덤덤함", right: "민감함", leftSide: "덤덤한", rightSide: "쉽게 흔들리는" },
  horizon: { ...STYLE_AXIS_SCALE.turnover, name: "투자 기간" },
} satisfies Record<string, AxisScale>;

// 종목 상세 '가격 흐름 분위기'(psych_greed_fear_axis −1 움츠러듦 ~ +1 들뜸)
export const PSYCHOLOGY_SCALE: AxisScale = {
  name: "가격 흐름 분위기",
  left: "움츠러듦",
  right: "들뜸",
  leftSide: "움츠러든",
  rightSide: "들뜬",
  words: ["많이 움츠러듦", "조금 움츠러듦", "차분함", "조금 들뜸", "많이 들뜸"],
};
