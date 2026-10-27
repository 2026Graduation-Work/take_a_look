"use client";

import { useEffect, useState } from "react";
import { loadStockCatalog, type StockOption } from "@/lib/stock-catalog";

export type { StockOption } from "@/lib/stock-catalog";

// The public stock master is identical for demo and account holdings.
export function useStockOptions(keyword: string, catalog: StockOption[]) {
  const [options, setOptions] = useState(catalog);
  const hasQuery = keyword.trim().length > 0;

  useEffect(() => {
    if (!hasQuery) return;
    let active = true;
    void loadStockCatalog().then((list) => active && setOptions(list)).catch(() => {});
    return () => { active = false; };
  }, [hasQuery]);

  // 입력값과 정확히 맞는 후보(이름 또는 코드)
  const match = options.find((item) => item.name === keyword.trim() || item.code === keyword.trim());
  return { options, match };
}
