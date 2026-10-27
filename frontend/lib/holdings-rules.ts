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

// 의미가 보존되는 전각 숫자와 쉼표만 정리한다. 잘못된 입력은 지우거나 자르지 않고 검증까지 보존한다.
export function numberDraft(value: string, maxDigits: number): string {
  const normalized = value.normalize("NFKC");
  const plain = normalized.replaceAll(",", "");
  if (!/^\d*(?:\.\d*)?$/.test(plain)) return normalized;
  const [whole, fraction] = plain.split(".");
  if (whole.length > maxDigits) return normalized;
  return groupDigits(whole) + (fraction !== undefined ? "." + fraction : "");
}

// "1234567" → "1,234,567"(앞자리 0도 그대로 둔다)
export const groupDigits = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

// 숫자만 있는 문자열 → 정수, 빈칸 → null, 그 밖(문자 섞임) → NaN. parseInt처럼 앞 숫자만 읽지 않는다.
export function parseWholeNumber(value: string, maxDigits = Number.POSITIVE_INFINITY): number | null {
  const text = value.replaceAll(",", "").trim();
  if (text === "") return null;
  const parsed = Number(text);
  return /^\d+$/.test(text) && text.length <= maxDigits && Number.isSafeInteger(parsed) ? parsed : Number.NaN;
}

const validQuantity = (value: number) => Number.isSafeInteger(value) && value > 0 && value < 10 ** QUANTITY_DIGITS;
const validPrice = (value: number | null) => value === null || (Number.isSafeInteger(value) && value >= 0 && value < 10 ** PRICE_DIGITS);

export function holdingInputError(value: SavedHolding): string {
  if (!validQuantity(value.quantity)) return `${value.name}의 수량은 1~999,999,999주의 정수로 적어 주세요. 보유하지 않으면 삭제를 눌러 주세요.`;
  if (!validPrice(value.avgBuyPrice)) return `${value.name}의 평균 매입가는 0~999,999,999,999원의 정수로 적거나 비워 주세요.`;
  return `${value.name}의 종목 정보를 확인해 주세요.`;
}

// 수량 0은 "보유 안 함"이라 저장하지 않는다. 평단 0은 허용한다(무상증자 등). 평단은 비워 둘 수 있다.
export function isValidHolding(value: SavedHolding): boolean {
  return (
    /^[0-9A-Z]{6}$/.test(value.code) &&
    value.name.trim().length > 0 &&
    validQuantity(value.quantity) &&
    validPrice(value.avgBuyPrice)
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

// 스크린샷에서 읽은 목록을 편집 중인 목록에 합친다. 이미 있는 종목은 새 값으로 바꾸고(이름을 돌려줘 화면에 표시), 없으면 뒤에 붙인다.
export function mergeImported(rows: SavedHolding[], imported: SavedHolding[]): { rows: SavedHolding[]; replaced: string[] } {
  const incoming = new Map(imported.map((row) => [row.code, row]));
  const replaced = rows.filter((row) => incoming.has(row.code)).map((row) => row.name);
  const kept = rows.map((row) => incoming.get(row.code) ?? row);
  return { rows: [...kept, ...imported.filter((row) => !rows.some(({ code }) => code === row.code))], replaced };
}
