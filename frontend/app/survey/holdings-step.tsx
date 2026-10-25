"use client";

// 온보딩 2단계: "지금 가진 주식이 있나요?" 보유 종목 화면과 같은 입력(HoldingsForm)을 쓰고 아래 '이전 / 저장하고 시작'만 다르다.
// 저장은 보유 종목 화면과 같은 경로(saveHoldings)를 쓴다.

import { useState } from "react";
import { isValidHolding, saveHoldings, type SavedHolding } from "@/lib/save-holdings";
import { KNOWN_STOCKS, portfolioHoldings } from "@/lib/mock-data";
import HoldingsForm, { HOLDINGS_INTRO } from "../portfolio/holdings-form";
import StepNav from "../components/step-nav";

// 데모 계정은 김민지 예시 보유 종목을 미리 채워 둔다. 평단은 비워 둔다(#278 점검: 옛 예시 평단이
// 실제 최신 종가와 섞여 "평단 대비 +269%" 같은 없는 손익을 보여 줬다). 평단을 넣으면 손익이 보인다.
const DEMO_ROWS: SavedHolding[] = portfolioHoldings.map(({ code, name, quantity }) => ({
  code,
  name,
  quantity,
  avgBuyPrice: null,
}));

export default function HoldingsStep({
  mode,
  onBack,
  onDone,
}: {
  mode: "demo" | "supabase";
  onBack: () => void;
  onDone: () => void;
}) {
  const demo = mode === "demo";
  const [rows, setRows] = useState<SavedHolding[]>(demo ? DEMO_ROWS : []);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function finish() {
    setError("");
    const invalid = rows.find((row) => !isValidHolding(row));
    if (invalid) {
      setError(`${invalid.name}의 수량을 1 이상의 정수로 적어 주세요. 보유하지 않으면 삭제를 눌러 주세요.`);
      return;
    }
    setSaving(true);
    try {
      await saveHoldings(rows, mode);
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
      setSaving(false);
    }
  }

  return (
    // 카드 안 카드가 되지 않게 단계 바깥 상자는 두지 않는다(목록이 흰 면을 가진다, 화면 규칙 v2)
    <section aria-labelledby="holdings-step-title" className="flex flex-col gap-6 py-2">
      <div className="flex flex-col gap-2">
        <h1 id="holdings-step-title" className="text-3xl font-semibold">
          지금 가진 주식이 있나요?
        </h1>
        <p className="m-0 text-sm text-body">{HOLDINGS_INTRO}</p>
        {demo && <p className="m-0 text-xs text-muted">예시로 넣어 뒀어요, 바꿔도 돼요.</p>}
      </div>

      <HoldingsForm rows={rows} onRowsChange={setRows} catalog={KNOWN_STOCKS} supabaseMode={!demo} />

      {error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      )}

      <StepNav
        className="pt-6"
        onBack={onBack}
        backDisabled={saving}
        // 보유가 없는 사람도 그대로 시작할 수 있게(페르소나 워크스루 2026-10 P1 막힘)
        nextLabel={rows.length === 0 ? "보유 없이 시작" : "저장하고 시작"}
        onNext={() => void finish()}
        nextBusy={saving}
      />
    </section>
  );
}
