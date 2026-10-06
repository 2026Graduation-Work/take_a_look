// 스키마 enum 값 → 화면 표기(라벨·색) 매핑. 점수 산출이 아닌 순수 표시 계층.
// 표현 제한 원칙: 확률 단정 대신 "과거 유사 신호 구간 상위 N%"류 표현만 사용한다.

import type {
  HorizonDirection,
  MarketCondition,
  RiskFlag,
  SignalLight,
} from "./types";

export interface SignalMeta {
  label: string;
  ink: string; // 글자·마크 색 (흰 배경 위)
  tint: string; // 아주 옅은 배경
  solid: string; // 흰 글자를 얹는 면 (히트맵 타일)
}

// 색은 globals.css @theme 토큰만 참조한다. 여기서 새 hex를 만들지 않는다.
export const SIGNAL_META: Record<SignalLight, SignalMeta> = {
  strong_positive: {
    label: "강한 긍정",
    ink: "var(--color-sig-sp)",
    tint: "var(--color-sig-sp-tint)",
    solid: "var(--color-sig-sp-solid)",
  },
  positive: {
    label: "긍정",
    ink: "var(--color-sig-p)",
    tint: "var(--color-sig-p-tint)",
    solid: "var(--color-sig-p-solid)",
  },
  neutral: {
    label: "중립",
    ink: "var(--color-sig-n)",
    tint: "var(--color-sig-n-tint)",
    solid: "var(--color-sig-n-solid)",
  },
  negative: {
    label: "부정",
    ink: "var(--color-sig-ng)",
    tint: "var(--color-sig-ng-tint)",
    solid: "var(--color-sig-ng-solid)",
  },
  strong_negative: {
    label: "강한 부정",
    ink: "var(--color-sig-sn)",
    tint: "var(--color-sig-sn-tint)",
    solid: "var(--color-sig-sn-solid)",
  },
};

// risk_flags == profiling avoided_assets 태그 체계 (schema enum과 1:1)
export const RISK_FLAG_LABEL: Record<RiskFlag, string> = {
  spac: "SPAC",
  managed_stock: "관리종목",
  low_liquidity: "저유동성",
  penny_stock: "저가주",
  high_volatility: "고변동성",
  preferred_stock: "우선주",
};

export const HORIZON_META: Record<HorizonDirection, { arrow: string; ink: string }> = {
  up: { arrow: "↑", ink: "var(--color-sig-p)" },
  flat: { arrow: "→", ink: "var(--color-muted)" },
  down: { arrow: "↓", ink: "var(--color-sig-ng)" },
};

export const MARKET_CONDITION_META: Record<
  MarketCondition,
  { label: string; ink: string; comment: string }
> = {
  stable: {
    label: "안정",
    ink: "var(--color-sig-p)",
    comment: "시장이 평소 범위 안에서 움직이고 있어요",
  },
  caution: {
    label: "주의",
    ink: "var(--color-sig-n)",
    comment: "시장 흔들림이 평소보다 큰 편이에요",
  },
  high_volatility: {
    label: "경계",
    ink: "var(--color-sig-ng)",
    comment: "시장 흔들림이 평소보다 크게 커진 구간이에요",
  },
};

// 시각이 붙은 ISO(UTC 등)를 한국 시각 "2026.10.06 12:53"으로. 날짜만 있으면 그대로 점 표기.
const KST_DATE_TIME = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});
export function formatKstDateTime(iso: string) {
  const time = iso.includes("T") ? Date.parse(iso) : NaN;
  return (Number.isNaN(time) ? iso : KST_DATE_TIME.format(time)).replaceAll("-", ".");
}
