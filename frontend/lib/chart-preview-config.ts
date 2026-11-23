import { isSupabaseConfigured } from "./supabase.ts";

export const isChartPreview = (code: string) => isSupabaseConfigured() && /^[0-9A-Z]{6}$/.test(code);
