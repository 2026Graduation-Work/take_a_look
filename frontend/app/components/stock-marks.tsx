"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { saveNote, setWatched, syncMarks, useMarks } from "@/lib/stock-marks";
import { STOCK_NAMES } from "@/lib/mock-data";
import { formatKstDateTime } from "@/lib/display";
import { useOnboarding } from "./onboarding-provider";
import ConfirmButton from "./confirm-button";
import StepNav from "./step-nav";

const localDate = (iso: string) => formatKstDateTime(iso).slice(0, 10);

function saveErrorMessage(cause: unknown) {
  return cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.";
}

export function useStockMarks() {
  const { mode } = useOnboarding().state;
  const marks = useMarks();
  useEffect(() => {
    void syncMarks(mode, STOCK_NAMES).catch(() => undefined);
  }, [mode]);
  return { mode, ...marks };
}

export default function StockMarks({ code, name }: { code: string; name: string }) {
  const { mode, watchlist, notes } = useStockMarks();
  const watched = watchlist.some((item) => item.code === code);
  const note = notes[code];
  const [draft, setDraft] = useState<string | null>(null);
  const [watchError, setWatchError] = useState("");
  const [memoError, setMemoError] = useState("");
  const [memoPending, setMemoPending] = useState(false);
  const memoRequest = useRef(false);
  const memoInput = useRef<HTMLTextAreaElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const memoTrigger = useRef<HTMLButtonElement>(null);
  const memoTitle = useId();
  const focusEdit = useCallback((node: HTMLButtonElement | null) => {
    if (dialog.current?.open) node?.focus();
  }, []);

  async function toggleWatch() {
    setWatchError("");
    try {
      await setWatched({ code, name }, !watched, mode);
    } catch (cause) {
      setWatchError(saveErrorMessage(cause));
    }
  }

  async function commitMemo(text: string) {
    const activeDialog = dialog.current;
    if (!activeDialog?.open || memoRequest.current) return;
    memoRequest.current = true;
    setMemoPending(true);
    setMemoError("");
    try {
      await saveNote(code, text, mode);
      if (dialog.current === activeDialog) activeDialog.close();
    } catch (cause) {
      if (dialog.current === activeDialog) {
        setMemoError(saveErrorMessage(cause));
        memoInput.current?.focus();
      }
    } finally {
      memoRequest.current = false;
      if (dialog.current === activeDialog) setMemoPending(false);
    }
  }

  function closeMemo() {
    if (!memoRequest.current) dialog.current?.close();
  }

  const watchLabel = watched ? "관심 종목에서 빼기" : "관심 종목에 두기";
  const memoLabel = note ? "판단 메모 보기" : "판단 메모 쓰기";
  const iconButton = "grid size-11 shrink-0 place-items-center rounded-sm text-brand hover:bg-brand-soft";

  return (
    <>
      <div className="flex shrink-0 items-center">
        <button
          type="button"
          aria-label={watchLabel}
          aria-pressed={watched}
          title={watchLabel}
          onClick={toggleWatch}
          className={iconButton}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill={watched ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round">
            <path d="m12 2.8 2.8 5.8 6.4.9-4.6 4.5 1.1 6.4L12 17.4l-5.7 3 1.1-6.4-4.6-4.5 6.4-.9z" />
          </svg>
        </button>
        <button
          ref={memoTrigger}
          type="button"
          aria-label={memoLabel}
          aria-haspopup="dialog"
          title={memoLabel}
          onClick={() => {
            setMemoError("");
            setDraft(note ? null : "");
            dialog.current?.showModal();
          }}
          className={iconButton}
        >
          <span aria-hidden="true" className={`grid h-[18px] w-[15px] content-center gap-[3px] rounded-[3px] border-[1.5px] border-current px-[3px] ${note ? "bg-brand-soft" : ""}`}>
            <span className="h-px bg-current" />
            <span className="h-px w-1 bg-current" />
          </span>
        </button>
      </div>
      {watchError && <p role="alert" className="m-0 basis-full text-xs text-danger">{watchError}</p>}

      <dialog
        ref={dialog}
        aria-labelledby={memoTitle}
        onCancel={(event) => {
          if (memoRequest.current) event.preventDefault();
        }}
        onClose={(event) => {
          if (event.target !== event.currentTarget) return;
          setDraft(null);
          setMemoError("");
          memoTrigger.current?.focus();
        }}
        className="m-auto w-[min(420px,calc(100vw-32px))] rounded-xl bg-white p-0 text-ink shadow-modal backdrop:bg-black/30"
      >
        <div className="flex flex-col gap-4 p-6">
          <div className="flex items-center justify-between gap-4">
            <h2 id={memoTitle} className="text-xl font-semibold">판단 메모</h2>
            <button type="button" onClick={closeMemo} disabled={memoPending} className="btn-text text-sm">닫기</button>
          </div>
          {note && draft === null && (
            <div className="flex flex-col gap-2">
              <span className="text-xs text-muted tabular-nums">지난 메모, {localDate(note.updatedAt)}</span>
              <p className="m-0 whitespace-pre-wrap break-words text-sm text-ink">{note.text}</p>
              <div className="flex gap-4">
                <button ref={focusEdit} type="button" disabled={memoPending} onClick={() => setDraft(note.text)} className="btn-text text-sm">
                  고치기
                </button>
                <ConfirmButton
                  title="이 메모를 지울까요?"
                  message="지운 메모는 되돌릴 수 없어요."
                  confirmLabel="메모 지우기"
                  onConfirm={() => void commitMemo("")}
                  disabled={memoPending}
                  className="btn-text text-sm"
                >
                  지우기
                </ConfirmButton>
              </div>
            </div>
          )}

          {draft !== null && (
            <form
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                if (draft.trim()) void commitMemo(draft);
              }}
            >
              <label className="flex flex-col gap-2 text-xs text-muted">
                내 판단 메모
                <textarea
                  ref={memoInput}
                  value={draft}
                  readOnly={memoPending}
                  onChange={(event) => setDraft(event.target.value)}
                  rows={3}
                  maxLength={1000}
                  autoFocus
                  placeholder="예: 실적 발표(10월 말) 뒤에 다시 보기"
                  className="w-full resize-none rounded-md bg-field px-4 py-3 text-sm text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                />
              </label>
              <StepNav
                onBack={() => {
                  if (memoRequest.current) return;
                  if (!note) {
                    closeMemo();
                    return;
                  }
                  setDraft(null);
                }}
                backLabel="취소"
                backDisabled={memoPending}
                nextType="submit"
                nextLabel="저장"
                nextDisabled={!draft.trim()}
                nextBusy={memoPending}
              />
            </form>
          )}
          {memoPending && draft === null && <p role="status" className="m-0 text-xs text-muted">메모를 지우는 중이에요.</p>}
          {memoError && <p role="alert" className="m-0 text-sm text-danger">{memoError}</p>}
        </div>
      </dialog>
    </>
  );
}

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
          <li key={stock.code} className="flex items-center gap-3 px-5 py-4">
            <span className="min-w-0 flex-1 truncate text-base font-medium">{stock.name}</span>
            <span className="text-xs text-muted tabular-nums">{stock.code}</span>
            <ConfirmButton
              aria-label={`${stock.name} 관심 종목에서 삭제`}
              title={`${stock.name}을(를) 관심 종목에서 삭제할까요?`}
              message="종목 화면에서 언제든 다시 추가할 수 있어요."
              confirmLabel="관심 종목에서 삭제"
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
