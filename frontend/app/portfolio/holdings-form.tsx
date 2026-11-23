"use client";

import { useEffect, useRef, useState } from "react";
import { loadStockCatalog } from "@/lib/stock-catalog";
import GainText from "../components/gain-text";
import ScreenshotImport from "./screenshot-import";
import { useStockOptions, type StockOption } from "./use-stock-options";
import { groupDigits, mergeImported, numberDraft, parseWholeNumber, PRICE_DIGITS, QUANTITY_DIGITS } from "@/lib/holdings-rules";
import type { SavedHolding } from "@/lib/save-holdings";

const field =
  "h-11 w-full rounded-md bg-field px-4 text-sm tabular-nums text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30";
const qtyId = (code: string) => `holding-qty-${code}`;
export const HOLDINGS_INTRO = "가진 주식과 수량을 넣으면 대시보드에 내 포트폴리오가 만들어져요. 증권사 계좌와는 연결하지 않아요.";

export default function HoldingsForm({
  rows,
  onRowsChange,
  catalog,
  closes,
}: {
  rows: SavedHolding[];
  onRowsChange: (rows: SavedHolding[]) => void;
  catalog: StockOption[];
  supabaseMode: boolean;
  closes?: Map<string, { close: number }>;
}) {
  const [keyword, setKeyword] = useState("");
  const [texts, setTexts] = useState<Record<string, string>>({});
  const { options } = useStockOptions(keyword, catalog);
  const [searchError, setSearchError] = useState("");
  const [selecting, setSelecting] = useState(false);
  const selectionVersion = useRef(0);
  const currentRows = useRef(rows);
  useEffect(() => { currentRows.current = rows; }, [rows]);

  async function pick(value: string) {
    if (!value.trim()) return;
    const version = ++selectionVersion.current;
    setSelecting(true);
    setSearchError("");
    try {
      const list = options.some((item) => item.name === value.trim() || item.code === value.trim()) ? options : await loadStockCatalog();
      if (version !== selectionVersion.current) return;
      const found = list.find((item) => item.name === value.trim() || item.code === value.trim());
      if (!found) { setSearchError("찾는 종목이 없어요. 종목명이나 코드를 확인하고 후보에서 골라 주세요."); return; }
      if (!currentRows.current.some(({ code }) => code === found.code)) onRowsChange([{ ...found, quantity: 0, avgBuyPrice: null }, ...currentRows.current]);
      setKeyword("");
      setTimeout(() => document.getElementById(qtyId(found.code))?.focus());
    } catch (cause) {
      if (version === selectionVersion.current) setSearchError(cause instanceof Error ? cause.message : "종목 목록을 불러오지 못했어요. 다시 검색해 주세요.");
    } finally {
      if (version === selectionVersion.current) setSelecting(false);
    }
  }

  const update = (code: string, patch: Partial<SavedHolding>) =>
    onRowsChange(rows.map((row) => (row.code === code ? { ...row, ...patch } : row)));
  const dropTexts = (codes: string[]) =>
    setTexts((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !codes.some((code) => key.startsWith(`${code}:`)))));

  const numberInput = (row: SavedHolding, kind: "quantity" | "price") => {
    const key = `${row.code}:${kind}`;
    const value = kind === "quantity" ? (row.quantity > 0 ? groupDigits(String(row.quantity)) : "") : row.avgBuyPrice === null ? "" : groupDigits(String(row.avgBuyPrice));
    return (
      <input
        id={kind === "quantity" ? qtyId(row.code) : undefined}
        inputMode="numeric"
        aria-label={`${row.name} ${kind === "quantity" ? "수량" : "평균 매입가"}`}
        value={texts[key] ?? value}
        placeholder={kind === "price" ? "모름" : undefined}
        onChange={(event) => {
          const text = numberDraft(event.target.value, kind === "quantity" ? QUANTITY_DIGITS : PRICE_DIGITS);
          setTexts((current) => ({ ...current, [key]: text }));
          update(row.code, kind === "quantity" ? { quantity: parseWholeNumber(text, QUANTITY_DIGITS) ?? 0 } : { avgBuyPrice: parseWholeNumber(text, PRICE_DIGITS) });
        }}
        className={field}
      />
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <ScreenshotImport
        catalog={catalog}
        onAdd={(imported) => {
          const merged = mergeImported(rows, imported);
          onRowsChange(merged.rows);
          dropTexts(imported.map(({ code }) => code));
          return merged.replaced;
        }}
        leading={
          <label className="flex flex-col gap-2">
            <span className="text-xs text-muted">종목 검색</span>
            <input
              list="holding-stock-catalog"
              value={keyword}
              onChange={(event) => {
                selectionVersion.current += 1;
                setSelecting(false);
                setSearchError("");
                setKeyword(event.target.value);
                // 후보 목록에서 고르면 inputType이 없거나 insertReplacementText다(키보드 입력과 구분)
                const type = (event.nativeEvent as InputEvent).inputType;
                if ((!type || type === "insertReplacementText") && options.some((item) => item.name === event.target.value || item.code === event.target.value)) void pick(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                void pick(keyword);
              }}
              placeholder="종목명 또는 코드"
              className={field.replace("bg-field", "bg-surface")}
            />
            <datalist id="holding-stock-catalog">
              {options.map((item) => (
                <option key={item.code} value={item.name}>
                  {item.code}
                </option>
              ))}
            </datalist>
            {selecting && <span role="status" className="text-xs text-muted">종목 목록을 불러오는 중이에요.</span>}
            {searchError && <span role="alert" className="text-xs text-danger">{searchError}</span>}
          </label>
        }
      >
        {/* 첫 실행은 읽는 도구 24.9MB를 받아 43초~2분 걸린다(2026-10-20 실측) */}
        <div className="flex flex-col gap-1 px-1 text-xs text-muted">
          <p className="m-0">평균 매입가를 넣으면 산 가격보다 몇 % 오르거나 내렸는지 보여요. 몰라도 괜찮아요.</p>
          <p className="m-0">캡처는 이 기기 안에서만 읽고 어디에도 보내지 않아요. 처음 한 번은 1분쯤 걸려요.</p>
        </div>
      </ScreenshotImport>

      <section aria-labelledby="holding-list-title" className="flex flex-col gap-2">
        <h2 id="holding-list-title" className="m-0 px-1 text-base font-semibold">
          넣은 종목 {rows.length}개
        </h2>
        {rows.length === 0 ? (
          <p className="m-0 px-1 text-sm text-muted">아직 넣은 종목이 없어요. 위에서 검색하거나 캡처를 불러오세요.</p>
        ) : (
          <div className="surface flex flex-col gap-2 py-2">
            <div aria-hidden className="hidden grid-cols-[1.4fr_1fr_1fr_4rem] gap-3 px-5 pt-2 text-2xs text-muted sm:grid">
              <span>종목</span>
              <span>수량(주)</span>
              <span>평균 매입가(원, 선택)</span>
              <span />
            </div>
            <ul aria-label="넣은 종목" className="m-0 flex list-none flex-col gap-2 p-0">
              {rows.map((row) => (
                <li key={row.code} className="grid grid-cols-2 items-center gap-3 px-5 py-3 sm:grid-cols-[1.4fr_1fr_1fr_4rem]">
                  <div className="col-span-2 flex flex-wrap items-baseline gap-x-2 sm:col-span-1">
                    <span className="text-base font-medium">{row.name}</span>
                    <span className="text-xs text-muted tabular-nums">{row.code}</span>
                    {closes && (
                      <span className="basis-full">
                        <GainText avgBuyPrice={row.avgBuyPrice} close={closes.get(row.code)?.close} />
                      </span>
                    )}
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-2xs text-muted sm:hidden">수량(주)</span>
                    {numberInput(row, "quantity")}
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-2xs text-muted sm:hidden">평균 매입가(원, 선택)</span>
                    {numberInput(row, "price")}
                  </label>
                  <button
                    type="button"
                    onClick={() => {
                      onRowsChange(rows.filter(({ code }) => code !== row.code));
                      dropTexts([row.code]);
                    }}
                    aria-label={`${row.name} 삭제`}
                    className="btn-remove col-span-2 justify-self-end sm:col-span-1"
                  >
                    삭제
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}
