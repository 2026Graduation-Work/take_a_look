"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { KNOWN_STOCKS } from "@/lib/mock-data";
import { getSupabaseClient } from "@/lib/supabase";

type StockOption = { code: string; name: string };

// 종목 마스터(code·name, 약 950행)를 처음 검색할 때 한 번만 받아 브라우저에서 거른다. 입력마다 조회하지 않는다.
// ponytail: PostgREST 한 번에 최대 1000행. 종목 마스터가 1000행을 넘으면 range로 나눠 받는다.
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

export default function StockSearch({ query, onQueryChange }: { query: string; onQueryChange: (value: string) => void }) {
  const [stocks, setStocks] = useState<StockOption[]>([]);
  const [open, setOpen] = useState(false);
  const keyword = query.trim().toLowerCase();

  useEffect(() => {
    if (!keyword) return;
    let active = true;
    void loadMaster().then((list) => active && setStocks(list));
    return () => {
      active = false;
    };
  }, [keyword]);

  const matches = keyword
    ? stocks.filter(({ code, name }) => name.toLowerCase().includes(keyword) || code.startsWith(keyword)).slice(0, 6)
    : [];

  return (
    <div
      className="relative w-full min-w-0 sm:max-w-[280px]"
      onFocus={() => setOpen(true)}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => event.key === "Escape" && setOpen(false)}
    >
      <input
        type="search"
        value={query}
        onChange={(event) => onQueryChange(event.target.value)}
        placeholder="종목명 또는 코드 검색"
        aria-label="종목 검색"
        className="box-border h-11 w-full min-w-0 rounded-md bg-track px-4 text-sm text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
      />
      {open && matches.length > 0 && (
        <ul aria-label="종목 검색 결과" className="glass absolute inset-x-0 top-12 z-50 m-0 list-none overflow-hidden rounded-md bg-white/90 p-0 py-1">
          {matches.map(({ code, name }) => (
            <li key={code}>
              <Link
                href={`/stocks/${code}`}
                className="flex min-h-11 items-center justify-between gap-3 px-4 text-sm text-ink hover:bg-field hover:no-underline"
              >
                <span className="truncate">{name}</span>
                <span className="flex-none text-xs text-muted tabular-nums">{code}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
