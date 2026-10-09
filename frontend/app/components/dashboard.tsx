"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import DisclaimerFooter from "./disclaimer-footer";
import { useOnboarding } from "./onboarding-provider";
import PortfolioHeatmap from "./portfolio-heatmap";
import SiteHeader from "./site-header";
import SourceLine from "./source-line";
import StockRow from "./stock-card";
import { useStockMarks } from "./stock-marks";
import {
  getAuthenticatedDashboardData,
  type DashboardData,
} from "@/lib/queries";
import { AVOIDED_ASSET_LABELS, summaryFromProfilingOutput } from "@/lib/profiling-rules";
import { loadLatestCloses, type LatestCloses } from "@/lib/latest-closes";
import { chartProvenance } from "@/lib/chart-detail";
import { getSupabaseClient } from "@/lib/supabase";
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

function SectionHead({ title, action }: { title: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-3 px-1">
      <h2 className="text-xl font-semibold">{title}</h2>
      {action}
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
              : "내 대시보드 데이터를 불러오지 못했습니다.",
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
  // 보유 종목의 최신 종가·신호(최신 게시 차트). 오늘 목록 종목도 같은 요청으로 읽어 출처 줄에 기준일을 붙인다.
  const savedCodes = [...(savedHoldings ?? []), ...stocks].map(({ code }) => code).join(",");
  const [closes, setCloses] = useState<LatestCloses>(new Map());
  useEffect(() => {
    let active = true;
    void loadLatestCloses(getSupabaseClient(), savedCodes ? savedCodes.split(",") : []).then((next) => active && setCloses(next));
    return () => {
      active = false;
    };
  }, [savedCodes]);
  // 사용자가 등록한 종목에 오늘 신호를 붙인다. 최신 게시 차트(4주 방향)가 먼저, 없으면 기존 값.
  // 신호가 없는 종목은 중립으로 꾸미지 않고 맵에서 빼고 개수만 알린다 — 없는 판단을 지어내지 않는다.
  const signalByCode = new Map(
    [...holdings, ...stocks, ...rawHoldingAlerts].map((item) => [item.code, item]),
  );
  const activeHoldings = savedHoldings
    ? savedHoldings.flatMap((saved) => {
        const source = signalByCode.get(saved.code);
        const latest = closes.get(saved.code);
        const signalLight = latest?.signal ?? source?.signalLight;
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
            provenance: latest?.signal ? chartProvenance(latest.asOf) : source!.provenance,
          },
        ];
      })
    : holdings;
  // 어제와 달라진 근거: 보유 ∪ 관심 종목
  const changeKey = JSON.stringify([...new Map([...(savedHoldings ?? holdings), ...watchlist].map(({ code, name }) => [code, name]))]);
  const [changes, setChanges] = useState<DailyChange[] | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    const stocks = (JSON.parse(changeKey) as [string, string][]).map(([code, name]) => ({ code, name }));
    void loadDailyChanges(getSupabaseClient(), stocks).then((next) => active && setChanges(next));
    return () => {
      active = false;
    };
  }, [changeKey]);
  const holdingsWithoutSignal = savedHoldings
    ? savedHoldings.length - activeHoldings.length
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
  const [strong, setStrong] = useState<Awaited<ReturnType<typeof loadStrongSignals>> | undefined>(undefined);
  useEffect(() => {
    let active = true;
    void loadStrongSignals(getSupabaseClient(), { userMaxRiskTier: null, avoided: new Set(avoidedKey ? avoidedKey.split(",") : []) })
      .then((next) => active && setStrong(next));
    return () => {
      active = false;
    };
  }, [avoidedKey]);
  const strongSignals = strong ? [...strong.up, ...strong.down] : [];
  const activeExcludedStocks = activeAvoidedLabels.length > 0 ? strong?.excluded ?? excludedStocks : [];
  const keyword = query.trim();
  const normalized = keyword.toLowerCase();
  const matches = (stock: { name: string; code: string }) =>
    stock.name.toLowerCase().includes(normalized) ||
    stock.code.toLowerCase().includes(normalized);
  const visibleStrong = keyword ? strongSignals.filter(matches) : strongSignals;
  const visibleAlerts = keyword ? holdingAlerts.filter(matches) : [];
  const noResult = keyword && visibleStrong.length + visibleAlerts.length === 0;
  const holdingCount = savedHoldings ? savedHoldings.length : activeHoldings.length;
  const summary = dashboardSummary({
    holdingSignals: activeHoldings.map(({ signalLight }) => signalLight),
    holdingCount,
    strongCount: strongSignals.length,
  });
  // 요약 문장은 보유 맵 신호의 기준일(최신 게시 차트)을 따른다. 없으면 시장 기준일.
  const summaryAsOf = activeHoldings.map(({ priceAsOf }) => priceAsOf ?? "").sort().at(-1) || marketStatus.date;
  const listProvenance = strongSignals[0] ? chartProvenance(strongSignals[0].asOf) : marketStatus.provenance;

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
        className="mx-auto box-border flex w-full max-w-[1200px] flex-col gap-8 px-4 pb-12 pt-6 sm:px-8"
        aria-busy={loadingAuthenticatedData}
      >
        {dataError && (
          <div
            role="alert"
            className="flex flex-col gap-3 rounded-lg bg-field px-4 py-3 sm:flex-row sm:items-center"
          >
            <div className="min-w-0">
              <p className="text-sm font-medium text-body">
                내 데이터를 불러오지 못해 샘플 데이터를 표시합니다.
              </p>
              <p className="mt-1 break-words text-xs text-body">{dataError}</p>
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
            <Link
              href="/profile"
              aria-label={`내 투자 성향: ${activeProfile.profileTypeLabel}. 결과 보기`}
              className="surface flex items-center gap-3 px-5 py-3.5 text-sm text-body hover:bg-white/70 hover:no-underline"
            >
              <span className="min-w-0 flex-1 truncate">
                <span className="font-semibold text-ink">{activeProfile.profileTypeLabel}</span> ·{" "}
                {activeProfile.personaLabel}
              </span>
              <span aria-hidden className="flex-none text-muted">›</span>
            </Link>

            <section aria-labelledby="today-summary" className="flex flex-col gap-1.5 px-1">
              <span className="eyebrow tabular-nums">{summaryAsOf.replaceAll("-", ".")} 기준</span>
              <h1 id="today-summary" className="text-3xl font-semibold">
                {summary}
              </h1>
            </section>

            {changes && changeKey !== "[]" && <DailyChanges changes={changes} />}

            <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-2 lg:gap-6">
              <div className="flex flex-col gap-8">
              <section aria-label="내 보유 종목" className="flex flex-col gap-3">
                <SectionHead
                  title="내 보유 종목의 오늘 신호"
                  action={
                    activeHoldings.length > 0 && (
                      <Link href="/portfolio" className="btn-text text-xs">
                        편집
                      </Link>
                    )
                  }
                />
                <PortfolioHeatmap holdings={activeHoldings} withoutSignalCount={holdingsWithoutSignal} />
              </section>

              {watchlist.length > 0 && (
                <section aria-label="관심 종목" className="flex flex-col gap-3">
                  <SectionHead
                    title="관심 종목"
                    action={
                      <Link href="/portfolio" className="btn-text text-xs">
                        편집
                      </Link>
                    }
                  />
                  <ul className="group-list m-0 list-none p-0">
                    {watchlist.map(({ code, name }) => {
                      const light = signalByCode.get(code)?.signalLight;
                      return (
                        <li key={code}>
                          <Link
                            href={`/stocks/${code}`}
                            className="flex items-center gap-3 px-5 py-4 text-ink hover:bg-field hover:text-ink hover:no-underline"
                          >
                            <span className="min-w-0 flex-1 truncate text-base font-medium">{name}</span>
                            <span className="flex-none text-xs text-muted tabular-nums">{code}</span>
                            <span
                              className="flex-none text-sm font-semibold"
                              style={{ color: light ? SIGNAL_META[light].ink : "var(--color-muted)" }}
                            >
                              {light ? SIGNAL_META[light].label : "오늘 신호 없음"}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}
              </div>

              <section aria-label="오늘 신호가 강한 종목" className="flex flex-col gap-3">
                <SectionHead title="오늘 신호가 강한 종목" />
                {strong === undefined ? (
                  <div className="surface h-[330px] animate-pulse" aria-label="오늘 신호 불러오는 중" />
                ) : !keyword && strongSignals.length === 0 ? (
                  <div className="surface flex min-h-[160px] items-center justify-center px-6 text-center">
                    <p className="text-sm text-body">오늘 보여 줄 모델 신호가 아직 없어요.</p>
                  </div>
                ) : noResult ? (
                  <div className="surface flex flex-col items-center gap-3 px-6 py-8 text-center">
                    <p className="text-sm text-body">&lsquo;{keyword}&rsquo;은(는) 오늘 목록에 없어요.</p>
                    <Link href={`/stocks/${encodeURIComponent(keyword)}`} className="btn-secondary">
                      종목 정보 보기
                    </Link>
                  </div>
                ) : (
                  <div className="group-list">
                    {visibleStrong.map((signal) => (
                      <StrongRow key={signal.code} signal={signal} />
                    ))}
                    {visibleAlerts.map((stock) => (
                      <StockRow key={stock.code} stock={stock} />
                    ))}
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
                  <SourceLine provenance={listProvenance} />
                  <span className="text-2xs text-muted">모델 검증 전 · 신호는 과거 데이터로 만든 참고 정보예요</span>
                </div>
                {!keyword && activeExcludedStocks.length > 0 && (
                  <details className="disclosure surface px-5">
                    <summary>
                      직접 고른 제외 항목
                      <span className="count">{activeExcludedStocks.length}개</span>
                    </summary>
                    <div className="flex flex-col gap-2 pb-4 text-xs text-body">
                      <p className="m-0 text-muted">{activeAvoidedLabels.join(" · ")}을(를) 골라 목록에서 뺐어요.</p>
                      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                        {activeExcludedStocks.map((stock) => (
                          <li key={stock.code} className="flex flex-wrap items-baseline gap-x-2 [word-break:keep-all]">
                            <span className="font-medium text-ink [overflow-wrap:anywhere]">{stock.name}</span>
                            <span className="text-muted tabular-nums">
                              {stock.code} · {stock.reason}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  </details>
                )}
              </section>
            </div>

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
      <h2 id="daily-changes" className="eyebrow px-1">어제와 달라진 근거</h2>
      {changes.length ? (
        <ul className="group-list m-0 list-none p-0">
          {changes.map((change) => (
            <li key={`${change.code}:${change.what}`}>
              <Link
                href={`/stocks/${change.code}`}
                className="flex min-h-11 items-center gap-3 px-5 py-3 text-sm text-ink hover:bg-field hover:text-ink hover:no-underline"
              >
                <span className="flex-none font-medium">{change.name}</span>
                <span className="min-w-0 flex-1 truncate text-body">
                  {change.what} · <span className="tabular-nums">{change.how}</span>
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

// 한 줄: 종목명 · 왜(기여도 1위 항목) · 방향. 검증 상태는 섹션 출처 줄에 한 번만.
function StrongRow({ signal }: { signal: StrongSignal }) {
  const meta = SIGNAL_META[signal.direction === "up" ? "positive" : "negative"];
  return (
    <Link
      href={`/stocks/${signal.code}`}
      data-stock-row={signal.code}
      className="flex items-center gap-4 px-5 py-4 text-ink transition-colors hover:bg-field hover:text-ink hover:no-underline"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline gap-2">
          <span className="truncate text-base font-medium">{signal.name}</span>
          <span className="flex-none text-xs text-muted tabular-nums">{signal.code}</span>
        </span>
        <span className="truncate text-xs text-muted">{signal.why ? `가장 크게 본 것: ${signal.why}` : "4주 · 20거래일"}</span>
      </div>
      <span className="flex-none text-sm font-semibold" style={{ color: meta.ink }}>
        {signal.direction === "up" ? "상방" : "하방"}
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
