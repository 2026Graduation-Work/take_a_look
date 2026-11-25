export interface SavedHolding {
  code: string;
  name: string;
  quantity: number;
  avgBuyPrice: number | null; // null = 모름
}

export const QUANTITY_DIGITS = 9;
export const PRICE_DIGITS = 12; // 1조 원 미만. 둘 다 안전한 정수 범위(2^53) 안
export function digitsOnly(value: string, maxDigits: number): string {
  return value.normalize("NFKC").split(".")[0].replace(/\D/g, "").slice(0, maxDigits);
}

export function numberDraft(value: string, maxDigits: number): string {
  const normalized = value.normalize("NFKC");
  const plain = normalized.replaceAll(",", "");
  if (!/^\d*(?:\.\d*)?$/.test(plain)) return normalized;
  const [whole, fraction] = plain.split(".");
  if (whole.length > maxDigits) return normalized;
  return groupDigits(whole) + (fraction !== undefined ? "." + fraction : "");
}

export const groupDigits = (digits: string) => digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

// 빈칸 → null, 문자 섞임 → NaN. parseInt처럼 앞 숫자만 읽지 않는다.
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

// 평단 0은 무상증자 등으로 생길 수 있어 허용한다.
export function isValidHolding(value: SavedHolding): boolean {
  return (
    /^[0-9A-Z]{6}$/.test(value.code) &&
    value.name.trim().length > 0 &&
    validQuantity(value.quantity) &&
    validPrice(value.avgBuyPrice)
  );
}

// null = 저장한 적 없음, [] = 전부 지웠음
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

export function costBasis(
  avgBuyPrice: number | null,
  close: number | undefined,
): { price: number; basis: "avg_buy" | "close" } {
  return close !== undefined
    ? { price: close, basis: "close" }
    : { price: avgBuyPrice ?? 0, basis: "avg_buy" };
}

// 0.12 = +12%. 평단을 모르거나(null·0) 최신 종가가 없으면 null.
export function gainRatio(avgBuyPrice: number | null, close: number | undefined): number | null {
  if (!avgBuyPrice || avgBuyPrice <= 0 || close === undefined || !(close > 0)) return null;
  return close / avgBuyPrice - 1;
}

export function mergeImported(rows: SavedHolding[], imported: SavedHolding[]): { rows: SavedHolding[]; replaced: string[] } {
  const incoming = new Map(imported.map((row) => [row.code, row]));
  const replaced = rows.filter((row) => incoming.has(row.code)).map((row) => row.name);
  const kept = rows.map((row) => incoming.get(row.code) ?? row);
  return { rows: [...kept, ...imported.filter((row) => !rows.some(({ code }) => code === row.code))], replaced };
}
