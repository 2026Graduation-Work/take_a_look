"use client";

import { useEffect, useState } from "react";
import { KNOWN_STOCKS } from "@/lib/mock-data";
import { getSupabaseClient } from "@/lib/supabase";

type StockOption = { code: string; name: string };

// 검색 후보와 본문 링크가 같은 종목 마스터를 사용한다. 요청은 브라우저 안에서 공유한다.
let master: Promise<StockOption[]> | null = null;
function loadMaster(): Promise<StockOption[]> {
  master ??= (async () => {
    const client = getSupabaseClient();
    if (!client) return KNOWN_STOCKS;
    const { data, error } = await client.from("stocks").select("code,name").eq("is_active", true).order("code");
    if (error) {
      master = null;
      return KNOWN_STOCKS;
    }
    return data as StockOption[];
  })();
  return master;
}

export function useStockSearch(query: string) {
  const [stocks, setStocks] = useState<StockOption[]>([]);
  const keyword = query.trim().toLowerCase();

  useEffect(() => {
    if (!keyword) return;
    let active = true;
    void loadMaster().then((list) => active && setStocks(list));
    return () => { active = false; };
  }, [keyword]);

  const matches = keyword
    ? stocks.filter(({ code, name }) => name.toLowerCase().includes(keyword) || code.toLowerCase().startsWith(keyword))
    : [];
  const exact = matches.find(({ code, name }) => code.toLowerCase() === keyword || name.toLowerCase() === keyword);
  return { matches: matches.slice(0, 6), target: exact ?? (matches.length === 1 ? matches[0] : undefined), loaded: stocks.length > 0 };
}
