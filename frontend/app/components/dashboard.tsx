"use client";

import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import Link from "next/link";
import Segmented from "./segmented";
import DisclaimerFooter from "./disclaimer-footer";
import { useOnboarding } from "./onboarding-provider";
import PortfolioHeatmap from "./portfolio-heatmap";
import SiteHeader from "./site-header";
import { useMarketStatus } from "./market-status-bar";
import { staleLabel } from "@/lib/market-status";
import { HORIZON_WHY, SIGNAL_WORD } from "@/lib/copy-glossary";
import MarketDetail from "./market-detail";
import { useSignalHorizon } from "@/lib/use-signal-horizon";
import StockRow from "./stock-card";
import { useStockSearch } from "./use-stock-search";
import { useStockMarks } from "./stock-marks";
import {
  getAuthenticatedDashboardData,
  type DashboardData,
} from "@/lib/queries";
import { AVOIDED_ASSET_LABELS, summaryFromProfilingOutput } from "@/lib/profiling-rules";
import { loadLatestCloses, type LatestCloses } from "@/lib/latest-closes";
import { chartProvenance } from "@/lib/chart-detail";
import { getSupabaseClient, isSupabaseConfigured } from "@/lib/supabase";
import { SIGNAL_META } from "@/lib/display";
import { dashboardSummary } from "@/lib/dashboard-summary";
import { costBasis } from "@/lib/holdings-rules";
import { holdingAlertsOutside } from "@/lib/recommendation-filter";
import { loadStrongSignals, type StrongSignal } from "@/lib/strong-signals";
import { loadDailyChanges, type DailyChange } from "@/lib/daily-changes";
import type { RiskFlag } from "@/lib/types";
import {
  getSavedHoldingsSnapshot,
  getServerHoldingsSnapshot,
  parseSavedHoldings,
  subscribeToSavedHoldings,
} from "@/lib/save-holdings";
import {
  getSavedProfileSnapshot,
  getServerProfileSnapshot,
  parseSavedProfile,
  subscribeToSavedProfile,
} from "@/lib/save-profile";

// 섹션 제목 줄: 제목 + 오른쪽 컨트롤(그것이 바꾸는 내용의 제목 줄, DESIGN.md '읽는 순서') + 아래 13px 한 줄.
// 두 열의 제목 줄 높이를 같게(min-h-11) 두어 같은 높이에서 시작한다
// 제목 줄: 제목 왼쪽, [설명][컨트롤] 오른쪽. 390처럼 한 줄에 안 들어가면 [설명][컨트롤]이 제목 아래 둘째 줄로 가고
// (컨트롤은 오른쪽), 설명이 없어도 컨트롤이 그 줄 높이를 잡아 아래 내용이 흔들리지 않는다
function SectionHead({ title, control }: { title: string; control?: ReactNode }) {
  return (
    <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-1">
      <h2 className="basis-full text-xl font-semibold sm:basis-auto">{title}</h2>
      {control && (
        <div className="flex min-w-0 flex-1 items-center justify-end gap-3 sm:flex-none">
          {control}
        </div>
      )}
    </div>
  );
}

interface AuthenticatedDashboardResult {
  userId: string;
  data?: DashboardData;
  error?: string;
}

