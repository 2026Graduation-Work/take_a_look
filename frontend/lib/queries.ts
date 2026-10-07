import type { SupabaseClient } from "@supabase/supabase-js";
import { loadLatestCloses } from "./latest-closes.ts";
import { snapshotPrice } from "./providers/demo-snapshot.ts";
import { costBasis } from "./holdings-rules.ts";
import {
  avoidanceNotice,
  holdingAlerts,
  investorProfile,
  investorStyleAxes,
  marketStatus,
  portfolioHoldings,
  recommendedStocks,
  stockDetails,
} from "./mock-data";
import {
  mapAvoidedAssetLabels,
  mapExcludedStocks,
  mapPortfolioHolding,
  mapProfileSummary,
  mapRecommendedStock,
  mapStockDetail,
  toRiskFlags,
  type AvoidedAssetRow,
  type ExcludedStock,
  type IpsProfileRow,
  type PortfolioHoldingRow,
  type PredictionDetailRow,
  type PredictionFeatureRow,
  type PredictionRow,
  type StockRow,
  type UserRow,
} from "./mappers";
import { isStyleAxes } from "./profiling-rules";
import { passesHardConstraints } from "./recommendation-filter";
import type { HoldingWeight } from "./providers";
import { assertOk, getSupabaseClient } from "./supabase";
import type {
  InvestorProfileSummary,
  MarketStatus,
  PortfolioHolding,
  RecommendedStock,
  StockDetail,
  StyleAxes,
} from "./types";

export interface ProfileQueryResult {
  profile: InvestorProfileSummary;
  maxRiskTier: number;
  avoidedLabels: string[];
  excludedStocks: ExcludedStock[];
}

export interface DashboardData {
  marketStatus: MarketStatus;
  stocks: RecommendedStock[];
  holdingAlerts: RecommendedStock[];
  holdings: PortfolioHolding[];
  profile: InvestorProfileSummary;
  maxRiskTier: number;
  avoidedLabels: string[];
  excludedStocks: ExcludedStock[];
}

export interface StockDetailData {
  detail: StockDetail;
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
  maxRiskTier: number;
  styleAxes: StyleAxes | null; // v1.0 프로필이면 null
  holdings: HoldingWeight[]; // 넛지 N08 보유 비중 판정용
  source: "mock" | "supabase";
}

interface ProfileSettingsRow {
  profile_type: "stable" | "aggressive";
}

interface ProfileSettings {
  profileType: "stable" | "aggressive";
  userMaxRiskTier: number | null;
  avoided: Set<string>;
}

interface ProfileQueryContext {
  settings: ProfileSettings;
  result: ProfileQueryResult;
}

const PREDICTION_COLUMNS =
  "stock_code,prediction_date,signal_light,rank_percentile,return_low,return_high,return_ci_level,bucket_hit_rate,similar_case_count,horizon_h5,horizon_h10,horizon_h20,horizon_agreement,caution,display_order" as const;
const DETAIL_PREDICTION_COLUMNS =
  `id,data_asof,horizon,${PREDICTION_COLUMNS}` as const;
const PREDICTION_FEATURE_COLUMNS =
  "feature,label_ko,contribution,display_order" as const;

const STOCK_COLUMNS = "code,name,market,risk_grade,risk_flags,volatility_annual,volatility_percentile,risk_as_of";

// 첫 화면(서버 렌더)은 데모 계정 데이터로 그린다. 개인 테이블은 RLS로 본인만 읽을 수 있어
// 서버의 비로그인 조회로는 얻을 수 없다. 로그인한 사용자는 브라우저에서
// getAuthenticatedDashboardData로 자기 데이터를 다시 불러온다.
export function getDashboardData(): DashboardData {
  return {
    marketStatus,
    stocks: recommendedStocks,
    holdingAlerts,
    holdings: portfolioHoldings,
    profile: investorProfile,
    maxRiskTier: 4,
    avoidedLabels: avoidanceNotice.avoidedLabels,
    excludedStocks: avoidanceNotice.excludedStocks,
  };
}

