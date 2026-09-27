"use client";

import type { ProfilingOutput } from "./types";
import { isRecord, isStyleAxes, threeAxisSummary } from "./profiling-rules";
import { assertOk, getSupabaseClient } from "./supabase";
import { STORAGE_KEYS } from "./storage-keys";

export const PROFILE_STORAGE_KEY = STORAGE_KEYS.profile;
export const PROFILE_UPDATED_EVENT = "takealook:profile-updated";

// mode는 로그인한 방식이다. 데모 계정은 환경변수가 있어도 이 브라우저에만 저장한다.
export async function saveProfile(
  profile: ProfilingOutput,
  mode: "demo" | "supabase",
): Promise<void> {
  if (typeof window === "undefined") return;

  const client = mode === "supabase" ? getSupabaseClient() : null;
  if (!client) {
    persistProfile(profile);
    return;
  }

  const { data, error: userAuthError } = await client.auth.getUser();
  assertOk(userAuthError, "로그인 사용자 확인");
  if (!data.user) throw new Error("로그인 후 설문 결과를 저장할 수 있습니다.");

  const now = new Date().toISOString();
  const metadata = data.user.user_metadata;
  const displayName =
    typeof metadata.full_name === "string" && metadata.full_name.trim()
      ? metadata.full_name.trim()
      : profile.user_id;
  const avatarLabel = Array.from(displayName)[0] ?? "";

  const authUserId = data.user.id;
  const { data: existingUser, error: existingUserError } = await client
    .from("users")
    .select("id")
    .eq("auth_user_id", authUserId)
    .maybeSingle();
  assertOk(existingUserError, "기존 사용자 확인");

  // Supabase Auth ID를 최초 DB 사용자 ID로 사용하고, 재설문 시 기존 ID를 재사용한다.
  const userId = (existingUser as { id: string } | null)?.id ?? authUserId;
  const storedProfile: ProfilingOutput = { ...profile, user_id: userId };
  const { error: userError } = await client.from("users").upsert(
    {
      id: userId,
      auth_user_id: authUserId,
      display_name: displayName,
      avatar_label: avatarLabel,
      updated_at: now,
    },
    { onConflict: "auth_user_id" },
  );
  assertOk(userError, "사용자 저장");

  const investor = profile.investor_profile;
  const psychology = profile.psychological_state;
  const freeText = profile.free_text_signal;
  const context = profile.context;
  // 성향 카드 3축(8축 묶음 요약)을 그대로 컬럼에 둔다. SQL로 봐도 화면과 같은 숫자가 나온다.
  if (!profile.style_axes) throw new Error("8축 진단 결과(style_axes)가 없어 저장할 수 없습니다.");
  const summary = threeAxisSummary(profile.style_axes);
  const { error: profileError } = await client.from("ips_profiles").upsert(
    {
      user_id: userId,
      session_id: profile.session_id,
      surveyed_at: profile.timestamp,
      profile_type: investor.profile_type,
      max_risk_tier: investor.profile_type === "stable" ? 4 : 2,
      risk_score: summary.riskTaking,
      fomo_score: summary.sensitivity,
      horizon_score: summary.horizonScore,
      risk_tolerance: investor.risk_tolerance,
      time_horizon_months: investor.time_horizon_months,
      liquidity_need_ratio: investor.liquidity_need_ratio,
      target_return_annual: investor.target_return_annual,
      investment_experience_years: investor.investment_experience_years,
      fomo_index: psychology.fomo_index,
      panic_sell_tendency: psychology.panic_sell_tendency,
      herding_score: psychology.herding_score,
      self_confidence: psychology.self_confidence,
      current_market_anxiety: psychology.current_market_anxiety,
      overheating_caution: psychology.overheating_caution,
      preferred_sectors: profile.constraints.preferred_sectors,
      free_text_raw: freeText.raw_text,
      extracted_signals: freeText.extracted_signals,
      conflict_with_survey: freeText.conflict_with_survey,
      confidence_per_field: profile.confidence_per_field,
      target_ticker: context.target_ticker ?? null,
      investment_amount_krw: context.investment_amount_krw,
      action_intent: context.action_intent,
      market_regime_hint: context.market_regime_hint ?? null,
      benchmark_index: context.benchmark_index ?? null,
      schema_version: profile.meta.schema_version,
      source: profile.meta.source,
      confidence: profile.meta.confidence,
      profile_payload: storedProfile,
      updated_at: now,
    },
    { onConflict: "user_id" },
  );
  assertOk(profileError, "IPS 프로필 저장");

  // 보유 종목(save-holdings.ts)·관심 종목(watchlist.ts)은 각자 저장한다. 성향을 다시 저장해도 건드리지 않는다
  // (전에는 여기서 둘 다 비활성화한 뒤 설문 payload의 빈 목록으로 덮어 다시 진단할 때마다 지워졌다).
  const { error: avoidedResetError } = await client
    .from("avoided_assets")
    .update({ is_active: false, updated_at: now })
    .eq("user_id", userId);
  assertOk(avoidedResetError, "기존 회피 설정 비활성화");
  await upsertAvoidedAssets(profile, userId, now);

  persistProfile(storedProfile);
}

