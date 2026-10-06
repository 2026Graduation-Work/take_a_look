"use client";

import type { User } from "@supabase/supabase-js";
import {
  PROFILE_STORAGE_KEY,
  PROFILE_UPDATED_EVENT,
  parseSavedProfile,
} from "./save-profile";
import { isRecord } from "./profiling-rules";
import { getSupabaseClient, isSupabaseConfigured } from "./supabase";
import { STORAGE_KEYS } from "./storage-keys";

const DEMO_SESSION_STORAGE_KEY = STORAGE_KEYS.demoSession;
export const AUTH_UPDATED_EVENT = "takealook:auth-updated";

export type OnboardingStatus =
  | "loading"
  | "signed_out"
  | "needs_survey"
  | "ready"
  | "error";

export interface OnboardingState {
  status: OnboardingStatus;
  mode: "demo" | "supabase";
  userId?: string;
  displayName?: string;
  error?: string;
}

interface DemoSession {
  userId: string;
  displayName: string;
  signedInAt: string;
}

// 세션이 정해지기 전(로딩 중)의 표시용 모드. 실제 모드는 로그인한 방식으로 정한다.
export function getAuthMode(): OnboardingState["mode"] {
  return readDemoSession() ? "demo" : isSupabaseConfigured() ? "supabase" : "demo";
}

export async function resolveOnboardingState(): Promise<OnboardingState> {
  // 데모 계정으로 들어왔으면 환경변수가 있어도 데모로 둔다(Supabase를 부르지 않는다).
  if (readDemoSession()) return resolveDemoOnboardingState();
  const client = getSupabaseClient();
  if (!client) return { status: "signed_out", mode: "demo" };

  const { data: sessionData, error: sessionError } = await client.auth.getSession();
  if (sessionError) {
    throw new Error(`로그인 세션 확인 실패: ${sessionError.message}`);
  }
  if (!sessionData.session) {
    clearSavedProfile();
    return { status: "signed_out", mode: "supabase" };
  }

  const { data: userData, error: userError } = await client.auth.getUser();
  if (userError || !userData.user) {
    throw new Error(
      `로그인 사용자 확인 실패: ${userError?.message ?? "사용자 정보가 없습니다."}`,
    );
  }

  return resolveSupabaseProfile(userData.user);
}

async function resolveSupabaseProfile(user: User): Promise<OnboardingState> {
  const client = getSupabaseClient();
  if (!client) return { status: "signed_out", mode: "supabase" };

  const { data: appUser, error: appUserError } = await client
    .from("users")
    .select("id, display_name")
    .eq("auth_user_id", user.id)
    .maybeSingle();
  if (appUserError) {
    throw new Error(`사용자 프로필 확인 실패: ${appUserError.message}`);
  }

  const displayName = displayNameFor(user, appUser?.display_name);
  if (!appUser) {
    clearSavedProfile();
    return {
      status: "needs_survey",
      mode: "supabase",
      userId: user.id,
      displayName,
    };
  }

  const { data: profile, error: profileError } = await client
    .from("ips_profiles")
    .select("profile_payload")
    .eq("user_id", appUser.id)
    .maybeSingle();
  if (profileError) {
    throw new Error(`투자 성향 확인 실패: ${profileError.message}`);
  }
  if (!profile) {
    clearSavedProfile();
    return {
      status: "needs_survey",
      mode: "supabase",
      userId: user.id,
      displayName,
    };
  }

  syncSavedProfile(profile.profile_payload);
  return {
    status: "ready",
    mode: "supabase",
    userId: user.id,
    displayName,
  };
}

function resolveDemoOnboardingState(): OnboardingState {
  const session = readDemoSession();
  if (!session) return { status: "signed_out", mode: "demo" };

  const profile = parseSavedProfile(
    window.localStorage.getItem(PROFILE_STORAGE_KEY),
  );
  return {
    status: profile ? "ready" : "needs_survey",
    mode: "demo",
    userId: session.userId,
    displayName: session.displayName,
  };
}

export function startDemoSession(): void {
  clearSavedProfile(); // 이전 계정의 설문 결과가 데모 화면에 섞이지 않게
  const session: DemoSession = {
    userId: "demo_minji",
    displayName: "김민지",
    signedInAt: new Date().toISOString(),
  };
  window.localStorage.setItem(DEMO_SESSION_STORAGE_KEY, JSON.stringify(session));
  window.dispatchEvent(new Event(AUTH_UPDATED_EVENT));
}


// 비밀번호 가입.
// Supabase에서 이메일 확인이 켜져 있으면 세션 없이 돌아오고, 확인 메일을 눌러야 로그인된다.
export async function signUpWithPassword(
  email: string,
  password: string,
  name: string,
): Promise<{ needsEmailConfirmation: boolean }> {
  const client = getSupabaseClient();
  if (!client) throw new Error("이 배포에는 계정 기능이 아직 연결되지 않았습니다.");
  const { data, error } = await client.auth.signUp({
    email,
    password,
    options: { emailRedirectTo: `${window.location.origin}/login`, data: { full_name: name } },
  });
  if (error) throw new Error(`가입 실패: ${koreanAuthError(error.message)}`);
  return { needsEmailConfirmation: !data.session };
}