export async function getAuthenticatedDashboardData(): Promise<DashboardData> {
  const client = getSupabaseClient();
  if (!client) throw new Error("계정 기능이 아직 연결되지 않았어요.");

  const { data: authData, error: authError } = await client.auth.getUser();
  assertOk(authError, "로그인 사용자 확인");
  if (!authData.user) throw new Error("로그인 사용자 정보가 없습니다.");

  const { data: appUser, error: appUserError } = await client
    .from("users")
    .select("id")
    .eq("auth_user_id", authData.user.id)
    .maybeSingle();
  assertOk(appUserError, "대시보드 사용자 확인");
  if (!appUser) throw new Error("연결된 서비스 사용자 정보가 없습니다.");

  const [currentMarketStatus, profileContext, holdingRows] = await Promise.all([
    loadMarketStatus(),
    loadProfileQueryContext(client, appUser.id),
    loadHoldings(client, appUser.id),
  ]);
  const [{ stocks, candidates }, currentHoldingAlerts, holdings] = await Promise.all([
    queryRecommendedStocks(client, appUser.id, profileContext.settings),
    queryHoldingAlerts(client, appUser.id, profileContext.settings, holdingRows),
    queryPortfolio(client, appUser.id, profileContext.settings, holdingRows),
  ]);

  return {
    marketStatus: currentMarketStatus,
    stocks,
    holdingAlerts: currentHoldingAlerts,
    holdings,
    profile: profileContext.result.profile,
    maxRiskTier: profileContext.result.maxRiskTier,
    avoidedLabels: profileContext.result.avoidedLabels,
    // 종목 마스터가 전 종목이라, 제외 목록은 오늘 목록 후보에서 실제로 뺀 종목만 보인다.
    excludedStocks: profileContext.result.excludedStocks.filter(({ code }) => candidates.has(code)),
  };
}

export function getMockStockDetailData(code: string, fallback?: StockDetail): StockDetailData | null {
  const detail = stockDetails[code] ?? fallback;
  if (!detail) return null;
  return {
    detail,
    profile: investorProfile,
    marketStatus,
    maxRiskTier: 4,
    styleAxes: investorStyleAxes,
    holdings: portfolioHoldings,
    source: "mock",
  };
}

export async function getAuthenticatedStockDetailData(
  code: string,
): Promise<StockDetailData> {
  const client = getSupabaseClient();
  if (!client) throw new Error("계정 기능이 아직 연결되지 않았어요.");

  const { data: authData, error: authError } = await client.auth.getUser();
  assertOk(authError, "로그인 사용자 확인");
  if (!authData.user) throw new Error("로그인 사용자 정보가 없습니다.");

  const { data: appUser, error: appUserError } = await client
    .from("users")
    .select("id")
    .eq("auth_user_id", authData.user.id)
    .maybeSingle();
  assertOk(appUserError, "상세 화면 사용자 확인");
  if (!appUser) throw new Error("연결된 서비스 사용자 정보가 없습니다.");

  return queryStockDetail(client, appUser.id, code);
}

// 시장 브리핑은 실데이터 스냅샷(KRX 지수, providers/demo-snapshot.ts)을 쓴다.
// DB market_status에는 손으로 쓴 시드만 있어 읽지 않는다(없는 데이터를 실데이터처럼 보이지 않게).
// ponytail: 백엔드가 market_status를 매일 채우게 되면 여기서 DB를 다시 읽는다(행 매퍼 mapMarketStatus는 git 기록에 있음).
async function loadMarketStatus(): Promise<MarketStatus> {
  return marketStatus;
}

