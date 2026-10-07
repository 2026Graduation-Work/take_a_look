import { AVOIDED_ASSET_LABELS, summaryFromStyleAxes } from "./profiling-rules";
import type { LatestCloses } from "./latest-closes.ts";
import { costBasis } from "./holdings-rules.ts";
import type {
  DataProvenance,
  HorizonAgreement,
  HorizonDirection,
  InvestorProfileSummary,
  PortfolioHolding,
  PredictionReason,
  RecommendedStock,
  RiskFlag,
  RiskGrade,
  SignalLight,
  StockDetail,
  StyleAxes,
} from "./types";

export interface UserRow {
  id: string;
  display_name: string;
  avatar_label: string;
}

export interface IpsProfileRow {
  user_id: string;
  surveyed_at: string;
  profile_type: "stable" | "aggressive";
  max_risk_tier: number;
  risk_score: number;
  fomo_score: number;
  horizon_score: number;
}

export interface AvoidedAssetRow {
  asset_type: string;
}

export interface StockRow {
  code: string;
  name: string;
  market: "KOSPI" | "KOSDAQ";
  risk_grade: number;
  risk_flags: string[];
  volatility_annual?: number | null;
  volatility_percentile?: number | null;
  risk_as_of?: string | null;
}

export interface PredictionRow {
  stock_code: string;
  prediction_date: string;
  signal_light: string;
  rank_percentile: number;
  return_low: number;
  return_high: number;
  return_ci_level: number | null;
  bucket_hit_rate: number;
  similar_case_count: number | null;
  horizon_h5: string | null;
  horizon_h10: string | null;
  horizon_h20: string | null;
  horizon_agreement: string | null;
  caution: string | null;
  display_order: number;
}

export interface PredictionDetailRow extends PredictionRow {
  id: string;
  data_asof: string | null;
  horizon: "h5" | "h10" | "h20" | null;
}

export interface PredictionFeatureRow {
  feature: string;
  label_ko: string;
  contribution: number;
  display_order: number;
}

export interface PortfolioHoldingRow {
  stock_code: string;
  quantity: number;
  avg_buy_price: number | null; // 0004부터 비워 둘 수 있음
  display_order: number;
}

export interface ExcludedStock {
  name: string;
  code: string;
  reason: string;
}

const RISK_FLAGS: RiskFlag[] = [
  "spac",
  "managed_stock",
  "low_liquidity",
  "penny_stock",
  "high_volatility",
  "preferred_stock",
];

const SIGNAL_LIGHTS: SignalLight[] = [
  "strong_positive",
  "positive",
  "neutral",
  "negative",
  "strong_negative",
];

const HORIZON_DIRECTIONS: HorizonDirection[] = ["up", "flat", "down"];
const HORIZON_AGREEMENTS: HorizonAgreement[] = ["aligned", "mixed", "conflict"];
const NEWS_FEATURE_TOKENS = ["news", "sentiment", "finbert", "headline"];
const PROFILING_FEATURE_TOKENS = ["psychology", "psychological", "profile", "fomo"];
const FINANCIAL_FEATURE_TOKENS = [
  "dart",
  "financial",
  "fundamental",
  "revenue",
  "profit",
  "earning",
  "per",
  "pbr",
  "roe",
  "debt",
];

// Supabase 테이블은 지금 supabase/seed.sql 데모 시드로만 채워진다(백엔드 적재 경로 없음).
// 실데이터 적재가 생기면 행에 출처 컬럼을 두고 여기서 읽는다. 그 전까지는 예시로 표시한다.
const SUPABASE_DEMO: DataProvenance = { kind: "mock", source: "데모 시드" };

export function mapRecommendedStock(
  prediction: PredictionRow,
  stock: StockRow,
): RecommendedStock {
  return {
    code: stock.code,
    name: stock.name,
    market: stock.market,
    riskGrade: toRiskGrade(stock.risk_grade),
    signalLight: includes(SIGNAL_LIGHTS, prediction.signal_light)
      ? prediction.signal_light
      : "neutral",
    rankPercentile: prediction.rank_percentile,
    returnBand: {
      low: prediction.return_low,
      high: prediction.return_high,
      ciLevel: prediction.return_ci_level ?? 0.68,
    },
    hitRate: prediction.bucket_hit_rate,
    similarCaseCount: prediction.similar_case_count ?? 0,
    horizonAgreement: {
      h5: toHorizonDirection(prediction.horizon_h5),
      h10: toHorizonDirection(prediction.horizon_h10),
      h20: toHorizonDirection(prediction.horizon_h20),
      agreement: includes(HORIZON_AGREEMENTS, prediction.horizon_agreement)
        ? prediction.horizon_agreement
        : "mixed",
    },
    riskFlags: toRiskFlags(stock.risk_flags),
    ...(prediction.caution ? { caution: prediction.caution } : {}),
    provenance: { ...SUPABASE_DEMO, asOf: prediction.prediction_date },
  };
}

export function mapStockDetail(
  prediction: PredictionDetailRow,
  stock: StockRow,
  featureRows: PredictionFeatureRow[],
): StockDetail {
  return {
    ...mapRecommendedStock(prediction, stock),
    asOf: prediction.data_asof ?? prediction.prediction_date,
    ...(prediction.horizon ? { returnHorizon: prediction.horizon } : {}),
    reasons: mapPredictionReasons(featureRows),
    ...masterVolatility(stock),
  };
}

