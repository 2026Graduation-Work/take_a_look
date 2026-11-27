"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import StockDetailView from "./stock-detail";
import ChartPreviewDetail from "./chart-preview";
import { isChartPreview } from "@/lib/chart-preview-config";
import { useOnboarding } from "./onboarding-provider";
import { STORAGE_KEYS } from "@/lib/storage-keys";
import { readingHistoryKey } from "@/lib/evidence-reading-history";
import { summaryFromProfilingOutput } from "@/lib/profiling-rules";
import type { StockInsights } from "@/lib/providers";
import {
  getAuthenticatedStockDetailData,
  type StockDetailData,
} from "@/lib/queries";
import {
  getSavedProfileSnapshot,
  getServerProfileSnapshot,
  parseSavedProfile,
  subscribeToSavedProfile,
} from "@/lib/save-profile";

interface AuthenticatedDetailResult {
  userId: string;
  code: string;
  data?: StockDetailData;
  error?: string;
}

export default function StockDetailBoundary({
  code,
  initialData,
  insights,
}: {
  code: string;
  initialData: StockDetailData;
  insights: StockInsights;
}) {
  const { state: onboardingState } = useOnboarding();
  const [authenticatedResult, setAuthenticatedResult] =
    useState<AuthenticatedDetailResult | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    const userId = onboardingState.userId;
    if (onboardingState.mode !== "supabase" || !userId) return;

    let active = true;
    getAuthenticatedStockDetailData(code)
      .then((data) => {
        if (active) setAuthenticatedResult({ userId, code, data });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setAuthenticatedResult({
          userId,
          code,
          error:
            error instanceof Error
              ? error.message
              : "종목 상세 데이터를 불러오지 못했어요.",
        });
      });

    return () => {
      active = false;
    };
  }, [code, onboardingState.mode, onboardingState.userId, requestVersion]);

  const currentResult =
    onboardingState.mode === "supabase" &&
    authenticatedResult &&
    authenticatedResult.userId === onboardingState.userId &&
    authenticatedResult.code === code
      ? authenticatedResult
      : null;
  const fetched = currentResult?.data ?? initialData;
  const savedProfile = parseSavedProfile(
    useSyncExternalStore(subscribeToSavedProfile, getSavedProfileSnapshot, getServerProfileSnapshot),
  );
  const data =
    fetched.source === "mock" && savedProfile?.style_axes
      ? {
          ...fetched,
          styleAxes: savedProfile.style_axes,
          profile: summaryFromProfilingOutput(savedProfile, fetched.profile),
        }
      : fetched;
  const error = currentResult?.error ?? "";
  const loading =
    onboardingState.mode === "supabase" && Boolean(onboardingState.userId) && !currentResult?.data && !error;

  function retry() {
    setAuthenticatedResult(null);
    setRequestVersion((version) => version + 1);
  }

  const ready = onboardingState.status === "ready";
  const readingUsesDiagnosis = ready && Boolean(data.styleAxes) && (fetched.source === "supabase" || Boolean(savedProfile?.style_axes));
  const historyKey = ready && onboardingState.userId
    ? readingHistoryKey(onboardingState.mode, onboardingState.userId)
    : onboardingState.status === "signed_out" ? STORAGE_KEYS.guestReadingHistory : null;
  const viewKey = `${code}:${historyKey ?? ""}`;
  if (isChartPreview(code)) {
    return <ChartPreviewDetail key={viewKey} data={data} insights={insights} readingHistoryKey={loading ? null : historyKey} readingInvite={ready} readingUsesDiagnosis={readingUsesDiagnosis} />;
  }

  return (
    <StockDetailView
      key={viewKey}
      {...data}
      readingHistoryKey={historyKey}
      readingInvite={ready}
      readingUsesDiagnosis={readingUsesDiagnosis}
      insights={insights}
      loading={loading}
      dataError={error}
      onRetry={retry}
    />
  );
}
