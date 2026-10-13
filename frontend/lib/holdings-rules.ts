// 보유 종목 입력 규칙. I/O(save-holdings.ts)와 분리해 두어 단위 테스트에서 바로 쓴다.

export interface SavedHolding {
  code: string;
  name: string;
  quantity: number;
  avgBuyPrice: number | null; // null = 모름(선택 입력). 비중은 기준일 종가로 계산한다
}

// 숫자 입력칸 정리(#278): 숫자만 남기고 자릿수를 자른다. 문자("10abc")·쉼표·지수 표기(1e+21)가 들어갈 수 없다.
// 소수점 아래는 버린다(1.5 → 1, 전에는 점만 지워 15가 됐다). 전각 숫자(１２)는 반각으로 읽는다(NFKC). 페르소나 워크스루 2026-10
export const QUANTITY_DIGITS = 9; // 10억 주 미만
export const PRICE_DIGITS = 12; // 1조 원 미만. 둘 다 안전한 정수 범위(2^53) 안
export function digitsOnly(value: string, maxDigits: number): string {
  return value.normalize("NFKC").split(".")[0].replace(/\D/g, "").slice(0, maxDigits);
}

// 새 종목 입력칸용: 점(소수)을 지우지 않고 보여 준다. 한 글자씩 "1" "." "5"를 쳐도 15가 되지 않고,
// 넣을 때 parseWholeNumber가 NaN으로 막아 "정수로 적어 주세요" 안내가 뜬다(페르소나 워크스루 2026-10).
export function numberDraft(value: string, maxDigits: number): string {
  const [whole, ...fraction] = value.normalize("NFKC").replace(/[^\d.]/g, "").split(".");
  return whole.slice(0, maxDigits) + (fraction.length ? "." + fraction.join("") : "");
}

// 숫자만 있는 문자열 → 정수, 빈칸 → null, 그 밖(문자 섞임) → NaN. parseInt처럼 앞 숫자만 읽지 않는다.
export function parseWholeNumber(value: string): number | null {
  const text = value.replaceAll(",", "").trim();
  if (text === "") return null;
  return /^\d+$/.test(text) ? Number(text) : Number.NaN;
}

// 수량 0은 "보유 안 함"이라 저장하지 않는다. 평단 0은 허용한다(무상증자 등). 평단은 비워 둘 수 있다.
export function isValidHolding(value: SavedHolding): boolean {
  return (
    /^[0-9A-Z]{6}$/.test(value.code) &&
    value.name.trim().length > 0 &&
    Number.isInteger(value.quantity) &&
    value.quantity > 0 &&
    (value.avgBuyPrice === null ||
      (Number.isInteger(value.avgBuyPrice) && value.avgBuyPrice >= 0))
  );
}

// null = 저장한 적 없음, [] = 전부 지웠음. 둘을 구분해야 데모 시드를 되살릴지 판단할 수 있다.
export function parseSavedHoldings(serialized: string | null): SavedHolding[] | null {
  if (!serialized) return null;
  try {
    const parsed: unknown = JSON.parse(serialized);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter(
      (item): item is SavedHolding =>
        typeof item === "object" &&
        item !== null &&
        typeof (item as SavedHolding).code === "string" &&
        typeof (item as SavedHolding).name === "string" &&
        typeof (item as SavedHolding).quantity === "number" &&
        (typeof (item as SavedHolding).avgBuyPrice === "number" ||
          (item as SavedHolding).avgBuyPrice === null),
    );
  } catch {
    return null;
  }
}

// 비중 계산용 단가. 최신 종가가 있으면 평가금액(수량 × 종가), 없으면 평균 매입가(매입금액)로 센다.
export function costBasis(
  avgBuyPrice: number | null,
  close: number | undefined,
): { price: number; basis: "avg_buy" | "close" } {
  return close !== undefined
    ? { price: close, basis: "close" }
    : { price: avgBuyPrice ?? 0, basis: "avg_buy" };
}

// 평단 대비 평가손익 비율(#255). 0.12 = +12%. 평단을 모르거나(null·0) 최신 종가가 없으면 null(미제공).
export function gainRatio(avgBuyPrice: number | null, close: number | undefined): number | null {
  if (!avgBuyPrice || avgBuyPrice <= 0 || close === undefined || !(close > 0)) return null;
  return close / avgBuyPrice - 1;
}
