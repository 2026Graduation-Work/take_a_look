import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

export function isSupabaseConfigured(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL &&
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
  );
}

export function getSupabaseClient(): SupabaseClient | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;

  client ??= createClient(url, anonKey);
  return client;
}

// DB 오류 → 화면에 그대로 보일 문구(무슨 일 + 어떻게 하면 되는지)
export function assertOk(error: { message: string } | null, operation: string): asserts error is null {
  if (error) throw new Error(`${operation} 실패: ${error.message}. 잠시 뒤 다시 시도해 주세요.`);
}
