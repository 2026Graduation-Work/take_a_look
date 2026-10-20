"use client";

// 보유 종목 입력 한 벌: /portfolio와 설문 보유 단계가 같이 쓴다(10/20 읽는 순서 정리). 저장 버튼 줄만 부르는 쪽이 정한다.
// 위에서 아래로: 종목 넣기(검색 + 캡처로 불러오기) → 평균 매입가 설명 한 번 → 캡처 결과 확인 → '넣은 종목 N개' 목록.
// 검색에서 종목을 고르면 바로 목록 맨 위에 행이 생기고 수량 칸으로 간다. 저장 형식(SavedHolding)은 그대로다.

import { useState } from "react";
import GainText from "../components/gain-text";
import ScreenshotImport from "./screenshot-import";
import { useStockOptions, type StockOption } from "./use-stock-options";
import { mergeImported, numberDraft, parseWholeNumber, PRICE_DIGITS, QUANTITY_DIGITS } from "@/lib/holdings-rules";
import type { SavedHolding } from "@/lib/save-holdings";

const field =
  "h-11 w-full rounded-md bg-field px-4 text-sm tabular-nums text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30";
const qtyId = (code: string) => `holding-qty-${code}`;
export const HOLDINGS_INTRO = "가진 주식과 수량을 넣으면 대시보드에 내 포트폴리오가 만들어져요. 증권사 계좌와는 연결하지 않아요.";

export default function HoldingsForm({
  rows,
  onRowsChange,
  catalog,
  supabaseMode,
  closes,
}: {
  rows: SavedHolding[];
  onRowsChange: (rows: SavedHolding[]) => void;
  catalog: StockOption[];
  supabaseMode: boolean;
  closes?: Map<string, { close: number }>;
}) {
  const [keyword, setKeyword] = useState("");
  // 줄 안 수정칸에 친 글자 그대로("1.5"). 점을 보여 주고 저장할 때 막는다(페르소나 워크스루 2026-10)
  const [texts, setTexts] = useState<Record<string, string>>({});
  const { options } = useStockOptions(keyword, supabaseMode, catalog);

  // 후보 목록에서 고르거나 Enter를 누르면 바로 맨 위에 행을 만들고 수량 칸으로 간다. 이미 있으면 그 행 수량 칸으로.
  // 키보드로 치는 중에는 넣지 않는다('LG'를 치다 'LG'가 바로 들어가지 않게)
  function pick(value: string) {
    const found = options.find((item) => item.name === value.trim() || item.code === value.trim());
    if (!found) return;
    if (!rows.some(({ code }) => code === found.code)) onRowsChange([{ ...found, quantity: 0, avgBuyPrice: null }, ...rows]);
    setKeyword("");
    setTimeout(() => document.getElementById(qtyId(found.code))?.focus()); // 새 행이 그려진 뒤
  }

  const update = (code: string, patch: Partial<SavedHolding>) =>
    onRowsChange(rows.map((row) => (row.code === code ? { ...row, ...patch } : row)));
  const dropTexts = (codes: string[]) =>
    setTexts((current) => Object.fromEntries(Object.entries(current).filter(([key]) => !codes.some((code) => key.startsWith(`${code}:`)))));

  const numberInput = (row: SavedHolding, kind: "quantity" | "price") => {
    const key = `${row.code}:${kind}`;
    const value = kind === "quantity" ? (row.quantity > 0 ? String(row.quantity) : "") : row.avgBuyPrice === null ? "" : String(row.avgBuyPrice);
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
          update(row.code, kind === "quantity" ? { quantity: parseWholeNumber(text) ?? 0 } : { avgBuyPrice: parseWholeNumber(text) });
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
                setKeyword(event.target.value);
                // 후보 목록에서 고르면 inputType이 없거나 insertReplacementText다(키보드 입력과 구분)
                const type = (event.nativeEvent as InputEvent).inputType;
                if (!type || type === "insertReplacementText") pick(event.target.value);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                pick(keyword);
              }}
              placeholder="종목명 또는 코드"
              // 페이지 바탕 위라 흰 면(카드 안 입력칸은 회색 field)
              className={field.replace("bg-field", "bg-surface")}
            />
            <datalist id="holding-stock-catalog">
              {options.map((item) => (
                <option key={item.code} value={item.name}>
                  {item.code}
                </option>
              ))}
            </datalist>
          </label>
        }
      >
        {/* 첫 실행은 읽는 도구 24.9MB를 받아 43초~2분(2026-10-20 실측). 용량은 사용자에게 의미가 없어 시간만 적는다 */}
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
          // 열 이름은 PC에서 위에 한 번만, 390에서는 행 안 작은 라벨. 편집 행이라 선 없이 간격으로 나눈다(화면 규칙 v2)
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
