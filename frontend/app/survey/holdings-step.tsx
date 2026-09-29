"use client";

// 온보딩 2단계: "지금 가진 주식이 있나요?" 수량은 필수, 평균 매입가는 선택(모르면 비워 두기).
// 저장은 보유 종목 화면과 같은 경로(saveHoldings)를 쓴다.

import { useState } from "react";
import { isValidHolding, saveHoldings, type SavedHolding } from "@/lib/save-holdings";
import { KNOWN_STOCKS, portfolioHoldings } from "@/lib/mock-data";
import { useStockOptions } from "../portfolio/use-stock-options";
import StepNav from "../components/step-nav";

// 데모 계정은 김민지 예시 보유 종목을 미리 채워 둔다.
const DEMO_ROWS: SavedHolding[] = portfolioHoldings.map(({ code, name, quantity, avgBuyPrice }) => ({
  code,
  name,
  quantity,
  avgBuyPrice,
}));

const field =
  "h-11 w-full rounded-md bg-field px-3.5 text-sm tabular-nums text-ink outline-none focus:bg-white focus:ring-2 focus:ring-brand/30";

function parseCount(value: string): number {
  const parsed = Number.parseInt(value.replaceAll(",", "").trim(), 10);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

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
  const [answer, setAnswer] = useState<"yes" | null>(demo ? "yes" : null);
  const [rows, setRows] = useState<SavedHolding[]>(demo ? DEMO_ROWS : []);
  const [keyword, setKeyword] = useState("");
  const [quantity, setQuantity] = useState("");
  const [avgPrice, setAvgPrice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const { options, match } = useStockOptions(keyword, !demo, KNOWN_STOCKS);

  function add() {
    setError("");
    if (!match) {
      setError("목록에 있는 종목을 골라 주세요. 이름을 입력하면 후보가 나와요.");
      return;
    }
    if (rows.some((row) => row.code === match.code)) {
      setError(`${match.name}은(는) 이미 넣었어요.`);
      return;
    }
    const candidate: SavedHolding = {
      ...match,
      quantity: parseCount(quantity),
      avgBuyPrice: avgPrice.trim() === "" ? null : parseCount(avgPrice),
    };
    if (!isValidHolding(candidate)) {
      setError("수량은 1 이상의 정수로 적어 주세요. 평균 매입가는 비워 둬도 돼요.");
      return;
    }
    setRows((current) => [...current, candidate]);
    setKeyword("");
    setQuantity("");
    setAvgPrice("");
  }

  async function finish(next: SavedHolding[]) {
    setSaving(true);
    setError("");
    try {
      await saveHoldings(next, mode);
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "저장하지 못했어요. 잠시 뒤 다시 눌러 주세요.");
      setSaving(false);
    }
  }

  return (
    <section aria-labelledby="holdings-step-title" className="surface flex flex-col gap-6 px-6 py-8 sm:px-10">
      <div className="flex flex-col gap-1.5">
        <h1 id="holdings-step-title" className="text-3xl font-semibold">
          지금 가진 주식이 있나요?
        </h1>
        <p className="m-0 text-sm text-body">대시보드에서 내 종목의 오늘 신호를 먼저 보여 드려요. 증권사 계좌와 연결하지 않아요.</p>
      </div>

      {answer === null ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <button type="button" onClick={() => setAnswer("yes")} className="btn-primary min-h-14 text-base">
            있어요
          </button>
          <button type="button" onClick={() => void finish([])} disabled={saving} className="btn-secondary min-h-14 text-base">
            아직 없어요
          </button>
        </div>
      ) : (
        <>
          {demo && <p className="m-0 text-xs text-muted">예시로 넣어 뒀어요, 바꿔도 돼요.</p>}
          {rows.length > 0 && (
            <ul className="group-list m-0 list-none bg-field p-0">
              {rows.map((row) => (
                <li key={row.code} className="flex items-center gap-3 px-4 py-3">
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{row.name}</span>
                    <span className="block text-xs text-muted tabular-nums">
                      {row.quantity}주 ·{" "}
                      {row.avgBuyPrice === null ? "평균 매입가 모름(현재가 기준)" : `평균 ${row.avgBuyPrice.toLocaleString("ko-KR")}원`}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => setRows((current) => current.filter(({ code }) => code !== row.code))}
                    className="btn-remove"
                    aria-label={`${row.name} 삭제`}
                  >
                    삭제
                  </button>
                </li>
              ))}
            </ul>
          )}

          <form
            onSubmit={(event) => {
              event.preventDefault();
              add();
            }}
            className="flex flex-col gap-3"
          >
            <label className="flex flex-col gap-1.5">
              <span className="text-xs text-muted">종목 검색</span>
              <input
                list="onboarding-stock-catalog"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="종목명 또는 코드"
                className={field}
              />
              <datalist id="onboarding-stock-catalog">
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
                <input inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="10" className={field} />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-xs text-muted">평균 매입가(원, 선택)</span>
                <input
                  inputMode="numeric"
                  value={avgPrice}
                  onChange={(event) => setAvgPrice(event.target.value)}
                  placeholder="모르면 비워 두세요"
                  className={field}
                />
              </label>
            </div>
            <button type="submit" className="btn-secondary self-start">
              종목 넣기
            </button>
          </form>

          {error && (
            <p role="alert" className="m-0 text-sm text-danger">
              {error}
            </p>
          )}

          <StepNav
            className="border-t border-line-soft pt-6"
            onBack={() => setAnswer(null)}
            backDisabled={saving}
            nextLabel={saving ? "저장 중" : "저장하고 시작"}
            onNext={() => void finish(rows)}
            nextDisabled={saving || rows.length === 0}
          />
        </>
      )}

      {answer === null && error && (
        <p role="alert" className="m-0 text-sm text-danger">
          {error}
        </p>
      )}
      {answer === null && <StepNav className="border-t border-line-soft pt-6" onBack={onBack} backDisabled={saving} />}
    </section>
  );
}
