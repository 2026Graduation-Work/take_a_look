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

// 전일 대비 등락을 원과 %로 함께: "+1,200원 (+1.8%)". 원은 반올림, 0원이면 부호 없음
export function formatWonChange(won: number, percent: number): string {
  const rounded = Math.round(won);
  return `${rounded > 0 ? "+" : rounded < 0 ? "-" : ""}${Math.abs(rounded).toLocaleString("ko-KR")}원 (${formatSignedPercent(percent)})`;
}

// 오늘 종가에 수익률(%)을 적용한 가격. 유효숫자 3자리로 반올림해 '약'을 붙인다(−5.5% → 약 94,500원).
export function bandPrice(close: number, percent: number): string {
  const price = close * (1 + percent / 100);
  const unit = 10 ** Math.max(0, Math.floor(Math.log10(Math.max(Math.abs(price), 1))) - 2);
  return `약 ${(Math.round(price / unit) * unit).toLocaleString("ko-KR")}원`;
}

// 순매수 수량(주). 만 주 단위로 줄여 읽기 쉽게: +5,276,406 → +527.6만 주.
// 1만 주 미만은 반올림하면 "-0만 주"가 되므로 말로 쓴다(페르소나 워크스루 2026-10).
export function formatShares(value: number): string {
  if (value === 0) return "변동 없음";
  if (Math.abs(value) < 10_000) return `1만 주 미만 ${value > 0 ? "순매수" : "순매도"}`;
  return `${value > 0 ? "+" : "-"}${(Math.abs(value) / 10_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만 주`;
}

// 대상 클래스의 전체 피처 절댓값 합을 분모로 쓴다. 기준값은 서버에서 제외한다.
export function contributionShare(contribution: number, total?: number): number | undefined {
  if (!Number.isFinite(contribution) || total === undefined || !Number.isFinite(total) || total <= 0 || Math.abs(contribution) > total + 1e-8) return undefined;
  return Math.min(1, Math.abs(contribution) / total);
}

export function contributionWord(contribution: number, target: SignalWord, total?: number): string {
  const direction = contribution === 0 ? `${target} 점수를 바꾸지 않았어요.` : `${target} 점수를 ${contribution > 0 ? "높였어요" : "낮췄어요"}.`;
  const share = contributionShare(contribution, total);
  if (share === undefined) return direction;
  const percent = share * 100;
  return `${direction} 영향 비중 ${percent > 0 && percent < 0.1 ? "0.1% 미만" : `${percent.toFixed(1)}%`}`;
}

export function contributionValue(value: number): string {
  if (value === 0) return "0";
  return `${value > 0 ? "+" : ""}${Math.abs(value) < 0.00005 ? value.toExponential(3) : value.toFixed(4)}`;
}
