import { SIGNAL_WORD, type SignalWord } from "./copy-glossary.ts";
import type {
  HorizonDirection,
  MarketCondition,
  RiskFlag,
  SignalLight,
} from "./types";

export interface SignalMeta {
  label: string;
  ink: string;
  tint: string;
  solid: string;
}

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

const KST_DATE_TIME = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});
export const kstDay = (timestamp: number) => new Date(timestamp + 9 * 3_600_000).toISOString().slice(0, 10);

export function formatKstDateTime(iso: string) {
  const time = iso.includes("T") ? Date.parse(iso) : NaN;
  return (Number.isNaN(time) ? iso : KST_DATE_TIME.format(time)).replaceAll("-", ".");
}

// signedPercent는 비율(0.12 → "+12.0%"), formatSignedPercent는 이미 % 단위인 값(1.2 → "+1.2%").
export const signedPercent = (ratio: number) => formatSignedPercent(ratio * 100);
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

export function formatWonChange(won: number, percent: number): string {
  const rounded = Math.round(won);
  return `${rounded > 0 ? "+" : rounded < 0 ? "-" : ""}${Math.abs(rounded).toLocaleString("ko-KR")}원 (${formatSignedPercent(percent)})`;
}

export function bandPrice(close: number, percent: number): string {
  const price = close * (1 + percent / 100);
  const unit = 10 ** Math.max(0, Math.floor(Math.log10(Math.max(Math.abs(price), 1))) - 2);
  return `약 ${(Math.round(price / unit) * unit).toLocaleString("ko-KR")}원`;
}

export function formatShares(value: number): string {
  if (value === 0) return "변동 없음";
  if (Math.abs(value) < 10_000) return `1만 주 미만 ${value > 0 ? "순매수" : "순매도"}`;
  return `${value > 0 ? "+" : "-"}${(Math.abs(value) / 10_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만 주`;
}

export function contributionShare(contribution: number, total?: number): number | undefined {
  if (!Number.isFinite(contribution) || total === undefined || !Number.isFinite(total) || total <= 0 || Math.abs(contribution) > total + 1e-8) return undefined;
  return Math.min(1, Math.abs(contribution) / total);
}

export function contributionWord(contribution: number, target: SignalWord, total?: number): string {
  if (contribution === 0) return `${target} 점수를 바꾸지 않았어요.`;
  const share = contributionShare(contribution, total);
  const size = share === undefined ? "" : share >= 0.1 ? "크게 " : "조금 ";
  return `${target} 점수를 ${size}${contribution > 0 ? "높였어요" : "낮췄어요"}.`;
}

export function contributionPercent(contribution: number, total?: number): string {
  const share = contributionShare(contribution, total);
  if (share === undefined) return "미제공";
  const percent = share * 100;
  if (share === 0) return "0%";
  const sign = contribution > 0 ? "+" : "−";
  return percent < 0.1 ? `${sign}(0.1% 미만)` : `${sign}${Number(percent.toFixed(1))}%`;
}