async function queryRecommendedStocks(
  client: SupabaseClient,
  userId: string,
  profileSettings?: ProfileSettings,
): Promise<{ stocks: RecommendedStock[]; candidates: Set<string> }> {
  const settings = profileSettings ?? (await loadProfileSettings(client, userId));
  const { data, error } = await client
    .from("predictions")
    .select(PREDICTION_COLUMNS)
    .eq("model_type", settings.profileType)
    .eq("is_recommended", true)
    .order("prediction_date", { ascending: false })
    .order("display_order", { ascending: true });
  assertOk(error, "오늘 신호 조회");

  const predictions = latestDateRows((data ?? []) as PredictionRow[]);
  const stocks = await loadStocks(
    client,
    predictions.map(({ stock_code }) => stock_code),
  );
  const stockByCode = new Map(stocks.map((stock) => [stock.code, stock]));

  const recommended = predictions.flatMap((prediction) => {
    const stock = stockByCode.get(prediction.stock_code);
    if (!stock || !passesHardConstraints(stock.risk_grade, toRiskFlags(stock.risk_flags), settings)) {
      return [];
    }
    return [mapRecommendedStock(prediction, stock)];
  });
  return { stocks: recommended, candidates: new Set(predictions.map(({ stock_code }) => stock_code)) };
}

async function queryHoldingAlerts(
  client: SupabaseClient,
  userId: string,
  profileSettings?: ProfileSettings,
  portfolioRows?: PortfolioHoldingRow[],
): Promise<RecommendedStock[]> {
  const [settings, holdings] = await Promise.all([
    profileSettings ?? loadProfileSettings(client, userId),
    portfolioRows ?? loadHoldings(client, userId),
  ]);
  if (!holdings.length) return [];

  const { data, error } = await client
    .from("predictions")
    .select(PREDICTION_COLUMNS)
    .eq("model_type", settings.profileType)
    .in(
      "stock_code",
      holdings.map(({ stock_code }) => stock_code),
    )
    .order("prediction_date", { ascending: false })
    .order("display_order", { ascending: true });
  assertOk(error, "보유 종목 알림 조회");

  const predictions = latestRowsByStock((data ?? []) as PredictionRow[]);
  const stocks = await loadStocks(
    client,
    predictions.map(({ stock_code }) => stock_code),
  );
  const stockByCode = new Map(stocks.map((stock) => [stock.code, stock]));
  return predictions.flatMap((prediction) => {
    const stock = stockByCode.get(prediction.stock_code);
    return stock ? [mapRecommendedStock(prediction, stock)] : [];
  });
}

async function queryPortfolio(
  client: SupabaseClient,
  userId: string,
  profileSettings?: ProfileSettings,
  portfolioRows?: PortfolioHoldingRow[],
): Promise<PortfolioHolding[]> {
  const [settings, holdings] = await Promise.all([
    profileSettings ?? loadProfileSettings(client, userId),
    portfolioRows ?? loadHoldings(client, userId),
  ]);
  if (!holdings.length) return [];

  const codes = holdings.map(({ stock_code }) => stock_code);
  const [stocks, predictionResult, closes] = await Promise.all([
    loadStocks(client, codes),
    client
      .from("predictions")
      .select(PREDICTION_COLUMNS)
      .eq("model_type", settings.profileType)
      .in("stock_code", codes)
      .order("prediction_date", { ascending: false }),
    loadLatestCloses(client, codes),
  ]);
  assertOk(predictionResult.error, "포트폴리오 예측 조회");

  const stockByCode = new Map(stocks.map((stock) => [stock.code, stock]));
  const predictionByCode = new Map(
    latestRowsByStock((predictionResult.data ?? []) as PredictionRow[]).map(
      (prediction) => [prediction.stock_code, prediction],
    ),
  );

  return holdings.flatMap((holding) => {
    const stock = stockByCode.get(holding.stock_code);
    return stock
      ? [mapPortfolioHolding(holding, stock, predictionByCode.get(holding.stock_code), closes)]
      : [];
  });
}

