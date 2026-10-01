"use client";

import { useEffect, useState } from "react";
import { loadPublicCharts, type ChartHorizon, type ChartSnapshot } from "./chart-public";

type Charts = Map<string, Map<ChartHorizon, ChartSnapshot>>;

export function usePublicCharts(codes: string[]) {
  const key = [...new Set(codes)].sort().join(",");
  const [state, setState] = useState<{ key: string; charts: Charts | null; error: string; loading: boolean }>({
    key: "", charts: null, error: "", loading: true,
  });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!key) return;
    const refresh = () => {
      if (document.visibilityState === "visible") setVersion(value => value + 1);
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    const timer = window.setInterval(refresh, 5 * 60 * 1000);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      window.clearInterval(timer);
    };
  }, [key]);

  useEffect(() => {
    let active = true;
    loadPublicCharts(key ? key.split(",") : [])
      .then((charts) => {
        if (active) setState({ key, charts, error: "", loading: false });
      })
      .catch((error: unknown) => {
        if (active) setState((previous) => ({
          key, charts: previous.key === key ? previous.charts : null,
          error: error instanceof Error ? error.message : "공개 차트 조회에 실패했습니다.", loading: false,
        }));
      });
    return () => { active = false; };
  }, [key, version]);

  return {
    charts: state.key === key ? state.charts : null,
    error: state.key === key ? state.error : "",
    loading: state.key !== key || state.loading,
    retry: () => { setState((previous) => ({ ...previous, loading: true })); setVersion((value) => value + 1); },
  };
}
