import { STORAGE_KEYS } from "./storage-keys.ts";

type ReadingHistory =
  | { status: "new" }
  | { status: "dismissed" }
  | { status: "completed"; code: string; hinted: string[] };

const volatileHistory = new Map<string, ReadingHistory>();
const stockCode = /^[A-Z0-9]{6}$/;

export function readingHistoryKey(mode: "demo" | "supabase", userId: string) {
  return mode === "demo"
    ? STORAGE_KEYS.demoReadingHistory
    : `${STORAGE_KEYS.accountReadingHistory}.${userId}`;
}

export function readReadingHistory(key: string): ReadingHistory {
  const volatile = volatileHistory.get(key);
  if (volatile) return volatile;
  try {
    const value = JSON.parse(window.localStorage.getItem(key) ?? "null");
    if (value?.status === "dismissed") return { status: "dismissed" };
    if (
      value?.status === "completed" &&
      typeof value.code === "string" && stockCode.test(value.code) &&
      Array.isArray(value.hinted) && value.hinted.length <= 2 &&
      value.hinted.every((code: unknown) => typeof code === "string" && stockCode.test(code) && code !== value.code) &&
      new Set(value.hinted).size === value.hinted.length
    ) {
      return { status: "completed", code: value.code, hinted: value.hinted };
    }
  } catch {
    return { status: "new" };
  }
  return { status: "new" };
}

function writeReadingHistory(key: string, history: ReadingHistory) {
  try {
    window.localStorage.setItem(key, JSON.stringify(history));
    volatileHistory.delete(key);
  } catch {
    volatileHistory.set(key, history);
  }
}

export function recordReadingOutcome(key: string, code: string, status: "dismissed" | "completed") {
  const history = readReadingHistory(key);
  if (history.status === "completed" || history.status === status) return;
  writeReadingHistory(key, status === "dismissed" ? { status } : { status, code, hinted: [] });
}

export function clearDemoReadingHistory() {
  const key = STORAGE_KEYS.demoReadingHistory;
  volatileHistory.delete(key);
  try {
    window.localStorage.removeItem(key);
  } catch {
    return;
  }
}
