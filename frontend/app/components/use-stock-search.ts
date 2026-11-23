"use client";

import { useEffect, useState } from "react";
import { KNOWN_STOCKS } from "@/lib/mock-data";
import { loadStockCatalog, type StockOption } from "@/lib/stock-catalog";

export function useStockSearch(query: string) {
  const [stocks, setStocks] = useState<StockOption[]>([]);
  const keyword = query.trim().toLowerCase();

  useEffect(() => {
    if (!keyword) return;
    let active = true;
    void loadStockCatalog().then((list) => active && setStocks(list))
      .catch(() => active && setStocks(KNOWN_STOCKS));
    return () => { active = false; };
  }, [keyword]);

  const matches = keyword
    ? stocks.filter(({ code, name }) => name.toLowerCase().includes(keyword) || code.toLowerCase().startsWith(keyword))
    : [];
  const exact = matches.find(({ code, name }) => code.toLowerCase() === keyword || name.toLowerCase() === keyword);
  return { matches: matches.slice(0, 6), target: exact ?? (matches.length === 1 ? matches[0] : undefined), loaded: stocks.length > 0 };
}
