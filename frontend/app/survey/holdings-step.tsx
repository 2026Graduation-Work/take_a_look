"use client";

import { useState } from "react";
import { isValidHolding, saveHoldings, type SavedHolding } from "@/lib/save-holdings";
import { KNOWN_STOCKS, portfolioHoldings } from "@/lib/mock-data";
import HoldingsForm, { HOLDINGS_INTRO } from "../portfolio/holdings-form";
import StepNav from "../components/step-nav";
import { holdingInputError } from "@/lib/holdings-rules";

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
      setError(holdingInputError(invalid));
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
        nextLabel={rows.length === 0 ? "보유 없이 시작" : "저장하고 시작"}
        onNext={() => void finish()}
        nextBusy={saving}
      />
    </section>
  );
}