// 종목 마스터의 1년 변동성·백분위(0014). 없으면 넣지 않는다.
export function masterVolatility(stock: StockRow): Pick<StockDetail, "volatilityAnnual" | "volatilityPercentile" | "riskAsOf"> {
  return stock.volatility_annual != null && stock.volatility_percentile != null
    ? { volatilityAnnual: stock.volatility_annual, volatilityPercentile: stock.volatility_percentile, riskAsOf: stock.risk_as_of ?? undefined }
    : {};
}

export function mapPredictionReasons(
  rows: PredictionFeatureRow[],
): PredictionReason[] {
  return [...rows]
    .sort(
      (left, right) =>
        left.display_order - right.display_order ||
        Math.abs(right.contribution) - Math.abs(left.contribution) ||
        left.feature.localeCompare(right.feature),
    )
    .slice(0, 3)
    .map((row) => {
      const source = featureSource(row.feature);
      const direction = row.contribution >= 0 ? "신호를 높이는 기여" : "신호를 낮추는 기여";
      const signedValue = `${row.contribution > 0 ? "+" : ""}${row.contribution.toFixed(4)}`;
      return {
        title: row.label_ko,
        detail: `${direction} · 모델 기여값 ${signedValue}`,
        source: source.type,
        sourceLabel: source.label,
      };
    });
}

export function mapProfileSummary(
  user: UserRow,
  profile: IpsProfileRow,
  styleAxes: StyleAxes | null = null,
): InvestorProfileSummary {
  return summaryFromStyleAxes(styleAxes, {
    displayName: user.display_name,
    avatarLabel: user.avatar_label,
    surveyedAt: profile.surveyed_at.slice(0, 7).replace("-", "."),
  });
}

export function mapPortfolioHolding(
  holding: PortfolioHoldingRow,
  stock: StockRow,
  prediction?: PredictionRow,
  closes: LatestCloses = new Map(),
): PortfolioHolding {
  return {
    code: holding.stock_code,
    name: stock.name,
    signalLight:
      prediction && includes(SIGNAL_LIGHTS, prediction.signal_light)
        ? prediction.signal_light
        : "neutral",
    quantity: holding.quantity,
    ...weightPrice(holding, closes),
    provenance: SUPABASE_DEMO,
  };
}

export function mapAvoidedAssetLabels(rows: AvoidedAssetRow[]): string[] {
  const selected = new Set(rows.map(({ asset_type }) => asset_type));
  return RISK_FLAGS.filter((flag) => selected.has(flag)).map(
    (flag) => AVOIDED_ASSET_LABELS[flag],
  );
}

export function mapExcludedStocks(
  stocks: StockRow[],
  avoidedRows: AvoidedAssetRow[],
): ExcludedStock[] {
  const avoided = new Set(
    avoidedRows
      .map(({ asset_type }) => asset_type)
      .filter((flag): flag is RiskFlag => includes(RISK_FLAGS, flag)),
  );

  return stocks.flatMap((stock) => {
    const reason = RISK_FLAGS.find(
      (flag) => avoided.has(flag) && stock.risk_flags.includes(flag),
    );
    return reason
      ? [{ name: stock.name, code: stock.code, reason: AVOIDED_ASSET_LABELS[reason] }]
      : [];
  });
}

export function toRiskFlags(values: string[]): RiskFlag[] {
  return values.filter((value): value is RiskFlag => includes(RISK_FLAGS, value));
}

export function toRiskGrade(value: number): RiskGrade {
  if (![1, 2, 3, 4, 5].includes(value)) {
    throw new Error(`지원하지 않는 위험 등급입니다: ${value}`);
  }
  return value as RiskGrade;
}

function toHorizonDirection(value: string | null): HorizonDirection {
  return includes(HORIZON_DIRECTIONS, value) ? value : "flat";
}

function featureSource(feature: string): {
  type: PredictionReason["source"];
  label: string;
} {
  const tokens = new Set(feature.toLowerCase().split(/[^a-z0-9]+/));
  if (NEWS_FEATURE_TOKENS.some((token) => tokens.has(token))) {
    return { type: "news", label: "뉴스 감성 분석" };
  }
  if (PROFILING_FEATURE_TOKENS.some((token) => tokens.has(token))) {
    return { type: "profiling", label: "심리 지수" };
  }
  if (FINANCIAL_FEATURE_TOKENS.some((token) => tokens.has(token))) {
    return { type: "financial", label: "재무 지표" };
  }
  return { type: "chart", label: "차트 지표" };
}

function includes<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === "string" && values.includes(value as T);
}

// 최신 종가가 있으면 평가금액, 없으면 매입금액으로 비중을 센다.
function weightPrice(holding: PortfolioHoldingRow, closes: LatestCloses): Pick<PortfolioHolding, "avgBuyPrice" | "priceBasis" | "priceAsOf"> {
  const latest = closes.get(holding.stock_code);
  const { price, basis } = costBasis(holding.avg_buy_price, latest?.close);
  return { avgBuyPrice: price, priceBasis: basis, ...(latest ? { priceAsOf: latest.asOf } : {}) };
}
