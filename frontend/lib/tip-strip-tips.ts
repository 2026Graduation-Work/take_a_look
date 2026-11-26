// #491의 화면 범위는 샘플 3개로 유지한다. 42개 문구 정본은 beginner-tips.ts에서 관리한다.
export interface TipStripTip {
  readonly id: string;
  readonly headline: string;
  readonly description: string;
  readonly source: string;
}

export const TIP_STRIP_TIPS: readonly TipStripTip[] = [
  {
    id: "recover-30-percent",
    headline: "-30% 손실을 회복하려면 +42.9%가 필요해요.",
    description: "100만 원에서 30%를 잃으면 70만 원이 남아요. 처음 금액으로 돌아가려면 남은 70만 원에서 30만 원이 늘어야 해요.",
    source: "30 ÷ 70 × 100% ≈ 42.9%",
  },
  {
    id: "rise-and-fall-10-percent",
    headline: "10% 오른 뒤 10% 내리면, 처음보다 1% 낮아요.",
    description: "100만 원에서 10% 오르면 110만 원이 돼요. 오른 금액에서 10%가 내리면 11만 원이 줄어 99만 원이 남아요.",
    source: "100 × 1.1 × 0.9 = 99",
  },
  {
    id: "recover-50-percent",
    headline: "50% 손실을 회복하려면 100% 상승이 필요해요.",
    description: "100만 원에서 50%를 잃으면 50만 원이 남아요. 처음 금액으로 돌아가려면 남은 돈이 두 배가 되어야 해요.",
    source: "50 ÷ 50 × 100% = 100%",
  },
];
