import { isSupabaseConfigured } from "./supabase.ts";

// Existing UI uses published chart snapshots for every configured stock page.
export const isChartPreview = (code: string) => isSupabaseConfigured() && /^[0-9A-Z]{6}$/.test(code);
