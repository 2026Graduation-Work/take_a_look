"use client";

import Link from "next/link";
import { useState } from "react";
import { useStockSearch } from "./use-stock-search";

export default function StockSearch({ query, onQueryChange }: { query: string; onQueryChange: (value: string) => void }) {
  const { matches, loaded } = useStockSearch(query);
  const [open, setOpen] = useState(false);
  const keyword = query.trim().toLowerCase();

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
        onChange={(event) => {
          onQueryChange(event.target.value);
          setOpen(true); // Esc로 닫은 뒤 다시 입력하면 목록을 다시 연다(#278)
        }}
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
      {open && keyword && loaded && matches.length === 0 && (
        <p role="status" className="glass absolute inset-x-0 top-12 z-50 m-0 rounded-md bg-white/90 px-4 py-3 text-sm text-body">
          찾는 종목이 없어요. 현재는 코스피 종목만 제공해요.
        </p>
      )}
    </div>
  );
}
