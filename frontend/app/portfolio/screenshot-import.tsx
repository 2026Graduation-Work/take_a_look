"use client";

// 스크린샷으로 보유 종목 불러오기(보유 종목 화면과 온보딩 보유 단계가 같이 쓴다).
// 사진은 이 기기 안(웹 워커)에서만 읽고 어디에도 보내지 않는다. 읽은 값은 사용자가 확인하고 고친 뒤
// '목록에 넣기'를 눌러야 편집 목록에 들어가고, 저장은 기존 저장 버튼이 한다.

import { useRef, useState } from "react";
import { getSupabaseClient } from "@/lib/supabase";
import { init, recognize, toolLoaded } from "@/lib/holdings-ocr/recognize";
import { mergeResults, parseHoldings, type CheckField, type ParsedHolding, type StockRef } from "@/lib/holdings-ocr/parse";
import { isValidHolding, numberDraft, parseWholeNumber, PRICE_DIGITS, QUANTITY_DIGITS, type SavedHolding } from "@/lib/holdings-rules";

type Row = ParsedHolding & { quantityText: string; priceText: string };
type Phase = "idle" | "downloading" | "reading" | "review" | "empty" | "failed";

const PAGE = 1000; // Supabase 한 번에 돌려주는 최대 행 수

// 종목 마스터 전체(이름 대조용). 연결이 없거나 실패하면 화면이 가진 후보 목록으로 대신한다.
let masterCache: Promise<StockRef[]> | null = null;
async function loadMaster(fallback: StockRef[]): Promise<StockRef[]> {
  const client = getSupabaseClient();
  if (!client) return fallback;
  masterCache ??= (async () => {
    const all: StockRef[] = [];
    for (let from = 0; ; from += PAGE) {
      const { data, error } = await client.from("stocks").select("code,name").order("code").range(from, from + PAGE - 1);
      if (error) throw error;
      all.push(...(data as StockRef[]));
      if (!data || data.length < PAGE) return all;
    }
  })();
  try {
    const master = await masterCache;
    return master.length ? master : fallback;
  } catch {
    masterCache = null;
    return fallback;
  }
}

const toRow = (holding: ParsedHolding): Row => ({
  ...holding,
  quantityText: holding.quantity === null ? "" : String(holding.quantity),
  priceText: holding.avgBuyPrice === null ? "" : String(holding.avgBuyPrice),
});

function CheckMark({ show }: { show: boolean }) {
  if (!show) return null;
  // 주황은 점만, 글자는 본문색(DESIGN.md 색 역할표)
  return (
    <span className="flex items-center gap-1 text-2xs text-body">
      <span aria-hidden className="size-1.5 rounded-full bg-caution-mark" />
      확인 필요
    </span>
  );
}

