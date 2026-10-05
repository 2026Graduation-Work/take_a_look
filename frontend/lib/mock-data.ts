// 데모용 목데이터. 추후 Supabase 조회로 교체하되 형태는 schema/ 계약을 따른다.
// (수치는 디자인 프로토타입 "Main Dashboard"/"Stock Detail" 기준.
//  데이터 기준일과 예측 생성일은 하나의 날짜로 통일한다. 팀 리뷰 결정)

import { summaryFromStyleAxes } from "./profiling-rules.ts";
import { MARKET_SNAPSHOT, SNAPSHOT_AS_OF, snapshotPrice } from "./providers/demo-snapshot.ts";
import type {
  DataProvenance,
  InvestorProfileSummary,
  MarketStatus,
  PortfolioHolding,
  RecommendedStock,
  StockDetail,
  StyleAxes,
} from "./types";

// 이 파일의 수치는 모두 손으로 정한 예시다. 화면에는 "예시 데이터"로 표시된다.
const DEMO: DataProvenance = { kind: "mock", source: "데모 데이터" };

// 시장 브리핑은 실데이터 스냅샷(KRX 지수, FinanceDataReader 캐시). 산식: scripts/build_demo_snapshot.py
export const marketStatus: MarketStatus = MARKET_SNAPSHOT;

const samsungElectronics: RecommendedStock = {
  code: "005930",
  name: "삼성전자",
  market: "KOSPI",
  riskGrade: 4,
  signalLight: "positive",
  rankPercentile: 0.82,
  returnBand: { low: -0.8, high: 4.2, ciLevel: 0.68 },
  hitRate: 0.61,
  similarCaseCount: 128,
  horizonAgreement: { h5: "up", h10: "up", h20: "up", agreement: "aligned" },
  riskFlags: [],
  reason: "20일 이동평균이 60일 이동평균을 상향 돌파", // 상세 모델 근거 1순위와 같은 문장
  provenance: DEMO,
};

const hyundaiMotor: RecommendedStock = {
  code: "005380",
  name: "현대차",
  market: "KOSPI",
  riskGrade: 5,
  signalLight: "strong_positive",
  rankPercentile: 0.95,
  returnBand: { low: 0.6, high: 7.2, ciLevel: 0.68 },
  hitRate: 0.66,
  similarCaseCount: 52,
  horizonAgreement: { h5: "up", h10: "up", h20: "up", agreement: "aligned" },
  riskFlags: [],
  reason: "60일 모멘텀이 전체 종목 상위 5%", // 상세 모델 근거 1순위와 같은 문장
  provenance: DEMO,
};

const celltrion: RecommendedStock = {
  code: "068270",
  name: "셀트리온",
  market: "KOSDAQ",
  riskGrade: 2,
  signalLight: "neutral",
  rankPercentile: 0.59,
  returnBand: { low: -2.0, high: 7.4, ciLevel: 0.68 },
  hitRate: 0.57,
  similarCaseCount: 34,
  horizonAgreement: { h5: "up", h10: "up", h20: "flat", agreement: "mixed" },
  riskFlags: ["high_volatility"],
  caution:
    "위험 2등급 종목으로, 성향 기준 허용 범위(4·5등급) 밖에 있습니다.",
  reason: "최근 20거래일 거래량이 평소의 2.8배", // 상세 모델 근거 1순위와 같은 문장
  provenance: DEMO,
};

// supabase/seed.sql 035720 예측 행과 같은 값
const kakao: RecommendedStock = {
  code: "035720",
  name: "카카오",
  market: "KOSPI",
  riskGrade: 3,
  signalLight: "negative",
  rankPercentile: 0.28,
  returnBand: { low: -5.1, high: 1.2, ciLevel: 0.68 },
  hitRate: 0.46,
  similarCaseCount: 61,
  horizonAgreement: { h5: "down", h10: "down", h20: "flat", agreement: "mixed" },
  riskFlags: [],
  caution:
    "위험 3등급 종목으로, 성향 기준 허용 범위(4·5등급) 밖에 있습니다.",
  provenance: DEMO,
};

