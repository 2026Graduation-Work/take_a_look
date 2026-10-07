import type { Contradiction } from "./profiling/style-scoring.ts";

// schema/ v1.1에서 파생된 프론트 타입입니다. 스키마 변경 시 반드시 동기화합니다.
// DB 컬럼 대응은 docs/erd.md.
// chart_output.schema.json: signal_light·rank_percentile·return_band·confidence·horizon_agreement·risk_flags

export type SignalLight =
  | "strong_positive"
  | "positive"
  | "neutral"
  | "negative"
  | "strong_negative";

export type HorizonDirection = "up" | "flat" | "down";

export type HorizonAgreement = "aligned" | "mixed" | "conflict";

export type RiskFlag =
  | "spac"
  | "managed_stock"
  | "low_liquidity"
  | "penny_stock"
  | "high_volatility"
  | "preferred_stock";

export type RiskGrade = 1 | 2 | 3 | 4 | 5; // 5 = 매우 안전, 1 = 매우 위험

// 화면 수치의 출처. 수치 데이터 타입은 이 필드를 필수로 가져 SourceChip으로 표시한다.
// real만 "실데이터"로 표기하고, fixture(손으로 정한 값·합성값)·mock(데모 시드 포함)은 "예시 데이터"다.
export type DataKind = "real" | "fixture" | "mock";
export interface DataProvenance {
  kind: DataKind;
  source: string; // 예: KRX, BigKinds · KR-FinBERT
  asOf?: string; // 데이터 기준일 (YYYY-MM-DD)
}

export interface ReturnBand {
  low: number; // 밴드 하한(%). -1.2 = -1.2%
  high: number; // 밴드 상한(%)
  ciLevel: number; // 신뢰구간 수준 (예: 0.68)
}

export interface HorizonAgreementSet {
  h5: HorizonDirection;
  h10: HorizonDirection;
  h20: HorizonDirection;
  agreement: HorizonAgreement;
}

export interface RecommendedStock {
  code: string;
  name: string;
  market: "KOSPI" | "KOSDAQ";
  riskGrade: RiskGrade;
  signalLight: SignalLight;
  rankPercentile: number; // 0~1, 1이 당일 신호 강도 최상위
  returnBand: ReturnBand;
  hitRate: number; // 0~1, 과거 유사 신호 구간에서 실제로 오른 비율 (confidence.bucket_hit_rate)
  similarCaseCount: number;
  horizonAgreement: HorizonAgreementSet;
  riskFlags: RiskFlag[];
  caution?: string; // 성향 대비 주의 문구. 있을 때만 "위험도 높음" 점과 상세 체크포인트에 표시
  reason?: string; // 목록의 한 줄 이유(모델 근거 1순위 문장). 없으면 기간별 방향 문장으로 대신한다
  provenance: DataProvenance;
}

// 예측 근거 출처 구분
export type ReasonSource = "chart" | "news" | "financial" | "profiling";

export interface PredictionReason {
  title: string; // 예: 최근 20거래일 거래량이 평소의 2.8배
  detail: string; // 기여도 수준 + 보조 설명
  source: ReasonSource;
  sourceLabel: string; // 칩 표기. 예: 차트 지표 (거래량)
}

// 과거 유사 신호 구간의 실현 수익률 분포 히스토그램 빈. [from, to) 단위 %
export interface ReturnBin {
  from: number;
  to: number;
  count: number;
}

export interface StockDetail extends RecommendedStock {
  currentPrice?: number; // 원. 시세 저장 계약이 없으면 미제공
  changePercent?: number; // 전일 대비 %. +1.2 = +1.2%
  asOf: string; // 데이터·예측 기준일 (ISO). 두 날짜는 항상 동일하게 유지
  returnHorizon?: "h5" | "h10" | "h20"; // 수익률 밴드·분포의 거래일 기준
  priceHistory?: number[]; // 최근 60거래일 종가(원). 마지막 원소 = currentPrice
  priceDates?: string[]; // priceHistory와 같은 길이의 거래일(YYYY-MM-DD). 없으면 기준일에서 거꾸로 센다
  priceProvenance?: DataProvenance; // 시세 출처. 예측(provenance)과 다를 수 있다
  realizedReturns?: ReturnBin[]; // similarCaseCount건의 실현 수익률 분포
  volatilityAnnual?: number; // 1년 변동성(일간 로그수익률 표준편차 × √252), 종목 마스터
  volatilityPercentile?: number; // 0~1, 코스피 전 종목 중 위치(1 = 가장 큼)
  riskAsOf?: string; // 위 두 값의 계산 기준일
  reasons: PredictionReason[]; // 기여도 순 Top 3
  aiAdvice?: string; // LLM 생성 설명(수치 번역만, 행동 제안 없음)
}

