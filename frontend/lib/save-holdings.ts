"use client";

import { assertOk, getSupabaseClient } from "./supabase";
import { isValidHolding, type SavedHolding } from "./holdings-rules";
import { STORAGE_KEYS } from "./storage-keys";

export { isValidHolding, parseSavedHoldings } from "./holdings-rules";
export type { SavedHolding } from "./holdings-rules";

// 보유 종목은 사용자가 직접 입력한 값이다(증권사 연동 없음).
// 저장 경로는 설문 프로필(save-profile.ts)과 같은 모양을 따른다:
// 데모는 이 브라우저에만, 로그인 사용자는 Supabase에.
export const HOLDINGS_STORAGE_KEY = STORAGE_KEYS.holdings;
export const HOLDINGS_UPDATED_EVENT = "takealook:holdings-updated";

export async function saveHoldings(
  holdings: SavedHolding[],
  mode: "demo" | "supabase",
): Promise<void> {
  if (typeof window === "undefined") return;
  const valid = holdings.filter(isValidHolding);

  const client = mode === "supabase" ? getSupabaseClient() : null;
  if (!client) {
    persistHoldings(valid);
    return;
  }

  const { data, error: authError } = await client.auth.getUser();
  assertOk(authError, "로그인 사용자 확인");
  if (!data.user) throw new Error("로그인 후 보유 종목을 저장할 수 있습니다.");

  const { data: appUser, error: appUserError } = await client
    .from("users")
    .select("id")
    .eq("auth_user_id", data.user.id)
    .maybeSingle();
  assertOk(appUserError, "서비스 사용자 확인");
  if (!appUser) throw new Error("연결된 서비스 사용자 정보가 없습니다.");

  const userId = (appUser as { id: string }).id;
  const now = new Date().toISOString();

  // stocks에 없는 종목은 FK 제약에 걸린다. 미리 걸러 어떤 종목이 빠졌는지 알려준다.
  const codes = valid.map(({ code }) => code);
  const known = new Set<string>();
  if (codes.length > 0) {
    const { data: stockRows, error: stockError } = await client
      .from("stocks")
      .select("code")
      .in("code", codes);
    assertOk(stockError, "보유 종목 마스터 확인");
    for (const { code } of (stockRows ?? []) as { code: string }[]) known.add(code);
  }
  const unknown = valid.filter(({ code }) => !known.has(code));
  const storable = valid.filter(({ code }) => known.has(code));

  // 지운 종목이 남지 않도록 전체를 비활성화한 뒤 현재 목록만 되살린다.
  const { error: resetError } = await client
    .from("portfolio_holdings")
    .update({ is_active: false, updated_at: now })
    .eq("user_id", userId);
  assertOk(resetError, "기존 보유 종목 비활성화");

  if (storable.length > 0) {
    const { error: upsertError } = await client.from("portfolio_holdings").upsert(
      storable.map((holding, index) => ({
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

  persistHoldings(storable);

  if (unknown.length > 0) {
    throw new Error(
      `종목 마스터에 없어 저장하지 못한 종목이 있습니다: ${unknown
        .map(({ name, code }) => `${name}(${code})`)
        .join(", ")}`,
    );
  }
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