export async function signInWithPassword(email: string, password: string): Promise<void> {
  const client = getSupabaseClient();
  if (!client) throw new Error("이 배포에는 계정 기능이 아직 연결되지 않았습니다.");
  const { error } = await client.auth.signInWithPassword({ email, password });
  if (error) throw new Error(`로그인 실패: ${koreanAuthError(error.message)}`);
}

// Supabase Auth 영문 오류 중 자주 나오는 것만 옮긴다. 나머지는 원문을 그대로 보여 준다.
export function koreanAuthError(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes("invalid login credentials")) return "이메일 또는 비밀번호가 맞지 않아요.";
  if (lower.includes("already registered")) return "이미 가입된 이메일이에요. 로그인해 주세요.";
  if (lower.includes("email not confirmed")) {
    return "메일 확인이 아직이에요. 받은 메일의 링크를 누른 뒤 다시 로그인해 주세요.";
  }
  if (lower.includes("rate limit")) {
    return "메일 발송 한도를 넘었어요. 비밀번호로 가입·로그인하거나 잠시 후 다시 시도해 주세요.";
  }
  if (lower.includes("password should be at least")) return "비밀번호는 6자 이상이어야 해요.";
  return message;
}

export async function signOut(): Promise<void> {
  // 데모 계정은 Supabase 세션이 없으므로 로컬만 지운다.
  const demo = readDemoSession() !== null;
  const client = demo ? null : getSupabaseClient();
  let signOutError: Error | null = null;
  if (client) {
    const { error } = await client.auth.signOut({ scope: "local" });
    if (error) signOutError = new Error(`로그아웃 실패: ${error.message}`);
  }

  window.localStorage.removeItem(DEMO_SESSION_STORAGE_KEY);
  // 데모 보유 종목은 이 브라우저가 원본이라 다음 참가자에게 남지 않게 지운다. 로그인 계정 것은 Supabase 사본이라 둔다.
  if (demo) window.localStorage.removeItem(STORAGE_KEYS.holdings);
  clearSavedProfile();
  window.dispatchEvent(new Event(AUTH_UPDATED_EVENT));

  if (signOutError) throw signOutError;
}

export function subscribeToAuthChanges(onChange: () => void): () => void {
  if (typeof window === "undefined") return () => undefined;

  const onStorage = (event: StorageEvent) => {
    if (
      event.key === DEMO_SESSION_STORAGE_KEY ||
      event.key === PROFILE_STORAGE_KEY
    ) {
      onChange();
    }
  };
  const onUpdated = () => onChange();

  window.addEventListener("storage", onStorage);
  window.addEventListener(AUTH_UPDATED_EVENT, onUpdated);
  window.addEventListener(PROFILE_UPDATED_EVENT, onUpdated);

  const client = getSupabaseClient();
  const subscription = client
    ? client.auth.onAuthStateChange(() => {
        window.setTimeout(onChange, 0);
      }).data.subscription
    : null;

  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(AUTH_UPDATED_EVENT, onUpdated);
    window.removeEventListener(PROFILE_UPDATED_EVENT, onUpdated);
    subscription?.unsubscribe();
  };
}

function readDemoSession(): DemoSession | null {
  if (typeof window === "undefined") return null;
  try {
    const serialized = window.localStorage.getItem(DEMO_SESSION_STORAGE_KEY);
    if (!serialized) return null;
    const value: unknown = JSON.parse(serialized);
    if (!isRecord(value)) return null;
    if (
      typeof value.userId !== "string" ||
      typeof value.displayName !== "string" ||
      typeof value.signedInAt !== "string"
    ) {
      return null;
    }
    return value as unknown as DemoSession;
  } catch {
    return null;
  }
}

function displayNameFor(user: User, storedName?: string | null): string {
  // 이름 칸이 생기기 전 가입자는 설문 예시 ID(u_minji_001)가 이름으로 저장됐다. 그 값은 건너뛴다.
  if (storedName?.trim() && storedName !== "u_minji_001") return storedName.trim();
  const fullName = user.user_metadata.full_name;
  if (typeof fullName === "string" && fullName.trim()) return fullName.trim();
  return user.email?.split("@")[0] || "사용자";
}

function syncSavedProfile(value: unknown): void {
  const serialized = JSON.stringify(value);
  if (!parseSavedProfile(serialized)) {
    clearSavedProfile();
    return;
  }
  if (window.localStorage.getItem(PROFILE_STORAGE_KEY) === serialized) return;
  window.localStorage.setItem(PROFILE_STORAGE_KEY, serialized);
  window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
}

function clearSavedProfile(): void {
  window.localStorage.removeItem(STORAGE_KEYS.surveyAnswers);
  window.localStorage.removeItem(STORAGE_KEYS.watchlist);
  window.localStorage.removeItem(STORAGE_KEYS.stockNotes);
  if (!window.localStorage.getItem(PROFILE_STORAGE_KEY)) return;
  window.localStorage.removeItem(PROFILE_STORAGE_KEY);
  window.dispatchEvent(new Event(PROFILE_UPDATED_EVENT));
}