function persistProfile(profile: ProfilingOutput): void {
  window.localStorage.setItem(PROFILE_STORAGE_KEY, JSON.stringify(profile));
  window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
}

async function upsertAvoidedAssets(
  profile: ProfilingOutput,
  userId: string,
  updatedAt: string,
): Promise<void> {
  if (!profile.constraints.avoided_assets.length) return;
  const client = getSupabaseClient();
  if (!client) return;
  const { error } = await client.from("avoided_assets").upsert(
    profile.constraints.avoided_assets.map((assetType) => ({
      user_id: userId,
      asset_type: assetType,
      is_active: true,
      updated_at: updatedAt,
    })),
    { onConflict: "user_id,asset_type" },
  );
  assertOk(error, "회피 설정 저장");
}


export function getSavedProfileSnapshot(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(PROFILE_STORAGE_KEY);
}

export function getServerProfileSnapshot(): null {
  return null;
}

export function subscribeToSavedProfile(onStoreChange: () => void) {
  if (typeof window === "undefined") return () => undefined;
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(PROFILE_UPDATED_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(PROFILE_UPDATED_EVENT, onStoreChange);
  };
}

export function parseSavedProfile(serialized: string | null): ProfilingOutput | null {
  if (!serialized) return null;
  try {
    const parsed: unknown = JSON.parse(serialized);
    return isProfilingOutput(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function isProfilingOutput(value: unknown): value is ProfilingOutput {
  if (!isRecord(value)) return false;
  const investor = value.investor_profile;
  const psychology = value.psychological_state;
  const constraints = value.constraints;
  const meta = value.meta;
  if (
    !isRecord(investor) ||
    !isRecord(psychology) ||
    !isRecord(constraints) ||
    !isRecord(meta)
  ) {
    return false;
  }

  const validRiskFlags = new Set([
    "spac",
    "managed_stock",
    "low_liquidity",
    "penny_stock",
    "high_volatility",
    "preferred_stock",
  ]);
  return (
    typeof value.timestamp === "string" &&
    !Number.isNaN(Date.parse(value.timestamp)) &&
    typeof investor.risk_tolerance === "number" &&
    Number.isFinite(investor.risk_tolerance) &&
    typeof investor.time_horizon_months === "number" &&
    Number.isFinite(investor.time_horizon_months) &&
    (investor.profile_type === "stable" || investor.profile_type === "aggressive") &&
    typeof psychology.fomo_index === "number" &&
    Number.isFinite(psychology.fomo_index) &&
    Array.isArray(constraints.avoided_assets) &&
    constraints.avoided_assets.every(
      (asset) => typeof asset === "string" && validRiskFlags.has(asset),
    ) &&
    (meta.schema_version === "1.0.0" || meta.schema_version === "1.1.0") &&
    (value.style_axes === undefined || isStyleAxes(value.style_axes))
  );
}
