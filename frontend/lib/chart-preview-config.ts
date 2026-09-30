import { isSupabaseConfigured } from "./supabase.ts";

// Public display-test selection. Empty env value disables the preview on redeploy.
export const PREVIEW_BATCH_ID = process.env.NEXT_PUBLIC_CHART_PREVIEW_BATCH_ID ??
  "3eb13ecec44e6f2e507f79fbba6c5ded2d6204b5ae5ad59db098950f17fa14ca";
export const isChartPreview = (code: string) => Boolean(PREVIEW_BATCH_ID) && isSupabaseConfigured() && code === "005930";
