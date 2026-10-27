import { KNOWN_STOCKS } from "./mock-data";
import { getSupabaseClient } from "./supabase";

export type StockOption = { code: string; name: string };

// Public master, shared by demo and signed-in search. Failed reads are not cached.
let master: Promise<StockOption[]> | null = null;
export function loadStockCatalog(): Promise<StockOption[]> {
  if (master) return master;
  const client = getSupabaseClient();
  if (!client) return Promise.resolve(KNOWN_STOCKS);
  master = (async () => {
    const stocks: StockOption[] = [];
    const pageSize = 1000;
    for (let start = 0; ; start += pageSize) {
      const { data, error } = await client.from("stocks").select("code,name")
        .eq("is_active", true).order("code").range(start, start + pageSize - 1);
      if (error) throw new Error("종목 목록을 불러오지 못했어요. 잠시 뒤 다시 검색해 주세요.");
      const page = (data ?? []) as StockOption[];
      stocks.push(...page);
      if (page.length < pageSize) return stocks;
    }
  })().catch((error: unknown) => { master = null; throw error; });
  return master;
}
