// 스키마 enum 값 → 화면 표기(라벨·색) 매핑. 점수 산출이 아닌 순수 표시 계층.
// 표현 제한 원칙: 확률 단정 대신 "과거 유사 신호 구간 상위 N%"류 표현만 사용한다.

import { SIGNAL_WORD, type SignalWord } from "./copy-glossary.ts";
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
    label: `강한 ${SIGNAL_WORD.up}`,
    ink: "var(--color-sig-sp)",
    tint: "var(--color-sig-sp-tint)",
    solid: "var(--color-sig-sp-solid)",
  },
  positive: {
    label: SIGNAL_WORD.up,
    ink: "var(--color-sig-p)",
    tint: "var(--color-sig-p-tint)",
    solid: "var(--color-sig-p-solid)",
  },
  neutral: {
    label: SIGNAL_WORD.flat,
    ink: "var(--color-sig-n)",
    tint: "var(--color-sig-n-tint)",
    solid: "var(--color-sig-n-solid)",
  },
  negative: {
    label: SIGNAL_WORD.down,
    ink: "var(--color-sig-ng)",
    tint: "var(--color-sig-ng-tint)",
    solid: "var(--color-sig-ng-solid)",
  },
  strong_negative: {
    label: `강한 ${SIGNAL_WORD.down}`,
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
// 한국 날짜 키 "2026-10-06". 월·연 경계와 "오늘" 판정을 한국 날짜로 나눈다.
export const kstDay = (timestamp: number) => new Date(timestamp + 9 * 3_600_000).toISOString().slice(0, 10);

export function formatKstDateTime(iso: string) {
  const time = iso.includes("T") ? Date.parse(iso) : NaN;
  return (Number.isNaN(time) ? iso : KST_DATE_TIME.format(time)).replaceAll("-", ".");
}

// 부호 붙은 퍼센트 한 자리. signedPercent는 비율(0.12 → "+12.0%"), formatSignedPercent는 이미 % 단위인 값(1.2 → "+1.2%").
export const signedPercent = (ratio: number) => formatSignedPercent(ratio * 100);
// 표시 자릿수에서 0이 되는 값은 방향 없음. 계산에 쓰는 원본 값은 바꾸지 않는다.
export function changeMeta(value: number, precision?: number) {
  const displayed = precision === undefined ? value : Number(value.toFixed(precision));
  return displayed > 0
    ? { color: "var(--color-up)", arrow: "▲" }
    : displayed < 0
      ? { color: "var(--color-down)", arrow: "▼" }
      : { color: "var(--color-body)", arrow: "" };
}

export function formatSignedPercent(value: number, precision = 1) {
  const displayed = Number(value.toFixed(precision));
  return `${displayed > 0 ? "+" : ""}${displayed.toFixed(precision)}%`;
}

// 순매수 수량(주). 만 주 단위로 줄여 읽기 쉽게: +5,276,406 → +527.6만 주.
// 1만 주 미만은 반올림하면 "-0만 주"가 되므로 말로 쓴다(페르소나 워크스루 2026-10).
export function formatShares(value: number): string {
  if (value === 0) return "변동 없음";
  if (Math.abs(value) < 10_000) return `1만 주 미만 ${value > 0 ? "순매수" : "순매도"}`;
  return `${value > 0 ? "+" : "-"}${(Math.abs(value) / 10_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만 주`;
}

// 모델 근거의 크기 말(규칙 코드). 기여값은 선택한 분류 점수를 올리고 내린 정도라 "결과의 몇 %"로 쓰지 않는다.
// 크기 = |기여값| ÷ 전체 피처 |기여값| 합(payload.inference.contribution_abs_sum). 0.1 이상 "크게", 미만 "조금".
// 기준: 운영 배치(2026-10-13, 913종목 H20)에서 1위 항목의 중앙값이 약 0.13, 2~3위 항목은 대부분 0.1 미만.
// 합이 없으면(옛 스냅샷) 크기를 알 수 없어 방향만 쓴다.
export const CONTRIBUTION_LARGE = 0.1;
// target은 기여값이 가리키는 분류. "하락 신호를 높임"이 가격 상승으로 읽히지 않게 늘 붙인다.
export function contributionWord(contribution: number, target: SignalWord, total?: number): string {
  if (contribution === 0) return `${target} 신호를 바꾸지 않음`;
  const verb = contribution > 0 ? "높임" : "낮춤";
  if (!total) return `${target} 신호를 ${verb}`;
  return `${target} 신호를 ${Math.abs(contribution) / total >= CONTRIBUTION_LARGE ? "크게" : "조금"} ${verb}`;
}
