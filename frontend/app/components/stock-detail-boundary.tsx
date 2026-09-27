"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import StockDetailView from "./stock-detail";
import { useOnboarding } from "./onboarding-provider";
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
              : "종목 상세 데이터를 불러오지 못했습니다.",
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
  // 데모 모드에서도 이 브라우저에서 마친 설문 결과가 있으면 대시보드와 같은 8축을 쓴다.
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
    onboardingState.mode === "supabase" && !currentResult?.data && !error;

  function retry() {
    setAuthenticatedResult(null);
    setRequestVersion((version) => version + 1);
  }

  return (
    <StockDetailView
      {...data}
      insights={insights}
      loading={loading}
      dataError={error}
      onRetry={retry}
    />
  );
}
