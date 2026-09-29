"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import DisclaimerFooter from "../components/disclaimer-footer";
import SiteHeader from "../components/site-header";
import { WatchlistEditor } from "../components/stock-marks";
import { useOnboarding } from "../components/onboarding-provider";
import { useStockOptions } from "./use-stock-options";
import {
  getSavedHoldingsSnapshot,
  getServerHoldingsSnapshot,
  isValidHolding,
  parseSavedHoldings,
  saveHoldings,
  subscribeToSavedHoldings,
  type SavedHolding,
} from "@/lib/save-holdings";
import type { InvestorProfileSummary, MarketStatus, PortfolioHolding } from "@/lib/types";

interface HoldingsEditorProps {
  profile: InvestorProfileSummary;
  marketStatus: MarketStatus;
  catalog: { code: string; name: string }[];
  demoHoldings: PortfolioHolding[];
}

type Draft = { code: string; name: string; quantity: string; avgBuyPrice: string };

const EMPTY_DRAFT: Draft = { code: "", name: "", quantity: "", avgBuyPrice: "" };

// 비워 두면 null(모름). 평균 매입가만 선택 입력이다.
function toOptionalInt(value: string): number | null {
  return value.trim() === "" ? null : toInt(value);
}

function toInt(value: string): number {
  const parsed = Number.parseInt(value.replaceAll(",", "").trim(), 10);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function formatWon(value: number): string {
  return value.toLocaleString("ko-KR");
}

export default function HoldingsEditor({
  profile,
  marketStatus,
  catalog,
  demoHoldings,
}: HoldingsEditorProps) {
  const { state: onboardingState } = useOnboarding();
  const supabaseMode = onboardingState.mode === "supabase";

  const savedSnapshot = useSyncExternalStore(
    subscribeToSavedHoldings,
    getSavedHoldingsSnapshot,
    getServerHoldingsSnapshot,
  );
  const saved = parseSavedHoldings(savedSnapshot);

  // 저장된 목록이 있으면 그것이 정답이다. 없을 때만 데모 시드를 보여 준다.
  // (로그인 사용자는 데모 시드를 받지 않으므로 빈 목록에서 시작한다.)
  const initial: SavedHolding[] =
    saved ??
    (supabaseMode
      ? []
      : demoHoldings.map(({ code, name, quantity, avgBuyPrice }) => ({
          code,
          name,
          quantity,
          avgBuyPrice,
        })));

  const [rows, setRows] = useState<SavedHolding[]>(initial);
  const [baseline, setBaseline] = useState<SavedHolding[]>(initial); // 마지막으로 저장된 목록
  const dirty = JSON.stringify(rows) !== JSON.stringify(baseline);

  // 새로고침·탭 닫기 때만 막는다. ponytail: 앱 안 링크 이동은 못 막음, 필요해지면 라우터 가드 추가
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState(""); // 종목 추가 시트 안 오류
  const [saveError, setSaveError] = useState(""); // 저장 오류
  const sheetRef = useRef<HTMLDialogElement>(null);

  function openSheet() {
    setError("");
    sheetRef.current?.showModal();
  }

  const { options, match } = useStockOptions(draft.name, supabaseMode, catalog);

  function addRow() {
    setError("");
    const code = match?.code ?? draft.code.trim();
    const name = match?.name ?? draft.name.trim();
    const candidate: SavedHolding = {
      code,
      name,
      quantity: toInt(draft.quantity),
      avgBuyPrice: toOptionalInt(draft.avgBuyPrice),
    };

    if (!match) {
      setError("목록에 있는 종목을 골라 주세요. 종목명을 입력하면 후보가 나옵니다.");
      return;
    }
    if (rows.some((row) => row.code === candidate.code)) {
      setError(`${name}은(는) 이미 목록에 있습니다. 아래에서 수량을 고쳐 주세요.`);
      return;
    }
    if (!isValidHolding(candidate)) {
      setError("수량은 1 이상의 정수로, 평균 매입가는 비워 두거나 0 이상의 정수로 입력해 주세요.");
      return;
    }

    setRows((current) => [...current, candidate]);
    setDraft(EMPTY_DRAFT);
    setStatus("idle");
    sheetRef.current?.close();
  }

  function updateRow(code: string, patch: Partial<SavedHolding>) {
    setRows((current) =>
      current.map((row) => (row.code === code ? { ...row, ...patch } : row)),
    );
    setStatus("idle");
  }

  function removeRow(code: string) {
    setRows((current) => current.filter((row) => row.code !== code));
    setStatus("idle");
  }

  async function submit() {
    setSaveError("");
    setStatus("saving");
    try {
      await saveHoldings(rows, onboardingState.mode);
      setBaseline(rows);
      setStatus("saved");
    } catch (cause) {
      setStatus("idle");
      setSaveError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    }
  }

  // 합계는 평균 매입가를 입력한 종목만 더한다(모르는 종목은 현재가 기준이라 섞지 않는다)
  const total = rows.reduce((sum, row) => sum + row.quantity * (row.avgBuyPrice ?? 0), 0);

  const field =
    "h-11 w-full rounded-md bg-field px-3.5 text-sm tabular-nums text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30";

  return (
    <div className="w-full">
      <SiteHeader profile={profile} marketStatus={marketStatus} activePage="portfolio" />

      <main className="mx-auto box-border flex w-full max-w-[720px] flex-col gap-6 px-4 pb-12 pt-8 sm:px-8">
        <div className="flex flex-col gap-1 px-1">
          <h1 className="text-3xl font-semibold">보유 종목</h1>
          <p className="m-0 text-sm text-body">
            직접 입력한 수량으로 대시보드의 보유 종목 맵을 만들어요. 증권사 계좌와 연결하지 않아요.
          </p>
        </div>

        {rows.length === 0 ? (
          <div className="surface flex flex-col items-center gap-4 px-6 py-12 text-center">
            <p className="m-0 text-sm text-body">아직 등록한 종목이 없어요.</p>
            <button type="button" onClick={openSheet} className="btn-primary">
              종목 추가
            </button>
          </div>
        ) : (
          <section aria-label="등록한 종목" className="flex flex-col gap-2">
            <div className="flex items-baseline justify-between px-1">
              <span className="eyebrow tabular-nums">
                {rows.length}종목 · 매입금액 합계 {formatWon(total)}원
              </span>
              <button type="button" onClick={openSheet} className="btn-text text-xs">
                종목 추가
              </button>
            </div>
            <ul className="group-list m-0 list-none p-0">
              {rows.map((row) => (
                <li key={row.code} className="grid grid-cols-2 items-center gap-3 px-5 py-3.5 sm:grid-cols-[1.4fr_1fr_1fr_auto]">
                  <div className="col-span-2 flex items-baseline gap-2 sm:col-span-1">
                    <span className="text-base font-medium">{row.name}</span>
                    <span className="text-xs text-muted tabular-nums">{row.code}</span>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-2xs text-muted">수량(주)</span>
                    <input
                      inputMode="numeric"
                      aria-label={`${row.name} 수량`}
                      value={String(row.quantity)}
                      onChange={(event) => updateRow(row.code, { quantity: toInt(event.target.value) })}
                      className="h-11 w-full rounded-sm bg-field px-3 text-sm tabular-nums outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                    />
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-2xs text-muted">평균 매입가(원)</span>
                    <input
                      inputMode="numeric"
                      aria-label={`${row.name} 평균 매입가`}
                      value={row.avgBuyPrice === null ? "" : String(row.avgBuyPrice)}
                      placeholder="모름 · 현재가 기준"
                      onChange={(event) => updateRow(row.code, { avgBuyPrice: toOptionalInt(event.target.value) })}
                      className="h-11 w-full rounded-sm bg-field px-3 text-sm tabular-nums outline-none focus:bg-white focus:ring-2 focus:ring-brand/30"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => removeRow(row.code)}
                    className="col-span-2 min-h-11 justify-self-start text-xs font-medium text-danger hover:underline sm:col-span-1 sm:justify-self-end"
                  >
                    삭제
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {saveError && (
          <p role="alert" className="m-0 px-1 text-sm text-danger">
            {saveError}
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-3 px-1">
          {dirty ? (
            <span className="mr-auto flex items-center gap-2 text-xs text-body">
              저장하지 않은 변경이 있어요
              <button type="button" onClick={() => setRows(baseline)} className="btn-text min-h-11 text-xs">
                되돌리기
              </button>
            </span>
          ) : (
            <span className="mr-auto text-xs text-muted">
              {supabaseMode ? "내 계정에 저장돼요" : "데모 계정이라 이 브라우저에만 저장돼요"}
            </span>
          )}
          {status === "saved" && (
            <span role="status" className="text-sm text-body">
              저장했어요. <Link href="/">대시보드에서 보기</Link>
            </span>
          )}
          <button type="button" onClick={submit} disabled={status === "saving"} className="btn-primary">
            {status === "saving" ? "저장 중…" : "저장"}
          </button>
        </div>

        <WatchlistEditor />
      </main>

      {/* 종목 추가 시트 — 네이티브 dialog라 포커스 가두기·Esc 닫기를 브라우저가 맡는다 */}
      <dialog
        ref={sheetRef}
        aria-labelledby="add-sheet-title"
        className="m-auto w-[min(440px,calc(100vw-32px))] rounded-xl bg-white p-0 text-ink shadow-modal backdrop:bg-black/30"
      >
        <form
          method="dialog"
          onSubmit={(event) => {
            event.preventDefault();
            addRow();
          }}
          className="flex flex-col gap-4 p-6"
        >
          <h2 id="add-sheet-title" className="text-lg font-semibold">
            종목 추가
          </h2>
          <label className="flex flex-col gap-1.5">
            <span className="text-xs text-muted">종목명 또는 코드</span>
            <input
              list="stock-catalog"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder="삼성전자"
              autoFocus
              className={field}
            />
            <datalist id="stock-catalog">
              {options.map((item) => (
                <option key={item.code} value={item.name}>
                  {item.code}
                </option>
              ))}
            </datalist>
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-muted">수량(주)</span>
              <input
                inputMode="numeric"
                value={draft.quantity}
                onChange={(event) => setDraft({ ...draft, quantity: event.target.value })}
                placeholder="10"
                className={field}
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-muted">평균 매입가(원, 선택)</span>
              <input
                inputMode="numeric"
                value={draft.avgBuyPrice}
                onChange={(event) => setDraft({ ...draft, avgBuyPrice: event.target.value })}
                placeholder="모르면 비워 두세요"
                className={field}
              />
            </label>
          </div>
          {error && (
            <p role="alert" className="m-0 text-sm text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => sheetRef.current?.close()} className="btn-secondary">
              취소
            </button>
            <button type="submit" className="btn-primary">
              추가
            </button>
          </div>
        </form>
      </dialog>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}