async function queryStockDetail(
  client: SupabaseClient,
  userId: string,
  code: string,
): Promise<StockDetailData> {
  const [holdingRows, marketResult, userResult, profileResult, stockResult] = await Promise.all([
    loadHoldings(client, userId),
    loadMarketStatus(),
    client
      .from("users")
      .select("id,display_name,avatar_label")
      .eq("id", userId)
      .maybeSingle(),
    client
      .from("ips_profiles")
      .select(
        "user_id,surveyed_at,profile_type,max_risk_tier,risk_score,fomo_score,horizon_score,style_axes:profile_payload->style_axes",
      )
      .eq("user_id", userId)
      .maybeSingle(),
    client
      .from("stocks")
      .select(STOCK_COLUMNS)
      .eq("code", code)
      .eq("is_active", true)
      .maybeSingle(),
  ]);
  assertOk(userResult.error, "상세 화면 사용자 조회");
  assertOk(profileResult.error, "상세 화면 IPS 프로필 조회");
  assertOk(stockResult.error, "상세 화면 종목 조회");
  if (!userResult.data || !profileResult.data) {
    throw new Error("사용자 또는 IPS 프로필 데이터가 없습니다.");
  }
  if (!stockResult.data) throw new Error(`종목 정보를 찾지 못했습니다: ${code}`);

  const profile = profileResult.data as IpsProfileRow;
  // 8축은 profile_payload(schema v1.1) 안에만 있다. v1.0 프로필이면 null.
  const payloadStyleAxes = (profileResult.data as { style_axes?: unknown }).style_axes;
  const { data: predictionData, error: predictionError } = await client
    .from("predictions")
    .select(DETAIL_PREDICTION_COLUMNS)
    .eq("stock_code", code)
    .eq("model_type", profile.profile_type)
    .order("prediction_date", { ascending: false })
    .limit(1)
    .maybeSingle();
  assertOk(predictionError, "상세 화면 예측 조회");
  if (!predictionData) {
    throw new Error(`${code}의 ${profile.profile_type} 모델 예측이 없습니다.`);
  }

  const prediction = predictionData as PredictionDetailRow;
  const closes = await loadLatestCloses(client, holdingRows.map(({ stock_code }) => stock_code));
  const { data: featureData, error: featureError } = await client
    .from("prediction_features")
    .select(PREDICTION_FEATURE_COLUMNS)
    .eq("prediction_id", prediction.id)
    .order("display_order", { ascending: true });
  assertOk(featureError, "상세 화면 예측 근거 조회");

  return {
    // 시세는 DB 저장 계약이 없어 실데이터 스냅샷에서 붙인다(데모 4종목만).
    detail: {
      ...mapStockDetail(prediction, stockResult.data as StockRow, (featureData ?? []) as PredictionFeatureRow[]),
      ...snapshotPrice(code),
    },
    profile: mapProfileSummary(
      userResult.data as UserRow,
      profile,
      isStyleAxes(payloadStyleAxes) ? payloadStyleAxes : null,
    ),
    marketStatus: marketResult,
    maxRiskTier: profile.max_risk_tier,
    styleAxes: isStyleAxes(payloadStyleAxes) ? payloadStyleAxes : null,
    holdings: holdingRows.map(({ stock_code, quantity, avg_buy_price }) => ({
      code: stock_code,
      quantity,
      avgBuyPrice: costBasis(avg_buy_price, closes.get(stock_code)?.close).price,
    })),
    source: "supabase",
  };
}

async function loadProfileQueryContext(
  client: SupabaseClient,
  userId: string,
): Promise<ProfileQueryContext> {
  const [userResult, profileResult, avoidedResult] = await Promise.all([
    client
      .from("users")
      .select("id,display_name,avatar_label")
      .eq("id", userId)
      .maybeSingle(),
    client
      .from("ips_profiles")
      .select(
        "user_id,surveyed_at,profile_type,max_risk_tier,risk_score,fomo_score,horizon_score,style_axes:profile_payload->style_axes",
      )
      .eq("user_id", userId)
      .maybeSingle(),
    client
      .from("avoided_assets")
      .select("asset_type")
      .eq("user_id", userId)
      .eq("is_active", true),
  ]);
  assertOk(userResult.error, "사용자 조회");
  assertOk(profileResult.error, "IPS 프로필 조회");
  assertOk(avoidedResult.error, "회피 설정 조회");
  if (!userResult.data || !profileResult.data) {
    throw new Error("사용자 또는 IPS 프로필 데이터가 없습니다.");
  }

  const avoidedRows = (avoidedResult.data ?? []) as AvoidedAssetRow[];
  const profile = profileResult.data as IpsProfileRow;
  const payloadStyleAxes = (profileResult.data as { style_axes?: unknown }).style_axes;
  const stocks = await loadAvoidedStocks(client, avoidedRows);
  return {
    settings: toProfileSettings(profile, avoidedRows),
    result: {
      profile: mapProfileSummary(
        userResult.data as UserRow,
        profile,
        isStyleAxes(payloadStyleAxes) ? payloadStyleAxes : null,
      ),
      maxRiskTier: profile.max_risk_tier,
      avoidedLabels: mapAvoidedAssetLabels(avoidedRows),
      excludedStocks: mapExcludedStocks(stocks, avoidedRows),
    },
  };
}

