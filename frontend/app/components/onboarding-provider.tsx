"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  getAuthMode,
  resolveOnboardingState,
  signOut,
  subscribeToAuthChanges,
  type OnboardingState,
} from "@/lib/auth";
import Wordmark from "@/components/brand/Wordmark";
import { isChartPreview } from "@/lib/chart-preview-config";

interface OnboardingContextValue {
  state: OnboardingState;
  refresh: (showLoading?: boolean) => Promise<void>;
  logOut: () => Promise<void>;
}

const OnboardingContext = createContext<OnboardingContextValue | null>(null);

export default function OnboardingProvider({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const pathname = usePathname();
  const router = useRouter();
  const requestId = useRef(0);
  const [state, setState] = useState<OnboardingState>({
    status: "loading",
    mode: "demo",
  });

  const refresh = useCallback(async (showLoading = false) => {
    const currentRequest = ++requestId.current;
    if (showLoading) {
      setState({ status: "loading", mode: getAuthMode() });
    }
    try {
      const nextState = await resolveOnboardingState();
      if (currentRequest === requestId.current) setState(nextState);
    } catch (error) {
      if (currentRequest !== requestId.current) return;
      setState({
        status: "error",
        mode: getAuthMode(),
        error:
          error instanceof Error
            ? error.message
            : "로그인 상태를 확인하지 못했습니다.",
      });
    }
  }, []);

  useEffect(() => {
    const initialCheck = window.setTimeout(() => void refresh(), 0);
    const unsubscribe = subscribeToAuthChanges(() => void refresh());
    return () => {
      window.clearTimeout(initialCheck);
      unsubscribe();
    };
  }, [refresh]);

  const logOut = useCallback(async () => {
    await signOut();
    await refresh(true);
  }, [refresh]);

  const destination = onboardingDestination(pathname, state.status);
  useEffect(() => {
    if (destination) router.replace(destination);
  }, [destination, router]);

  const contextValue = useMemo(
    () => ({ state, refresh, logOut }),
    [state, refresh, logOut],
  );

  if (state.status === "loading" || destination) {
    return <OnboardingLoading />;
  }

  if (state.status === "error") {
    return (
      <OnboardingError
        message={state.error ?? "로그인 상태를 확인하지 못했습니다."}
        onRetry={() => void refresh(true)}
      />
    );
  }

  return (
    <OnboardingContext.Provider value={contextValue}>
      {state.mode === "demo" && state.status !== "signed_out" && <DemoAccountBanner />}
      {children}
    </OnboardingContext.Provider>
  );
}

// 데모 계정으로 들어오면 모든 화면 맨 위에 둔다. 실제 계정과 헷갈리지 않게 하는 표시다.
function DemoAccountBanner() {
  return (
    <div
      role="note"
      className="bg-track px-4 py-2 text-center text-xs font-medium text-body"
    >
      데모 계정 · 예시 데이터
      <span className="font-normal"> — 가입 없이 둘러보는 중이에요. 설문 결과는 이 브라우저에만 저장돼요.</span>
    </div>
  );
}

export function useOnboarding(): OnboardingContextValue {
  const value = useContext(OnboardingContext);
  if (!value) {
    throw new Error("useOnboarding은 OnboardingProvider 안에서 사용해야 합니다.");
  }
  return value;
}

function onboardingDestination(
  pathname: string,
  status: OnboardingState["status"],
): string | null {
  if (status === "loading" || status === "error") return null;
  if (pathname.startsWith("/stocks/") && isChartPreview(pathname.slice("/stocks/".length))) return null;
  if (status === "signed_out") return pathname === "/login" ? null : "/login";
  if (status === "needs_survey") {
    return pathname === "/survey" ? null : "/survey";
  }
  if (status === "ready" && pathname === "/login") return "/";
  return null;
}

function BrandMark() {
  return (
    <Wordmark size={32} className="text-xl" />
  );
}

function OnboardingLoading() {
  return (
    <main className="grid min-h-screen place-items-center bg-page px-5">
      <div className="flex flex-col items-center gap-5" aria-live="polite">
        <BrandMark />
        <span className="size-6 animate-spin rounded-full border-2 border-track border-t-brand-accent" />
        <span className="text-sm font-semibold text-muted">로그인 상태 확인 중</span>
      </div>
    </main>
  );
}

function OnboardingError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-page px-5">
      <section className="w-full max-w-[460px] surface p-7">
        <BrandMark />
        <h1 className="mt-8 text-xl font-semibold text-ink">연결을 확인해 주세요</h1>
        <p role="alert" className="mt-2 text-sm leading-6 text-muted">
          {message}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="btn-primary mt-6 w-full"
        >
          다시 시도
        </button>
      </section>
    </main>
  );
}