export default function ScreenshotImport({
  catalog,
  onAdd,
}: {
  catalog: StockRef[];
  onAdd: (rows: SavedHolding[]) => string[]; // 이미 있어서 새 값으로 바꾼 종목 이름
}) {
  const input = useRef<HTMLInputElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [rows, setRows] = useState<Row[]>([]);
  const [unsupported, setUnsupported] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [progress, setProgress] = useState({ done: 0, total: 0 });

  async function read(files: File[]) {
    if (!files.length) return;
    setError("");
    setNotice("");
    try {
      // 처음 한 번은 읽는 도구(약 25MB)를 받는다. 받는 양을 알 수 없어 단계만 보인다
      if (!toolLoaded()) {
        setPhase("downloading");
        await init();
      }
      setPhase("reading");
      setProgress({ done: 0, total: files.length });
      const master = await loadMaster(catalog);
      const results = [];
      for (const file of files) {
        results.push(parseHoldings(await recognize(file), master));
        setProgress({ done: results.length, total: files.length });
      }
      const merged = mergeResults(results);
      setRows(merged.holdings.map(toRow));
      setUnsupported(merged.unsupported);
      setPhase(merged.holdings.length ? "review" : "empty");
    } catch {
      setPhase("failed");
    }
  }

  function edit(code: string, field: "quantity" | "avgBuyPrice", text: string) {
    setRows((current) =>
      current.map((row) => {
        if (row.code !== code) return row;
        const check = row.check.filter((item: CheckField) => item !== field); // 고친 칸은 확인한 것으로 본다
        return field === "quantity"
          ? { ...row, check, quantityText: text, quantity: parseWholeNumber(text) }
          : { ...row, check, priceText: text, avgBuyPrice: parseWholeNumber(text), avgComputed: false };
      }),
    );
  }

  function add() {
    const holdings: SavedHolding[] = rows.map(({ code, name, quantity, avgBuyPrice }) => ({ code, name, quantity: quantity ?? Number.NaN, avgBuyPrice }));
    const invalid = holdings.find((holding) => !isValidHolding(holding));
    if (invalid) {
      setError(`${invalid.name}의 수량은 1 이상의 정수로, 평균 매입가는 비워 두거나 정수로 적어 주세요.`);
      return;
    }
    const replaced = onAdd(holdings);
    setNotice(
      `${holdings.length}종목을 목록에 넣었어요.${replaced.length ? ` ${replaced.join(", ")}은(는) 새 값으로 바꿨어요.` : ""} 저장을 눌러야 저장돼요.`,
    );
    setRows([]);
    setUnsupported([]);
    setPhase("idle");
  }

  return (
    <section aria-label="스크린샷으로 불러오기" className="flex flex-col gap-3">
      <div className="flex flex-col gap-3">
        <button type="button" onClick={() => input.current?.click()} disabled={phase === "reading" || phase === "downloading"} className="btn-secondary self-start">
          스크린샷으로 불러오기
        </button>
        <input
          ref={input}
          type="file"
          accept="image/*"
          multiple
          hidden
          aria-label="보유 종목 화면 캡처 파일"
          onChange={(event) => {
            void read([...(event.target.files ?? [])]);
            event.target.value = ""; // 같은 파일을 다시 골라도 읽게
          }}
        />
        {/* 첫 실행은 읽는 도구 24.9MB를 받아 43초~2분(2026-10-20 실측). 용량은 사용자에게 의미가 없어 시간만 적는다 */}
        <p className="m-0 max-w-2xl px-1 text-xs text-muted">
          증권 앱의 보유 종목 화면을 캡처해 올리면 종목과 수량을 채워 드려요. 사진은 이 기기 안에서만 읽고 어디에도 보내지 않아요. 처음 한 번은 1분쯤 걸려요.
        </p>
      </div>

      <div aria-live="polite" className="flex flex-col gap-2">
        {phase === "downloading" && (
          <div role="status" className="flex flex-col gap-2">
            <p className="m-0 text-sm text-body">읽는 도구를 내려받고 있어요. 다음부터는 바로 읽어요.</p>
            <progress aria-label="읽는 도구 내려받기" className="h-1 w-full max-w-xs accent-brand-accent" />
          </div>
        )}
        {phase === "reading" && (
          <p role="status" className="m-0 text-sm text-body tabular-nums">
            사진을 읽고 있어요{progress.total > 1 && ` (${progress.done}/${progress.total})`}
          </p>
        )}
        {phase === "empty" && (
          <p role="alert" className="m-0 text-sm text-body">
            종목을 찾지 못했어요. 보유 종목이 보이는 화면을 다시 올리거나 직접 입력해 주세요.
          </p>
        )}
        {phase === "failed" && (
          <p role="alert" className="m-0 text-sm text-danger">
            사진을 읽지 못했어요. 인터넷 연결을 확인하고 다시 올리거나 직접 입력해 주세요.
          </p>
        )}
        {notice && phase === "idle" && <p role="status" className="m-0 text-sm text-body">{notice}</p>}
      </div>

      {phase === "review" && (
        // 입력칸(회색)이 보이도록 흰 카드 위에(보유 목록 편집 카드와 같은 모양)
        <div className="surface mt-2 flex flex-col gap-3 px-5 py-5">
          <h3 className="m-0 text-base font-semibold">읽은 내용을 확인해 주세요</h3>
          {/* 칸마다 바로 고친다. 이름은 마스터에서 맞춘 것이라 틀렸으면 그 줄을 삭제하고 직접 입력한다 */}
          <ul className="m-0 flex list-none flex-col gap-3 p-0" aria-label="읽은 보유 종목">
            {rows.map((row) => (
              <li key={row.code} className="grid grid-cols-2 items-start gap-x-3 gap-y-1 sm:grid-cols-[1.4fr_1fr_1fr_auto]">
                <div className="col-span-2 flex flex-wrap items-baseline gap-x-2 sm:col-span-1 sm:pt-7">
                  <span className="text-sm font-medium">{row.name}</span>
                  <span className="text-xs text-muted tabular-nums">{row.code}</span>
                  <CheckMark show={row.check.includes("name")} />
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-2xs text-muted">수량(주)</span>
                  <input
                    inputMode="numeric"
                    aria-label={`${row.name} 수량`}
                    value={row.quantityText}
                    onChange={(event) => edit(row.code, "quantity", numberDraft(event.target.value, QUANTITY_DIGITS))}
                    className="h-11 w-full rounded-sm bg-field px-3 text-sm tabular-nums outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                  />
                  <CheckMark show={row.check.includes("quantity")} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-2xs text-muted">평균 매입가(원)</span>
                  <input
                    inputMode="numeric"
                    aria-label={`${row.name} 평균 매입가`}
                    value={row.priceText}
                    placeholder="모름, 현재가 기준"
                    onChange={(event) => edit(row.code, "avgBuyPrice", numberDraft(event.target.value, PRICE_DIGITS))}
                    className="h-11 w-full rounded-sm bg-field px-3 text-sm tabular-nums outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                  />
                  <CheckMark show={row.check.includes("avgBuyPrice")} />
                  {row.avgComputed && <span className="text-2xs text-muted">계산한 값</span>}
                </label>
                <button
                  type="button"
                  onClick={() => setRows((current) => current.filter(({ code }) => code !== row.code))}
                  aria-label={`${row.name} 삭제`}
                  className="btn-remove col-span-2 justify-self-start sm:col-span-1 sm:mt-6 sm:justify-self-end"
                >
                  삭제
                </button>
              </li>
            ))}
          </ul>
          {unsupported.length > 0 && (
            <p className="m-0 text-xs text-muted">다루지 않는 종목(ETF, 해외 주식 등): {unsupported.join(", ")}</p>
          )}
          {rows.some(({ avgComputed }) => avgComputed) && (
            <p className="m-0 text-xs text-muted">계산한 값은 평가금액에서 평가손익을 빼고 수량으로 나눈 평균 매입가예요.</p>
          )}
          {error && <p role="alert" className="m-0 text-sm text-danger">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setPhase("idle")} className="btn-secondary">
              취소
            </button>
            <button type="button" onClick={add} disabled={rows.length === 0} className="btn-secondary">
              목록에 넣기
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