// 추천 리스트. 위험등급은 거르지 않는다 — 성향에서 자동 파생된 max_risk_tier는
// 소프트 틸트라 주의 문구로만 쓴다 (AGENTS.md "명시 규칙만 하드 제약").
export const recommendedStocks: RecommendedStock[] = [samsungElectronics, hyundaiMotor];

// 보유 중이지만 추천 목록에 없는 종목. 보유 종목은 모두 추천 또는 이 알림 중 한 곳에 보인다.
export const holdingAlerts: RecommendedStock[] = [celltrion, kakao];

// 회피 설정(avoided_assets)으로 추천에서 제외된 종목 안내.
// 화이트박스 원칙: 어떤 종목이 왜 빠졌는지 펼쳐서 확인 가능해야 한다.
export const avoidanceNotice = {
  avoidedLabels: ["SPAC", "관리종목"],
  excludedStocks: [{ name: "미래에셋비전스팩3호", code: "418250", reason: "SPAC" }],
};

// 김민지 8축(schema v1.1). supabase/seed.sql과 같은 값이다.
// 4축은 기존 v1.0 필드를 schema style_axes 축약 규칙의 역으로 구했다(ratio = 2 × v1.0값 − 1):
//   loss_tolerance ← risk_tolerance 0.35, urgency ← fomo_index 0.72,
//   drawdown_reaction ← panic_sell_tendency 0.65, information_reliance ← herding_score 0.58.
// turnover -0.25는 time_horizon_months 48에 가장 가까운 구간(1800일)이다.
// market_participation·concentration·rule_adherence는 원천 필드가 없어 정한 값이고
// confidence는 meta.confidence(0.81)를 쓴다. 나머지 confidence는 confidence_per_field의 대응 값.
export const investorStyleAxes: StyleAxes = {
  assessment_mode: "quick",
  axes: [
    { axis_id: "market_participation", ratio: -0.2, confidence: 0.81, answered_count: 3, question_count: 3 },
    { axis_id: "loss_tolerance", ratio: -0.3, confidence: 0.92, answered_count: 3, question_count: 3 },
    { axis_id: "turnover", ratio: -0.25, confidence: 0.95, answered_count: 3, question_count: 3 },
    { axis_id: "concentration", ratio: -0.4, confidence: 0.81, answered_count: 3, question_count: 3 },
    { axis_id: "rule_adherence", ratio: 0.2, confidence: 0.81, answered_count: 3, question_count: 3 },
    { axis_id: "information_reliance", ratio: 0.16, confidence: 0.85, answered_count: 3, question_count: 3 },
    { axis_id: "urgency", ratio: 0.44, confidence: 0.78, answered_count: 3, question_count: 3 },
    { axis_id: "drawdown_reaction", ratio: 0.3, confidence: 0.7, answered_count: 3, question_count: 3 },
  ],
};

// 김민지 성향 카드. 3축과 유형명은 위 8축에서 계산한다(대시보드·상세·설문 결과와 같은 규칙).
export const investorProfile: InvestorProfileSummary = summaryFromStyleAxes(investorStyleAxes, {
  displayName: "김민지",
  avatarLabel: "민",
  surveyedAt: "2026.03",
});

// supabase/seed.sql portfolio_holdings와 같은 종목·수량·평단 (N08 보유 비중 넛지가 의존)
export const portfolioHoldings: PortfolioHolding[] = [
  {
    code: "005930",
    name: "삼성전자",
    signalLight: "positive",
    quantity: 15,
    avgBuyPrice: 71_200,
    provenance: DEMO,
  },
  {
    code: "035720",
    name: "카카오",
    signalLight: "negative",
    quantity: 8,
    avgBuyPrice: 48_500,
    provenance: DEMO,
  },
  {
    code: "068270",
    name: "셀트리온",
    signalLight: "neutral",
    quantity: 3,
    avgBuyPrice: 182_000,
    provenance: DEMO,
  },
  {
    code: "005380",
    name: "현대차",
    signalLight: "strong_positive",
    quantity: 5,
    avgBuyPrice: 235_000,
    provenance: DEMO,
  },
];

