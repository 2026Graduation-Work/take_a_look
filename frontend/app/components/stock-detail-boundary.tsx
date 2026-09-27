"use client";

import { useEffect, useState } from "react";
import RealChartDetail from "./real-chart-detail";
import { getPublishedChartDetail, type PublishedChartDetail } from "@/lib/chart-signal";

export default function StockDetailBoundary({ code }: { code: string }) {
  const [requestVersion, setRequestVersion] = useState(0);
  const [chartResult, setChartResult] = useState<{ data: PublishedChartDetail | null; error: string } | null>(null);

  useEffect(() => {
    let active = true;
    getPublishedChartDetail(code)
      .then((data) => { if (active) setChartResult({ data, error: "" }); })
      .catch((error: unknown) => { if (active) setChartResult({ data: null, error: error instanceof Error ? error.message : "차트 데이터를 불러오지 못했습니다." }); });
    return () => { active = false; };
  }, [code, requestVersion]);

  if (chartResult?.data) return <RealChartDetail data={chartResult.data} />;
  return <main className="mx-auto max-w-[960px] p-6"><h1 className="text-2xl font-semibold">종목 상세</h1><p role={chartResult?.error ? "alert" : "status"} className="text-sm text-body">{chartResult?.error || (chartResult ? "공개된 차트 데이터가 없어요." : "공개된 차트 데이터를 불러오는 중이에요.")}</p><button type="button" className="btn-secondary" onClick={() => { setChartResult(null); setRequestVersion((version) => version + 1); }}>다시 시도</button></main>;
}