export type MarketCondition = "stable" | "caution" | "high_volatility";

export interface MarketIndexQuote {
  symbol: string;
  label: string;
  value: number;
  change: number;
  changePercent: number;
}

export interface MarketStatus {
  date: string; // ISO date (YYYY-MM-DD)
  provenance: DataProvenance;
  condition: MarketCondition;
  volatilityScore: number; // 0~100
  volumeScore: number; // 0~100
  indexQuotes: MarketIndexQuote[];
}

export type InvestmentHorizon = "short" | "mid" | "long";

export interface InvestorProfileSummary {
  displayName: string;
  avatarLabel: string;
  profileTypeLabel: string; // BIT 유형명. 예: 추종형 (lib/profiling/bit.ts BIT_LABEL)
  personaLabel: string; // 예: 신중한 장기 투자자
  riskTolerance: number; // 0~100, 위험 감수 = mean(loss_tolerance, concentration)
  sentimentSensitivity: number; // 0~100, 흔들림 민감도 = mean(urgency, drawdown_reaction, information_reliance)
  horizon: InvestmentHorizon;
  surveyedAt: string; // 예: 2026.03
}

export interface PortfolioHolding {
  code: string;
  name: string;
  signalLight: SignalLight;
  quantity: number;
  avgBuyPrice: number;
  priceBasis?: "avg_buy" | "close"; // close = 최신 종가로 센 평가금액, avg_buy = 종가가 없어 매입금액
  priceAsOf?: string; // 평가에 쓴 종가의 기준일(YYYY-MM-DD)
  provenance: DataProvenance;
}

export type ProfileType = "stable" | "aggressive";
export type ActionIntent =
  | "buy_consideration"
  | "sell_consideration"
  | "hold_consideration";

export interface ProfilingHolding {
  ticker: string;
  name: string;
  quantity: number;
  avg_buy_price: number;
}

// schema v1.1 style_axes. 축 id·극성은 lib/profiling/style-questions.json axes가 SSOT.
// ratio: -1 = 주석 왼쪽, +1 = 주석 오른쪽.
export type StyleAxisId =
  | "market_participation" // 시장 수익률 참여 ↔ 내 목표 우선
  | "loss_tolerance" // 원금 보전 ↔ 수익 기회
  | "turnover" // 장기 보유 ↔ 단기 매매
  | "concentration" // 폭넓은 분산 ↔ 소수 집중
  | "rule_adherence" // 사전 규칙 준수 ↔ 상황별 재량 (이름과 달리 +가 규칙에서 멀어지는 쪽)
  | "information_reliance" // 본인 판단 ↔ 시장·타인 추종
  | "urgency" // 여유 ↔ 조급함
  | "drawdown_reaction"; // 하락 시 유지 ↔ 하락 시 이탈

export interface StyleAxis {
  axis_id: StyleAxisId;
  ratio: number; // -1~+1
  confidence: number; // 0~1, 축 내부 응답 일관성 × 응답률
  answered_count: number;
  question_count: number;
}

export interface StyleAxes {
  assessment_mode: "quick" | "detailed";
  axes: StyleAxis[]; // 8축 모두
}

export interface ProfilingOutput {
  user_id: string;
  session_id: string;
  timestamp: string;
  investor_profile: {
    risk_tolerance: number;
    time_horizon_months: number;
    time_horizon_days?: number; // v1.1 optional. turnover 구간표에서 나온 1차 값
    liquidity_need_ratio: number;
    target_return_annual: number;
    investment_experience_years: number;
    profile_type: ProfileType;
  };
  psychological_state: {
    fomo_index: number;
    panic_sell_tendency: number;
    herding_score: number;
    self_confidence: number;
    current_market_anxiety: number;
    overheating_caution: number;
  };
  constraints: {
    avoided_assets: RiskFlag[];
    preferred_sectors: string[];
  };
  portfolio: {
    holdings: ProfilingHolding[];
    watchlist: string[];
  };
  free_text_signal: {
    raw_text: string;
    extracted_signals: Record<string, number>;
    conflict_with_survey: boolean;
  };
  confidence_per_field: Record<string, number>;
  style_axes?: StyleAxes; // v1.1 optional. 있을 때만 schema_version 1.1.0
  contradictions?: Contradiction[]; // v1.1 optional. 축 간 상충 관측치
  context: {
    target_ticker?: string;
    investment_amount_krw: number;
    action_intent: ActionIntent;
    market_regime_hint?: string;
    benchmark_index?: string;
  };
  meta: {
    schema_version: "1.0.0" | "1.1.0";
    source: "profiling_block";
    confidence: number;
  };
}
