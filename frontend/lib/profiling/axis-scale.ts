// flip은 화면만 뒤집는다. 저장 값(ratio)과 채점은 style-questions.json의 극성 그대로다.
import type { StyleAxisId } from "../types";

export interface AxisScale {
  name: string;
  left: string;
  right: string;
  leftSide: string; // 단계 말에 쓰는 행동(명사형, 예: '원금을 지킴')
  rightSide: string;
  flip?: boolean; // 저장 값 +1이 화면 왼쪽이면 true
  words?: readonly [string, string, string, string, string];
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

// 0 = 왼쪽 칸
export function stageOf(axis: AxisScale, stored: number): number {
  return stageIndex(shown(axis, stored));
}

// 그 칸의 가운데 값
export function storedForStage(axis: AxisScale, stage: number): number {
  const center = STAGE_CENTERS[stage];
  return axis.flip ? -center || 0 : center;
}

export function stageWord(axis: AxisScale, stage: number): string {
  if (axis.words) return axis.words[stage];
  return [`아주 ${axis.leftSide}`, axis.leftSide, "중간", axis.rightSide, `아주 ${axis.rightSide}`][stage];
}

// 8축. 극성(+1)은 style-questions.json axes의 positive_label 쪽이다.
export const STYLE_AXIS_SCALE: Record<StyleAxisId, AxisScale> = {
  market_participation: { name: "내 목표 중시", left: "시장 따라", right: "내 목표", leftSide: "시장 수익을 따라감", rightSide: "내 목표를 앞세움" },
  loss_tolerance: { name: "손실 감수", left: "원금 지킴", right: "손실 감수", leftSide: "원금을 지킴", rightSide: "손실도 감수" },
  turnover: { name: "보유 기간", left: "짧게", right: "길게", leftSide: "단기 매매", rightSide: "장기 보유", flip: true },
  concentration: { name: "모아 담기", left: "나눠 담음", right: "모아 담음", leftSide: "나눠 담음", rightSide: "모아 담음" },
  rule_adherence: { name: "규칙 지키기", left: "그때그때", right: "규칙대로", leftSide: "그때그때 바꿈", rightSide: "규칙을 지킴", flip: true },
  information_reliance: { name: "주변 영향", left: "직접 판단", right: "주변 따름", leftSide: "직접 판단", rightSide: "주변을 따름" },
  urgency: { name: "서두름", left: "기다림", right: "서두름", leftSide: "여유 있게 기다림", rightSide: "서둘러 결정" },
  drawdown_reaction: { name: "하락 때 팔기", left: "들고 감", right: "팔고 나옴", leftSide: "떨어져도 들고 감", rightSide: "떨어지면 팖" },
};

export const SUMMARY_SCALE = {
  riskTaking: { name: "위험 감수", left: "적게", right: "많이", leftSide: "원금을 지킴", rightSide: "손실도 감수" },
  sensitivity: { name: "흔들림 민감도", left: "덤덤함", right: "민감함", leftSide: "덤덤함", rightSide: "쉽게 흔들림" },
  horizon: { ...STYLE_AXIS_SCALE.turnover, name: "투자 기간" },
} satisfies Record<string, AxisScale>;

// psych_greed_fear_axis: −1 움츠러듦 ~ +1 들뜸
export const PSYCHOLOGY_SCALE: AxisScale = {
  name: "가격 흐름 분위기",
  left: "움츠러듦",
  right: "들뜸",
  leftSide: "움츠러듦",
  rightSide: "들뜸",
  words: ["많이 움츠러듦", "조금 움츠러듦", "차분함", "조금 들뜸", "많이 들뜸"],
};