async function loadProfileSettings(
  client: SupabaseClient,
  userId: string,
): Promise<ProfileSettings> {
  const [profileResult, avoidedResult] = await Promise.all([
    client
      .from("ips_profiles")
      .select("profile_type")
      .eq("user_id", userId)
      .maybeSingle(),
    client
      .from("avoided_assets")
      .select("asset_type")
      .eq("user_id", userId)
      .eq("is_active", true),
  ]);
  assertOk(profileResult.error, "성향 설정 조회");
  assertOk(avoidedResult.error, "제외 항목 조회");
  if (!profileResult.data) throw new Error("투자 성향 프로필이 없습니다.");

  return toProfileSettings(
    profileResult.data as ProfileSettingsRow,
    (avoidedResult.data ?? []) as AvoidedAssetRow[],
  );
}

function toProfileSettings(
  profile: ProfileSettingsRow,
  avoidedRows: AvoidedAssetRow[],
): ProfileSettings {
  return {
    profileType: profile.profile_type,
    // ips_profiles.max_risk_tier는 profile_type에서 자동 파생된 값이다(save-profile.ts).
    // 사용자가 직접 정하는 경로가 생기기 전까지는 종목을 거르지 않는다.
    userMaxRiskTier: null,
    avoided: new Set(avoidedRows.map(({ asset_type }) => asset_type)),
  };
}

async function loadAvoidedStocks(
  client: SupabaseClient,
  avoidedRows: AvoidedAssetRow[],
): Promise<StockRow[]> {
  const avoidedTypes = avoidedRows.map(({ asset_type }) => asset_type);
  if (!avoidedTypes.length) return [];

  const { data, error } = await client
    .from("stocks")
    .select(STOCK_COLUMNS)
    .eq("is_active", true)
    .overlaps("risk_flags", avoidedTypes);
  assertOk(error, "회피 대상 종목 조회");
  return (data ?? []) as StockRow[];
}

async function loadStocks(
  client: SupabaseClient,
  codes?: string[],
): Promise<StockRow[]> {
  if (codes && codes.length === 0) return [];
  let query = client.from("stocks").select(STOCK_COLUMNS).eq("is_active", true);
  if (codes) query = query.in("code", [...new Set(codes)]);
  const { data, error } = await query;
  assertOk(error, "종목 마스터 조회");
  return (data ?? []) as StockRow[];
}

async function loadHoldings(
  client: SupabaseClient,
  userId: string,
): Promise<PortfolioHoldingRow[]> {
  const { data, error } = await client
    .from("portfolio_holdings")
    .select("stock_code,quantity,avg_buy_price,display_order")
    .eq("user_id", userId)
    .eq("is_active", true)
    .order("display_order", { ascending: true });
  assertOk(error, "보유 종목 조회");
  return (data ?? []) as PortfolioHoldingRow[];
}

function latestDateRows(rows: PredictionRow[]): PredictionRow[] {
  const latestDate = rows[0]?.prediction_date;
  return latestDate ? rows.filter(({ prediction_date }) => prediction_date === latestDate) : [];
}

function latestRowsByStock(rows: PredictionRow[]): PredictionRow[] {
  const latestByStock = new Map<string, PredictionRow>();
  for (const row of rows) {
    if (!latestByStock.has(row.stock_code)) latestByStock.set(row.stock_code, row);
  }
  return [...latestByStock.values()].sort(
    (left, right) =>
      left.display_order - right.display_order || left.stock_code.localeCompare(right.stock_code),
  );
}

