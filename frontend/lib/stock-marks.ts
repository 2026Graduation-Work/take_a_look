"use client";

// 관심 종목과 내 판단 메모. 사용자가 직접 남긴 표시일 뿐 주문·종목 제거와 무관하다(HITL).
// 화면은 늘 이 브라우저의 저장값(localStorage)을 읽는다. 데모는 그것이 원본이고,
// 로그인 사용자는 Supabase(watchlist, stock_notes)에 쓰고 읽어 온 값을 여기에 비춰 둔다.
// stock_notes 마이그레이션(0006)이 아직 적용되지 않은 DB에서는 메모만 브라우저에 둔다.

import type { SupabaseClient } from "@supabase/supabase-js";
import { useMemo, useSyncExternalStore } from "react";
import { getSupabaseClient } from "./supabase";
import { STORAGE_KEYS } from "./storage-keys";
import type { OnboardingState } from "./auth";

export interface WatchedStock {
  code: string;
  name: string;
}
export interface StockNote {
  text: string;
  updatedAt: string; // ISO
}
type Mode = OnboardingState["mode"];

const EVENT = "takealook:marks-updated";

function read<T>(key: string, fallback: T): T {
  try {
    return (JSON.parse(window.localStorage.getItem(key) ?? "null") as T) ?? fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  window.localStorage.setItem(key, JSON.stringify(value));
  window.dispatchEvent(new Event(EVENT));
}

const readWatchlist = (): WatchedStock[] => read(STORAGE_KEYS.watchlist, []);
const readNotes = (): Record<string, StockNote> => read(STORAGE_KEYS.stockNotes, {});

// useSyncExternalStore용: 두 키의 문자열을 그대로 스냅숏으로 쓴다(같은 값이면 같은 문자열).
function getMarksSnapshot(): string {
  if (typeof window === "undefined") return "";
  return `${window.localStorage.getItem(STORAGE_KEYS.watchlist)}|${window.localStorage.getItem(STORAGE_KEYS.stockNotes)}`;
}
const getServerMarksSnapshot = () => "";
function subscribeToMarks(onChange: () => void) {
  window.addEventListener("storage", onChange);
  window.addEventListener(EVENT, onChange);
  return () => {
    window.removeEventListener("storage", onChange);
    window.removeEventListener(EVENT, onChange);
  };
}

type QueryError = { code?: string; message: string } | null;
// 테이블이 아직 없음(PostgREST 스키마 캐시에 없음 / Postgres undefined_table)
const missingTable = (error: QueryError) => error?.code === "PGRST205" || error?.code === "42P01";

function assertResult(error: QueryError, operation: string) {
  if (error) throw new Error(`${operation} 실패: ${error.message}. 잠시 뒤 다시 시도해 주세요.`);
}

async function appUser(mode: Mode): Promise<{ client: SupabaseClient; userId: string } | null> {
  const client = mode === "supabase" ? getSupabaseClient() : null;
  if (!client) return null;
  const { data, error } = await client.auth.getUser();
  assertResult(error, "로그인 사용자 확인");
  if (!data.user) return null;
  const { data: row, error: userError } = await client
    .from("users")
    .select("id")
    .eq("auth_user_id", data.user.id)
    .maybeSingle();
  assertResult(userError, "서비스 사용자 확인");
  return row ? { client, userId: (row as { id: string }).id } : null;
}

// 로그인 사용자: Supabase 값을 브라우저에 비춘다. 종목 이름은 화면이 아는 목록(names)에서 찾는다.
export async function syncMarks(mode: Mode, names: Record<string, string>): Promise<void> {
  const user = await appUser(mode);
  if (!user) return;
  const { client, userId } = user;
  const [watchResult, noteResult] = await Promise.all([
    client.from("watchlist").select("stock_code").eq("user_id", userId).eq("is_active", true).order("display_order"),
    client.from("stock_notes").select("stock_code,note,updated_at").eq("user_id", userId),
  ]);
  assertResult(watchResult.error, "관심 종목 조회");
  write(
    STORAGE_KEYS.watchlist,
    ((watchResult.data ?? []) as { stock_code: string }[]).map(({ stock_code }) => ({
      code: stock_code,
      name: names[stock_code] ?? stock_code,
    })),
  );
  if (missingTable(noteResult.error)) return; // 0006 적용 전: 브라우저 메모 유지
  assertResult(noteResult.error, "판단 메모 조회");
  write(
    STORAGE_KEYS.stockNotes,
    Object.fromEntries(
      ((noteResult.data ?? []) as { stock_code: string; note: string; updated_at: string }[]).map((row) => [
        row.stock_code,
        { text: row.note, updatedAt: row.updated_at },
      ]),
    ),
  );
}

export async function setWatched(stock: WatchedStock, watched: boolean, mode: Mode): Promise<void> {
  const current = readWatchlist().filter(({ code }) => code !== stock.code);
  const next = watched ? [...current, stock] : current;
  const user = await appUser(mode);
  if (user) {
    const { error } = await user.client.from("watchlist").upsert(
      {
        user_id: user.userId,
        stock_code: stock.code,
        display_order: next.length,
        is_active: watched,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id,stock_code" },
    );
    assertResult(error, "관심 종목 저장");
  }
  write(STORAGE_KEYS.watchlist, next);
}

// text가 비면 지운다.
export async function saveNote(code: string, text: string, mode: Mode): Promise<void> {
  const trimmed = text.trim().slice(0, 1000);
  const notes = readNotes();
  const updatedAt = new Date().toISOString();
  const user = await appUser(mode);
  if (user) {
    const table = user.client.from("stock_notes");
    const { error } = trimmed
      ? await table.upsert(
          { user_id: user.userId, stock_code: code, note: trimmed, updated_at: updatedAt },
          { onConflict: "user_id,stock_code" },
        )
      : await table.delete().eq("user_id", user.userId).eq("stock_code", code);
    if (!missingTable(error)) assertResult(error, "판단 메모 저장");
  }
  if (trimmed) notes[code] = { text: trimmed, updatedAt };
  else delete notes[code];
  write(STORAGE_KEYS.stockNotes, notes);
}

export function useMarks(): { watchlist: WatchedStock[]; notes: Record<string, StockNote> } {
  const snapshot = useSyncExternalStore(subscribeToMarks, getMarksSnapshot, getServerMarksSnapshot);
  return useMemo(
    () => (snapshot ? { watchlist: readWatchlist(), notes: readNotes() } : { watchlist: [], notes: {} }),
    [snapshot],
  );
}
