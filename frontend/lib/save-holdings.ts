"use client";

import type { SupabaseClient } from "@supabase/supabase-js";
import { assertOk, getSupabaseClient } from "./supabase.ts";
import { isValidHolding, type SavedHolding } from "./holdings-rules.ts";
import { STORAGE_KEYS } from "./storage-keys.ts";

export { isValidHolding, parseSavedHoldings } from "./holdings-rules.ts";
export type { SavedHolding } from "./holdings-rules.ts";

// 보유 종목은 사용자가 직접 입력한 값이다(증권사 연동 없음).
// 저장 경로는 설문 프로필(save-profile.ts)과 같은 모양을 따른다:
// 데모는 이 브라우저에만, 로그인 사용자는 Supabase에.
export const HOLDINGS_STORAGE_KEY = STORAGE_KEYS.holdings;
export const HOLDINGS_UPDATED_EVENT = "takealook:holdings-updated";

async function currentAccount(client: SupabaseClient, expectedAuthUserId?: string) {
  const { data, error } = await client.auth.getUser();
  assertOk(error, "로그인 사용자 확인");
  if (!data.user || (expectedAuthUserId && data.user.id !== expectedAuthUserId)) {
    throw new Error("로그인 계정이 바뀌었어요. 새로고침 후 다시 시도해 주세요.");
  }
  return data.user;
}

async function holdingOwner(client: SupabaseClient | null, expectedAuthUserId?: string) {
  if (!client) throw new Error("계정 연결을 확인하지 못했어요. 새로고침 후 다시 시도해 주세요.");
  const authUser = await currentAccount(client, expectedAuthUserId);
  const { data: user, error: userError } = await client.from("users")
    .select("id").eq("auth_user_id", authUser.id).maybeSingle();
  assertOk(userError, "서비스 사용자 확인");
  if (!user) throw new Error("연결된 서비스 사용자 정보가 없습니다.");
  return { client, userId: user.id as string, authUserId: authUser.id };
}

export async function loadAccountHoldings(
  expectedAuthUserId: string,
  client = getSupabaseClient(),
): Promise<SavedHolding[]> {
  const owner = await holdingOwner(client, expectedAuthUserId);
  const { data, error } = await owner.client.from("portfolio_holdings")
    .select("stock_code,quantity,avg_buy_price,stocks(name)")
    .eq("user_id", owner.userId).eq("is_active", true).order("display_order");
  assertOk(error, "보유 종목 조회");
  await currentAccount(owner.client, owner.authUserId);
  const holdings = (data ?? []).map((row) => ({
    code: row.stock_code as string,
    name: (row.stocks as unknown as { name: string } | null)?.name ?? row.stock_code,
    quantity: Number(row.quantity),
    avgBuyPrice: row.avg_buy_price === null ? null : Number(row.avg_buy_price),
  }));
  if (!holdings.every(isValidHolding)) {
    throw new Error("저장된 보유 정보를 읽지 못했어요. 새로고침 후 다시 시도해 주세요.");
  }
  if (typeof window !== "undefined") persistHoldings(holdings);
  return holdings;
}

export async function saveHoldings(
  holdings: SavedHolding[],
  mode: "demo" | "supabase",
  expectedAuthUserId?: string,
  client = getSupabaseClient(),
): Promise<void> {
  if (typeof window === "undefined") return;
  if (!holdings.every(isValidHolding) || new Set(holdings.map(({ code }) => code)).size !== holdings.length) {
    throw new Error("보유 종목의 수량·평균 매입가와 중복 종목을 확인해 주세요.");
  }
  const valid = holdings;

  if (mode === "demo") {
    persistHoldings(valid);
    return;
  }

  const owner = await holdingOwner(client, expectedAuthUserId);
  const db = owner.client;
  const userId = owner.userId;
  const now = new Date().toISOString();

  // stocks에 없는 종목은 FK 제약에 걸린다. 미리 걸러 어떤 종목이 빠졌는지 알려준다.
  const codes = valid.map(({ code }) => code);
  const known = new Set<string>();
  if (codes.length > 0) {
    const { data: stockRows, error: stockError } = await db
      .from("stocks")
      .select("code")
      .in("code", codes);
    assertOk(stockError, "보유 종목 마스터 확인");
    for (const { code } of (stockRows ?? []) as { code: string }[]) known.add(code);
  }
  const unknown = valid.filter(({ code }) => !known.has(code));
  if (unknown.length) {
    throw new Error(`종목 마스터에 없는 종목을 확인해 주세요: ${unknown.map(({ name }) => name).join(", ")}`);
  }

  // 저장 실패가 기존 목록을 비우지 않도록 현재 목록을 먼저 쓴다.
  if (valid.length > 0) {
    const { error: upsertError } = await db.from("portfolio_holdings").upsert(
      valid.map((holding, index) => ({
        user_id: userId,
        stock_code: holding.code,
        quantity: holding.quantity,
        avg_buy_price: holding.avgBuyPrice,
        display_order: index + 1,
        is_active: true,
        updated_at: now,
      })),
      { onConflict: "user_id,stock_code" },
    );
    assertOk(upsertError, "보유 종목 저장");
  }

  let removed = db.from("portfolio_holdings")
    .update({ is_active: false, updated_at: now }).eq("user_id", userId).eq("is_active", true);
  if (codes.length) removed = removed.not("stock_code", "in", `(${codes.join(",")})`);
  const { error: resetError } = await removed;
  if (resetError) throw new Error("추가·수정은 저장됐지만 삭제를 마치지 못했어요. 새로고침 후 보유 목록을 확인해 주세요.");
  await currentAccount(db, owner.authUserId);
  persistHoldings(valid);
}

function persistHoldings(holdings: SavedHolding[]): void {
  window.localStorage.setItem(HOLDINGS_STORAGE_KEY, JSON.stringify(holdings));
  window.dispatchEvent(new Event(HOLDINGS_UPDATED_EVENT));
}


export function getSavedHoldingsSnapshot(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(HOLDINGS_STORAGE_KEY);
}

export function getServerHoldingsSnapshot(): null {
  return null;
}

export function subscribeToSavedHoldings(onStoreChange: () => void) {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(HOLDINGS_UPDATED_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(HOLDINGS_UPDATED_EVENT, onStoreChange);
  };
}

