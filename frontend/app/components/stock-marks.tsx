"use client";

import { useEffect, useState } from "react";
import { saveNote, setWatched, syncMarks, useMarks } from "@/lib/stock-marks";
import { STOCK_NAMES } from "@/lib/mock-data";
import { useOnboarding } from "./onboarding-provider";
import ConfirmButton from "./confirm-button";
import StepNav from "./step-nav";

// ISO(UTC) → 이 기기 기준 날짜 2026.09.27
const localDate = (iso: string) => new Date(iso).toLocaleDateString("sv-SE").replaceAll("-", ".");

// 관심 종목·메모 + 로그인 사용자면 열 때 Supabase 값으로 한 번 맞춘다(조회 실패면 브라우저 값 그대로).
export function useStockMarks() {
  const { mode } = useOnboarding().state;
  const marks = useMarks();
  useEffect(() => {
    void syncMarks(mode, STOCK_NAMES).catch(() => undefined);
  }, [mode]);
  return { mode, ...marks };
}

// 종목 상세 헤더 아래: 관심 종목 켜기/끄기 + 내 판단 메모(지난 메모 · 날짜, 고치기·지우기). 주문과 무관하다.
export default function StockMarks({ code, name }: { code: string; name: string }) {
  const { mode, watchlist, notes } = useStockMarks();
  const watched = watchlist.some((item) => item.code === code);
  const note = notes[code];
  const [draft, setDraft] = useState<string | null>(null); // null = 편집 중 아님
  const [error, setError] = useState("");

  async function run(task: () => Promise<void>) {
    setError("");
    try {
      await task();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    }
  }

  return (
    <section aria-label="관심 종목과 내 판단 메모" className="flex flex-col gap-3 px-1">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          aria-pressed={watched}
          onClick={() => void run(() => setWatched({ code, name }, !watched, mode))}
          className={`min-h-11 rounded-md px-4 text-sm font-medium ${watched ? "bg-brand-soft text-brand" : "bg-track text-body hover:bg-line"}`}
        >
          {watched ? "관심 종목 ✓" : "관심 종목에 두기"}
        </button>
        {!note && draft === null && (
          <button type="button" onClick={() => setDraft("")} className="btn-text text-sm">
            판단 메모 쓰기
          </button>
        )}
      </div>

      {note && draft === null && (
        <div className="surface flex flex-col gap-2 px-5 py-4">
          <span className="text-xs text-muted tabular-nums">지난 메모 · {localDate(note.updatedAt)}</span>
          <p className="m-0 whitespace-pre-wrap text-sm text-ink">{note.text}</p>
          <div className="flex gap-4">
            <button type="button" onClick={() => setDraft(note.text)} className="btn-text text-sm">
              고치기
            </button>
            <ConfirmButton
              title="이 메모를 지울까요?"
              message="지운 메모는 되돌릴 수 없어요."
              confirmLabel="메모 지우기"
              onConfirm={() => void run(() => saveNote(code, "", mode))}
              className="btn-text text-sm"
            >
              지우기
            </ConfirmButton>
          </div>
        </div>
      )}

      {draft !== null && (
        <form
          className="surface flex flex-col gap-3 px-5 py-4"
          onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              await saveNote(code, draft, mode);
              setDraft(null);
            });
          }}
        >
          <label className="flex flex-col gap-1.5 text-xs text-muted">
            내 판단 메모
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={3}
              maxLength={1000}
              autoFocus
              placeholder="예: 실적 발표(10월 말) 뒤에 다시 보기"
              className="w-full resize-none rounded-md bg-field px-4 py-3 text-sm text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
            />
          </label>
          <StepNav onBack={() => setDraft(null)} backLabel="취소" nextType="submit" nextLabel="저장" nextDisabled={!draft.trim()} />
        </form>
      )}
      <p className="m-0 text-xs text-muted">나만 보는 기록이에요. 여기서 누른 것으로 주문이 나가지 않아요.</p>
      {error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}

// 보유 종목 편집 화면의 관심 종목 목록: 보고 뺄 수 있다(추가는 종목 상세에서). 0개면 숨긴다.
export function WatchlistEditor() {
  const { mode, watchlist } = useStockMarks();
  const [error, setError] = useState("");
  if (watchlist.length === 0) return null;
  return (
    <section aria-labelledby="watchlist-title" className="flex flex-col gap-2">
      <h2 id="watchlist-title" className="px-1 text-xl font-semibold">
        관심 종목
      </h2>
      <ul className="group-list m-0 list-none p-0">
        {watchlist.map((stock) => (
          <li key={stock.code} className="flex items-center gap-3 px-5 py-3.5">
            <span className="min-w-0 flex-1 truncate text-base font-medium">{stock.name}</span>
            <span className="text-xs text-muted tabular-nums">{stock.code}</span>
            <ConfirmButton
              aria-label={`${stock.name} 관심 종목에서 삭제`}
              title={`${stock.name}을(를) 관심 종목에서 삭제할까요?`}
              message="종목 화면에서 언제든 다시 추가할 수 있어요."
              confirmLabel="관심 종목 삭제"
              onConfirm={() =>
                void setWatched(stock, false, mode).catch((cause: unknown) =>
                  setError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요."),
                )
              }
              className="btn-remove"
            >
              삭제
            </ConfirmButton>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="m-0 px-1 text-sm text-danger">
          {error}
        </p>
      )}
    </section>
  );
}
