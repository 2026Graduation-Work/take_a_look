"use client";

import { BusyLabel } from "@/app/components/waiting";
import { useEffect, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import DisclaimerFooter from "../components/disclaimer-footer";
import SiteHeader from "../components/site-header";
import { WatchlistEditor } from "../components/stock-marks";
import { useOnboarding } from "../components/onboarding-provider";
import HoldingsForm, { HOLDINGS_INTRO } from "./holdings-form";
import { loadLatestCloses, type LatestCloses } from "@/lib/latest-closes";
import { getSupabaseClient } from "@/lib/supabase";
import { holdingInputError } from "@/lib/holdings-rules";
import {
  getSavedHoldingsSnapshot,
  getServerHoldingsSnapshot,
  isValidHolding,
  loadAccountHoldings,
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


export default function HoldingsEditor(props: HoldingsEditorProps) {
  const { state } = useOnboarding();
  return <AccountHoldingsEditor key={`${state.mode}:${state.userId}`} {...props} />;
}

function AccountHoldingsEditor({
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

  const initial: SavedHolding[] = supabaseMode ? [] :
    saved ?? demoHoldings.map(({ code, name, quantity }) => ({
          code,
          name,
          quantity,
          avgBuyPrice: null,
        }));

  const [rows, setRows] = useState<SavedHolding[]>(initial);
  const codeKey = rows.map(({ code }) => code).join(",");
  const [closes, setCloses] = useState<LatestCloses>(new Map());
  useEffect(() => {
    let active = true;
    void loadLatestCloses(getSupabaseClient(), codeKey ? codeKey.split(",") : []).then((next) => active && setCloses(next));
    return () => {
      active = false;
    };
  }, [codeKey]);
  const [baseline, setBaseline] = useState<SavedHolding[]>(initial);
  const dirty = JSON.stringify(rows) !== JSON.stringify(baseline);

  // 새로고침·탭 닫기 때만 막는다. ponytail: 앱 안 링크 이동은 못 막음, 필요해지면 라우터 가드 추가
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const [status, setStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [saveError, setSaveError] = useState("");
  const [loaded, setLoaded] = useState(!supabaseMode);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  const [formVersion, setFormVersion] = useState(0);
  useEffect(() => {
    let active = true;
    const request = supabaseMode
      ? loadAccountHoldings(onboardingState.userId!)
      : Promise.resolve(parseSavedHoldings(getSavedHoldingsSnapshot()));
    void request.then((next) => {
      if (!active) return;
      if (next !== null) {
        setRows(next);
        setBaseline(next);
      }
      setLoaded(true);
    }).catch((cause: unknown) => {
      if (active) setLoadError(cause instanceof Error ? cause.message : "보유 목록을 읽지 못했어요. 다시 시도해 주세요.");
    });
    return () => { active = false; };
  }, [supabaseMode, onboardingState.userId, reload]);

  const changeRows = (next: SavedHolding[]) => {
    setRows(next);
    setStatus("idle");
  };

  async function submit() {
    if (!loaded || status === "saving") return;
    setSaveError("");
    const empty = rows.find(({ quantity }) => quantity === 0);
    if (empty) {
      setSaveError(`${empty.name}의 수량을 1 이상으로 적어 주세요. 보유하지 않으면 삭제를 눌러 주세요.`);
      return;
    }
    const invalid = rows.find((row) => !isValidHolding(row));
    if (invalid) {
      setSaveError(holdingInputError(invalid));
      return;
    }
    setStatus("saving");
    try {
      await saveHoldings(rows, onboardingState.mode, onboardingState.userId);
      setBaseline(rows);
      setStatus("saved");
    } catch (cause) {
      setStatus("idle");
      setSaveError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
    }
  }

  return (
    <div className="w-full">
      <SiteHeader profile={profile} marketStatus={marketStatus} />

      <main className="page pb-12 pt-6">
      <div className="page-narrow flex flex-col gap-6">
        <div className="flex flex-col gap-1 px-1">
          <h1 className="text-3xl font-semibold">보유 종목</h1>
          <p className="m-0 text-sm text-body">{HOLDINGS_INTRO}</p>
        </div>

        {!loaded ? (
          <div className="surface flex flex-col gap-4 px-6 py-8">
            {loadError ? <>
              <p role="alert" className="m-0 text-sm text-danger">{loadError}</p>
              <button type="button" className="btn-secondary self-end" onClick={() => { setLoadError(""); setReload((value) => value + 1); }}>다시 불러오기</button>
            </> : <p role="status" className="m-0 text-sm text-body">저장된 보유 종목을 불러오는 중이에요.</p>}
          </div>
        ) : (
          <HoldingsForm key={formVersion} rows={rows} onRowsChange={changeRows} catalog={catalog} supabaseMode={supabaseMode} closes={closes} />
        )}

        {saveError && (
          <p role="alert" className="m-0 px-1 text-sm text-danger">
            {saveError}
          </p>
        )}

        <div className="flex flex-col items-stretch gap-2 px-1 sm:flex-row sm:items-center sm:justify-end sm:gap-3">
          {dirty ? (
            <span className="flex items-center gap-2 text-xs text-body sm:mr-auto">
              저장하지 않은 변경이 있어요
              <button type="button" onClick={() => { setRows(baseline); setFormVersion((value) => value + 1); }} className="btn-text min-h-11 text-xs">
                되돌리기
              </button>
            </span>
          ) : (
            <span className="text-xs text-muted sm:mr-auto">
              {supabaseMode ? "내 계정에 저장돼요." : "데모 계정이라 이 브라우저에만 저장돼요."}
            </span>
          )}
          {status === "saved" && (
            <span role="status" className="text-sm text-body">
              저장했어요. <Link href="/">대시보드에서 보기</Link>
            </span>
          )}
          <button type="button" onClick={submit} disabled={!loaded || status === "saving"} aria-busy={status === "saving" || undefined} className="btn-primary w-full sm:w-auto">
            <BusyLabel busy={status === "saving"}>저장</BusyLabel>
          </button>
        </div>

        <WatchlistEditor />
      </div>
      </main>

      <DisclaimerFooter fixed={false} />
    </div>
  );
}