export default function Dashboard(initialData: DashboardData) {
  const { state: onboardingState } = useOnboarding();
  const [query, setQuery] = useState("");
  const [authenticatedResult, setAuthenticatedResult] =
    useState<AuthenticatedDashboardResult | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    const userId = onboardingState.userId;
    if (onboardingState.mode !== "supabase" || !userId) return;

    let active = true;
    getAuthenticatedDashboardData()
      .then((data) => {
        if (!active) return;
        setAuthenticatedResult({ userId, data });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setAuthenticatedResult({
          userId,
          error:
            error instanceof Error
              ? error.message
              : "내 대시보드 데이터를 불러오지 못했어요.",
        });
      });

    return () => {
      active = false;
    };
  }, [onboardingState.mode, onboardingState.userId, requestVersion]);

  const currentAuthenticatedResult =
    authenticatedResult?.userId === onboardingState.userId
      ? authenticatedResult
      : null;
  const authenticatedData = currentAuthenticatedResult?.data ?? null;
  const dataError = currentAuthenticatedResult?.error ?? "";
  const currentData = authenticatedData ?? initialData;
  const {
    marketStatus,
    profile,
    stocks = [],
    holdingAlerts: rawHoldingAlerts = [],
    holdings = [],
    excludedStocks = [],
    avoidedLabels = [],
  } = currentData;
  const holdingAlerts = holdingAlertsOutside(rawHoldingAlerts, stocks);
  const { watchlist } = useStockMarks();
  const liveMarket = useMarketStatus(marketStatus); // 시장 바와 같은 최신 값
  const loadingAuthenticatedData =
    onboardingState.mode === "supabase" && !authenticatedData && !dataError;
  const savedSnapshot = useSyncExternalStore(
    subscribeToSavedProfile,
    getSavedProfileSnapshot,
    getServerProfileSnapshot,
  );
  const savedProfile = parseSavedProfile(savedSnapshot);
  const savedHoldingsSnapshot = useSyncExternalStore(
    subscribeToSavedHoldings,
    getSavedHoldingsSnapshot,
    getServerHoldingsSnapshot,
  );
  const savedHoldings = parseSavedHoldings(savedHoldingsSnapshot);
  // 보유·관심 종목의 최신 종가·신호(최신 게시 차트). 오늘 목록 종목도 같은 요청으로 읽어 출처 줄에 기준일을 붙인다.
  const savedCodes = [...(savedHoldings ?? holdings), ...watchlist, ...stocks].map(({ code }) => code).join(",");
  // 신호 기간: 기본 4주, 1주로 바꿔 볼 수 있다. 선택은 이 기기에만 기억(서버 렌더는 4주)
  const [horizon, chooseHorizon] = useSignalHorizon();
  const publicData = isSupabaseConfigured();
  const closeKey = JSON.stringify([savedCodes, horizon, onboardingState.mode, onboardingState.userId, requestVersion]);
  const [closeResult, setCloseResult] = useState<{ key: string; closes: LatestCloses; error: string } | null>(null);
  const closes: LatestCloses = closeResult?.key === closeKey ? closeResult.closes : new Map();
  const closesError = closeResult?.key === closeKey ? closeResult.error : "";
  const loadingCloses = publicData && Boolean(savedCodes) && closeResult?.key !== closeKey;
  useEffect(() => {
    let active = true;
    void loadLatestCloses(getSupabaseClient(), savedCodes ? savedCodes.split(",") : [], horizon, { throwOnError: true })
      .then((next) => active && setCloseResult({ key: closeKey, closes: next, error: "" }))
      .catch(() => active && setCloseResult({ key: closeKey, closes: new Map(), error: "보유 종목 신호를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요." }));
    return () => {
      active = false;
    };
  }, [savedCodes, horizon, closeKey]);
  // 사용자가 등록한 종목에 오늘 신호를 붙인다. 최신 게시 차트(4주 방향)가 먼저, 없으면 기존 값.
  // 신호가 없는 종목은 중립으로 꾸미지 않고 맵에서 빼고 개수만 알린다 — 없는 판단을 지어내지 않는다.
  const signalByCode = new Map(
    [...holdings, ...stocks, ...rawHoldingAlerts].map((item) => [item.code, item]),
  );
  // 보유 맵·관심 종목이 같은 신호를 쓴다(#278): 최신 게시 차트(4주 방향)가 먼저, 없으면 기존 값
  const lightFor = (code: string) => publicData ? closes.get(code)?.signal : signalByCode.get(code)?.signalLight;
  const displayHoldings = savedHoldings ?? (publicData ? holdings.map(row => ({ ...row, avgBuyPrice: null })) : null);
  const activeHoldings = displayHoldings
    ? displayHoldings.flatMap((saved) => {
        const source = signalByCode.get(saved.code);
        const latest = closes.get(saved.code);
        const signalLight = lightFor(saved.code);
        if (!signalLight) return [];
        const { price, basis } = costBasis(saved.avgBuyPrice, latest?.close);
        return [
          {
            code: saved.code,
            name: saved.name,
            signalLight,
            quantity: saved.quantity,
            avgBuyPrice: price,
            priceBasis: basis,
            ...(latest ? { priceAsOf: latest.asOf } : {}),
            provenance: latest?.signal ? chartProvenance(latest.asOf, horizon) : source!.provenance,
          },
        ];
      })
    : holdings;
  // 어제와 달라진 근거: 보유 ∪ 관심 종목
  const changeKey = JSON.stringify([...new Map([...(savedHoldings ?? holdings), ...watchlist].map(({ code, name }) => [code, name]))]);
  const changeRequestKey = JSON.stringify([changeKey, horizon]);
  const [changeResult, setChangeResult] = useState<{ key: string; data: DailyChange[] | null } | null>(null);
  const changes = changeResult?.key === changeRequestKey ? changeResult.data : undefined;
  useEffect(() => {
    let active = true;
    const stocks = (JSON.parse(changeKey) as [string, string][]).map(([code, name]) => ({ code, name }));
    void loadDailyChanges(getSupabaseClient(), stocks, horizon).then((next) => active && setChangeResult({ key: changeRequestKey, data: next }));
    return () => {
      active = false;
    };
  }, [changeKey, horizon, changeRequestKey]);
  const holdingsWithoutSignal = displayHoldings
    ? displayHoldings.length - activeHoldings.length
    : 0;
  const activeProfile = savedProfile
    ? summaryFromProfilingOutput(savedProfile, profile)
    : profile;
  const activeAvoidedLabels = savedProfile
    ? savedProfile.constraints.avoided_assets
        .map((asset) => AVOIDED_ASSET_LABELS[asset])
        .filter((label): label is string => Boolean(label))
    : avoidedLabels;
  // 오늘 신호가 강한 종목: 최신 게시 배치 코스피 전 종목의 4주 확신도 순(계정·데모 같은 화면). 회피 항목만 뺀다.
  const avoidedKey = (Object.entries(AVOIDED_ASSET_LABELS) as [RiskFlag, string][])
    .filter(([, label]) => activeAvoidedLabels.includes(label)).map(([flag]) => flag).join(",");
  const strongKey = JSON.stringify([avoidedKey, horizon]);
  const [strongResult, setStrongResult] = useState<{ key: string; data: Awaited<ReturnType<typeof loadStrongSignals>> } | null>(null);
  const strong = strongResult?.key === strongKey ? strongResult.data : undefined;
  useEffect(() => {
    let active = true;
    void loadStrongSignals(getSupabaseClient(), { userMaxRiskTier: null, avoided: new Set(avoidedKey ? avoidedKey.split(",") : []) }, horizon)
      .then((next) => active && setStrongResult({ key: strongKey, data: next }));
    return () => {
      active = false;
    };
  }, [avoidedKey, horizon, strongKey]);
  const strongSignals = strong ? [...strong.up, ...strong.down] : [];
  const activeExcludedStocks = activeAvoidedLabels.length > 0 ? strong?.excluded ?? excludedStocks : [];
  const keyword = query.trim();
  const { target: searchTarget, matches: searchMatches } = useStockSearch(keyword);
  const normalized = keyword.toLowerCase();
  const matches = (stock: { name: string; code: string }) =>
    stock.name.toLowerCase().includes(normalized) ||
    stock.code.toLowerCase().includes(normalized);
  const visibleStrong = keyword ? strongSignals.filter(matches) : strongSignals;
  const visibleAlerts = keyword ? holdingAlerts.filter(matches) : [];
  const noResult = keyword && visibleStrong.length + visibleAlerts.length === 0;
  const holdingCount = displayHoldings?.length ?? activeHoldings.length;
  const summary = loadingCloses ? "보유 종목의 신호를 불러오는 중이에요." : closesError ? "보유 종목의 신호를 확인하지 못했어요." : holdingCount > 0 && activeHoldings.length === 0 ? "보유 종목의 게시된 신호가 아직 없어요." : dashboardSummary({
    holdings: activeHoldings.map(({ name, signalLight }) => ({ name, signal: signalLight })),
    holdingCount,
    strongCount: strongSignals.length,
  });
  // 요약 문장은 보유 맵 신호의 기준일(최신 게시 차트)을 따른다. 없으면 시장 기준일.
  const summaryAsOf = activeHoldings.map(({ priceAsOf }) => priceAsOf ?? "").sort().at(-1) || liveMarket.date;

  function retryAuthenticatedData() {
    setAuthenticatedResult(null);
    setRequestVersion((version) => version + 1);
  }

  return (
    <div className="w-full">
      <SiteHeader
        query={query}
        onQueryChange={setQuery}
        profile={activeProfile}
        marketStatus={marketStatus}
      />

      <div
        className="mx-auto box-border flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-12 pt-6 sm:px-6 lg:px-8"
        aria-busy={loadingAuthenticatedData}
      >
        {dataError && (
          <div
            role="alert"
            className="flex flex-col gap-3 rounded-lg bg-field px-4 py-3 sm:flex-row sm:items-center"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-body">
                내 데이터를 불러오지 못해 샘플 데이터를 표시해요.
              </p>
              <p className="mt-1 break-words text-xs text-muted">{dataError}</p>
            </div>
            <button
              type="button"
              onClick={retryAuthenticatedData}
              className="h-11 flex-none surface px-4 text-xs font-medium text-body hover:bg-field sm:ml-auto"
            >
              다시 시도
            </button>
          </div>
        )}

        {loadingAuthenticatedData ? (
          <DashboardLoading />
        ) : (
          <>
            {/* 읽는 순서(DESIGN.md): 결론(요약) → 나에게 해당하는 것(성향 줄, 내 포트폴리오) → 둘러볼 것(신호가 강한 종목) */}
            <section aria-labelledby="today-summary" className="flex flex-col gap-2 px-1">
              {/* 기준일은 시장 바에 한 번 — 신호가 2영업일 넘게 밀렸을 때만 여기에도 */}
              {staleLabel(summaryAsOf) && <span className="text-2xs text-muted tabular-nums">{summaryAsOf.replaceAll("-", ".")} 기준</span>}
              <h1 id="today-summary" className="text-3xl font-semibold">
                {summary}
              </h1>
              {/* 성향 한 줄: 유형(굵게) + 놓치기 쉬운 것. 누르면 내 투자 성향 */}
              <Link
                href="/profile"
                aria-label={`내 투자 성향: ${activeProfile.profileTypeLabel}. 결과 보기`}
                className="flex min-h-11 items-center gap-2 text-base text-muted hover:text-body hover:no-underline"
              >
                <span className="min-w-0">
                  <span className="mr-2 font-semibold text-body">{activeProfile.profileTypeLabel}</span>
                  {activeProfile.blindSpot ?? activeProfile.personaLabel}
                </span>
                <span aria-hidden className="flex-none">›</span>
              </Link>
            </section>

            {/* 2단(1024px 이상 8:4): 왼쪽 내 것, 오른쪽 시장 전체. 1단에서는 왼쪽 → 오른쪽 순서 */}
            <div className="grid grid-cols-1 items-start gap-12 lg:grid-cols-12 lg:gap-6">
              <section aria-label="내 포트폴리오" className="flex flex-col gap-6 lg:col-span-8">
                <div className="flex flex-col gap-2">
                  {/* 기간 전환은 그것이 바꾸는 내용(맵, 요약, 목록)의 제목 줄에. 1주, 4주 오름차순(기본 4주) */}
                  <SectionHead
                    title="내 포트폴리오"
                    control={<>
                      <MarketDetail title="1주와 4주" className="inline-flex"
                        label={<><span aria-hidden className="px-1 text-muted">ⓘ</span><span className="sr-only">1주와 4주 설명 보기</span></>}>
                        <p className="m-0">{HORIZON_WHY}</p>
                      </MarketDetail>
                      <Segmented label="신호 기간" value={horizon} options={[[5, "1주"], [20, "4주"]]} onChange={chooseHorizon} />
                    </>}
                  />
                  {loadingCloses ? <div aria-label="보유 종목 신호 불러오는 중" className="surface h-[330px] animate-pulse" />
                    : closesError ? <div role="alert" className="surface flex flex-col gap-3 p-6">
                      <p className="text-sm text-body">{closesError}</p>
                      <button type="button" className="btn-secondary self-end" onClick={retryAuthenticatedData}>다시 시도</button>
                    </div>
                    : <PortfolioHeatmap holdings={activeHoldings} withoutSignalCount={holdingsWithoutSignal} horizon={horizon} />}
                </div>
                {changes && changeKey !== "[]" && <DailyChanges changes={changes} />}
                {watchlist.length > 0 && (
                  <section aria-label="관심 종목" className="flex flex-col gap-2">
                    <h3 className="m-0 px-1 text-sm font-semibold">관심 종목</h3>
                    <ul className="group-list m-0 list-none p-0">
                      {watchlist.map(({ code, name }) => {
                        const light = lightFor(code);
                        return (
                          <li key={code}>
                            <Link
                              href={`/stocks/${code}`}
                              className="flex min-h-11 items-center gap-2 px-6 py-3 text-ink hover:bg-field hover:text-ink hover:no-underline"
                            >
                              <span className="min-w-0 truncate text-sm font-medium">{name}</span>
                              <span className="flex-1 text-2xs text-muted tabular-nums">{code}</span>
                              <span
                                className="flex-none text-sm font-semibold"
                                style={{ color: light ? SIGNAL_META[light].ink : "var(--color-muted)" }}
                              >
                                {loadingCloses ? "불러오는 중" : light ? SIGNAL_META[light].label : "오늘 신호 없음"}
                              </span>
                              <span className="size-2 flex-none rotate-45 border-r-[1.5px] border-t-[1.5px] border-ghost" aria-hidden />
                            </Link>
                          </li>
                        );
                      })}
                    </ul>
                  </section>
                )}
              </section>

              <section aria-label="신호가 강한 종목" className="flex flex-col gap-2 lg:col-span-4">
                <SectionHead title="신호가 강한 종목" />
                {strong === undefined ? (
                  <div className="surface h-[330px] animate-pulse" aria-label="오늘 신호 불러오는 중" />
                ) : !keyword && strongSignals.length === 0 ? (
                  <div className="surface flex min-h-[160px] items-center justify-center px-6 text-center">
                    <p className="text-sm text-body">오늘 보여 줄 모델 신호가 아직 없어요.</p>
                  </div>
                ) : noResult ? (
                  <div className="surface flex flex-col items-center gap-4 px-6 py-8 text-center">
                    <p className="text-sm text-body">&lsquo;{keyword}&rsquo;은(는) 오늘 목록에 없어요.</p>
                    {searchTarget ? (
                      <Link href={`/stocks/${searchTarget.code}`} className="btn-secondary">
                        종목 정보 보기
                      </Link>
                    ) : (
                      <p className="text-sm text-muted">
                        {searchMatches.length > 1
                          ? "검색창에 표시된 후보에서 종목을 골라 주세요."
                          : "종목명이나 코드를 확인하고 다시 검색해 주세요."}
                      </p>
                    )}
                  </div>
                ) : (
                  // 묶음 제목 없이 한 목록(상승 먼저), 줄 오른쪽에 색 단어 하나(화면 규칙 v2)
                  <div className="group-list">
                    {[...visibleStrong.filter(({ direction }) => direction === "up"), ...visibleStrong.filter(({ direction }) => direction === "down")]
                      .map((signal) => <StrongRow key={signal.code} signal={signal} />)}
                    {visibleAlerts.map((stock) => <StockRow key={stock.code} stock={stock} horizon={horizon} />)}
                  </div>
                )}
                {!keyword && activeExcludedStocks.length > 0 && (
                  <details className="disclosure surface px-5">
                    <summary>
                      직접 고른 제외 항목
                      <span className="count">{activeExcludedStocks.length}개</span>
                    </summary>
                    <div className="flex flex-col gap-2 pb-4 text-xs text-body">
                      <p className="m-0 text-muted">{activeAvoidedLabels.join(", ")}을(를) 골라 목록에서 뺐어요.</p>
                      <ul className="m-0 flex list-none flex-col gap-2 p-0">
                        {activeExcludedStocks.map((stock) => (
                          <li key={stock.code} className="flex flex-wrap items-baseline gap-x-2 [word-break:keep-all]">
                            <span className="font-medium text-ink [overflow-wrap:anywhere]">{stock.name}</span>
                            <span className="text-muted tabular-nums">
                              {stock.code}, {stock.reason}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </details>
                )}
              </section>
            </div>

            {/* 데이터 출처는 모델 성적표(/performance) "데이터 출처"로 옮겼다(10/18). 맨 아래 면책 문구에서 성적표로 간다 */}
          </>
        )}
      </div>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}

// 보유·관심 종목에서 직전 대비 바뀐 사실 최대 3줄. 판단 문구 없이 무엇이·어떻게 + 상세 링크.
function DailyChanges({ changes }: { changes: DailyChange[] }) {
  return (
    <section aria-labelledby="daily-changes" className="flex flex-col gap-2">
      <h3 id="daily-changes" className="m-0 px-1 text-sm font-semibold">어제와 달라진 근거</h3>
      {changes.length ? (
        <ul className="group-list m-0 list-none p-0">
          {changes.map((change) => (
            <li key={change.code}>
              <Link
                href={`/stocks/${change.code}`}
                className="flex min-h-11 items-center gap-2 px-6 py-3 text-sm text-ink hover:bg-field hover:text-ink hover:no-underline"
              >
                <span className="flex-none font-medium">{change.name}</span>
                <span className="min-w-0 flex-1 truncate text-body">
                  {change.text}
                </span>
                <span className="size-2 flex-none rotate-45 border-r-[1.5px] border-t-[1.5px] border-ghost" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="m-0 px-1 text-sm text-body">어제와 달라진 근거가 없어요.</p>
      )}
    </section>
  );
}

// 한 줄: 종목명, 코드, 오른쪽 색 단어(상승/하락), 상세로 가는 화살표. 근거는 상세 화면 '모델이 본 이유'에 있다.
function StrongRow({ signal }: { signal: StrongSignal }) {
  return (
    <Link
      href={`/stocks/${signal.code}`}
      data-stock-row={signal.code}
      className="flex min-h-11 items-center gap-2 px-6 py-3 text-ink transition-colors hover:bg-field hover:text-ink hover:no-underline"
    >
      <span className="min-w-0 truncate text-sm font-medium">{signal.name}</span>
      <span className="flex-1 text-2xs text-muted tabular-nums">{signal.code}</span>
      <span className="flex-none text-sm font-semibold" style={{ color: SIGNAL_META[signal.direction === "up" ? "positive" : "negative"].ink }}>
        {SIGNAL_WORD[signal.direction]}
      </span>
      <span className="size-2 flex-none rotate-45 border-r-[1.5px] border-t-[1.5px] border-ghost" aria-hidden />
    </Link>
  );
}

function DashboardLoading() {
  return (
    <div className="flex flex-col gap-8" aria-label="내 대시보드 불러오는 중">
      <div className="flex flex-col gap-2 px-1 pt-4">
        <div className="h-4 w-40 animate-pulse rounded bg-track" />
        <div className="h-8 w-80 max-w-full animate-pulse rounded bg-track" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="surface h-[330px] animate-pulse" />
        <div className="surface h-[330px] animate-pulse" />
      </div>
    </div>
  );
}
