import { isSupabaseConfigured } from "./supabase.ts";

// Public display-test selection. Empty env value disables the preview on redeploy.
export const PREVIEW_BATCH_ID = process.env.NEXT_PUBLIC_CHART_PREVIEW_BATCH_ID ??
  "18e7a9f66fa63d4b6e0439c9189828e26f4496c128d17e79755d6711e0f3dc48";
export const isChartPreview = (code: string) => Boolean(PREVIEW_BATCH_ID) && isSupabaseConfigured() && code === "005930";