// 시세는 실데이터 스냅샷(네이버 금융 수정주가, 기준일 2025-12-30). 예측 수치(신호·밴드·분포·근거)는 예시다.
const realPrice = (code: string) => ({ asOf: SNAPSHOT_AS_OF, ...snapshotPrice(code) });

// 종목 상세. 진입 동선: 대시보드 카드 "근거 보기" → /stocks/[code]
export const stockDetails: Record<string, StockDetail> = {
  [celltrion.code]: {
    ...celltrion,
    ...realPrice(celltrion.code),
    realizedReturns: [
      { from: -6, to: -4, count: 2 },
      { from: -4, to: -2, count: 3 },
      { from: -2, to: 0, count: 6 },
      { from: 0, to: 2, count: 7 },
      { from: 2, to: 4, count: 6 },
      { from: 4, to: 6, count: 4 },
      { from: 6, to: 8, count: 3 },
      { from: 8, to: 10, count: 2 },
      { from: 10, to: 12, count: 1 },
    ],
    reasons: [
      {
        title: "최근 20거래일 거래량이 평소의 2.8배",
        detail: "기여도 상 · 매집 또는 이슈성 거래 가능성 모두 포함",
        source: "chart",
        sourceLabel: "차트 지표 (거래량)",
      },
      {
        title: "60일 모멘텀이 전체 종목 상위 15%",
        detail: "기여도 중 · 중기 추세는 우상향 유지",
        source: "chart",
        sourceLabel: "차트 지표 (모멘텀)",
      },
      {
        title: "최근 2주 뉴스 감성은 중립~약긍정",
        detail: "기여도 중 · 바이오시밀러 수주 기사 대비 부정 기사 적음",
        source: "news",
        sourceLabel: "뉴스 감성 분석",
      },
    ],
    aiAdvice:
      "셀트리온의 모델 신호는 중립으로, 방향이 뚜렷하지 않은 구간이에요. 과거 비슷한 신호 34건의 2주 뒤 수익률은 -2.0%에서 +7.4% 사이로 넓게 퍼져 있었고, 실제로 오른 경우는 57%로 한쪽으로 기울지 않았어요. 김민지님은 위험 감수(33)가 낮고 흔들림 민감도(65)가 높은 편이라, 가격 흔들림이 큰 이 종목의 오르내림이 부담이 될 수 있어요.",
  },
  [samsungElectronics.code]: {
    ...samsungElectronics,
    ...realPrice(samsungElectronics.code),
    realizedReturns: [
      { from: -4, to: -3, count: 3 },
      { from: -3, to: -2, count: 6 },
      { from: -2, to: -1, count: 10 },
      { from: -1, to: 0, count: 16 },
      { from: 0, to: 1, count: 22 },
      { from: 1, to: 2, count: 24 },
      { from: 2, to: 3, count: 19 },
      { from: 3, to: 4, count: 13 },
      { from: 4, to: 5, count: 8 },
      { from: 5, to: 6, count: 4 },
      { from: 6, to: 7, count: 3 },
    ],
    reasons: [
      {
        title: "20일 이동평균이 60일 이동평균을 상향 돌파",
        detail: "기여도 상 · 교차 이후 8거래일째 추세 유지",
        source: "chart",
        sourceLabel: "차트 지표 (추세)",
      },
      {
        title: "최근 2주 반도체 업황 뉴스 감성 긍정 비율 71%",
        detail: "기여도 중 · HBM 공급 계약 기사 중심",
        source: "news",
        sourceLabel: "뉴스 감성 분석",
      },
      {
        title: "직전 분기 영업이익이 시장 예상치를 9% 상회",
        detail: "기여도 중 · 실적 발표 이후 추정치 상향 반영",
        source: "financial",
        sourceLabel: "재무 지표 (실적)",
      },
    ],
    aiAdvice:
      "삼성전자의 모델 신호는 긍정이고, 1주·2주·4주 뒤 방향이 모두 오르는 쪽이에요. 과거 비슷한 신호 128건의 2주 뒤 수익률은 -0.8%에서 +4.2% 사이였고, 실제로 오른 경우는 61%였어요. 위험도는 낮음으로 김민지님이 답한 위험 감수(33) 범위 안에 있고, 범위가 좁은 편이라 흔들림 민감도(65)가 높은 김민지님에게 오르내림 부담이 덜한 편이에요.",
  },
  [hyundaiMotor.code]: {
    ...hyundaiMotor,
    ...realPrice(hyundaiMotor.code),
    realizedReturns: [
      { from: -3, to: -2, count: 1 },
      { from: -2, to: -1, count: 2 },
      { from: -1, to: 0, count: 3 },
      { from: 0, to: 1, count: 5 },
      { from: 1, to: 2, count: 7 },
      { from: 2, to: 3, count: 8 },
      { from: 3, to: 4, count: 7 },
      { from: 4, to: 5, count: 6 },
      { from: 5, to: 6, count: 4 },
      { from: 6, to: 7, count: 3 },
      { from: 7, to: 8, count: 2 },
      { from: 8, to: 9, count: 2 },
      { from: 9, to: 10, count: 2 },
    ],
    reasons: [
      {
        title: "60일 모멘텀이 전체 종목 상위 5%",
        detail: "기여도 상 · 최근 3개월 상대강도 지속 상승",
        source: "chart",
        sourceLabel: "차트 지표 (모멘텀)",
      },
      {
        title: "최근 20거래일 거래량이 평소의 1.9배",
        detail: "기여도 중 · 가격 상승과 같은 방향의 거래 증가",
        source: "chart",
        sourceLabel: "차트 지표 (거래량)",
      },
      {
        title: "북미 판매 실적 관련 뉴스 감성 긍정 우위",
        detail: "기여도 중 · 부정 기사 비중이 낮은 상태 유지",
        source: "news",
        sourceLabel: "뉴스 감성 분석",
      },
    ],
    aiAdvice:
      "현대차의 모델 신호는 강한 긍정으로, 오늘 분석한 종목 중 상위 5%예요. 과거 비슷한 신호 52건의 2주 뒤 수익률은 +0.6%에서 +7.2% 사이로 아래쪽 끝도 0% 위였고, 실제로 오른 경우는 66%였어요. 다만 비슷한 사례가 52건으로 많지 않아, 사례가 더 많은 신호보다 범위를 덜 믿을 만해요. 위험도는 낮음이에요.",
  },
};

// 카카오는 예측 근거·분포 예시가 없다. 시세만 실데이터로 두고 나머지는 "없음"으로 보인다.
stockDetails[kakao.code] = { ...kakao, ...realPrice(kakao.code), reasons: [] };

// 데모 모드에서 보유 종목을 고를 때 쓰는 종목 목록.
// 로그인 사용자는 Supabase stocks 테이블을 직접 검색한다.
export const KNOWN_STOCKS: { code: string; name: string }[] = [
  samsungElectronics,
  hyundaiMotor,
  celltrion,
  kakao,
].map(({ code, name }) => ({ code, name }));

// 코드 → 이름. 로그인 사용자의 관심 종목(Supabase에는 코드만 있다)에 이름을 붙일 때 쓴다.
export const STOCK_NAMES: Record<string, string> = Object.fromEntries([
  ...KNOWN_STOCKS.map(({ code, name }) => [code, name]),
  ...Object.values(stockDetails).map(({ code, name }) => [code, name]),
]);
