import { kstDay } from "./display.ts";
import { STORAGE_KEYS } from "./storage-keys.ts";

const DAY_MS = 86_400_000;
let inMemoryDay: string | null = null;

export function nextKstMidnight(now: number): number {
  return Date.parse(kstDay(now) + "T00:00:00+09:00") + DAY_MS;
}

export function isTipDismissed(now: number): boolean {
  const today = kstDay(now);
  if (inMemoryDay === today) return true;
  try {
    return window.localStorage.getItem(STORAGE_KEYS.tipDismissedOn) === today;
  } catch {
    return false;
  }
}

export function dismissTipToday(now: number): void {
  const today = kstDay(now);
  try {
    window.localStorage.setItem(STORAGE_KEYS.tipDismissedOn, today);
  } catch {
    inMemoryDay = today;
  }
}
