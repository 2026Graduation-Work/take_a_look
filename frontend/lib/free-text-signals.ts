const FREE_TEXT_SIGNALS = [
  { field: "fomo_index", label: "남보다 늦을까 조급함", keywords: ["남들 다 버는데", "뒤처지는", "놓칠까"], value: 0.8 },
  { field: "panic_sell_tendency", label: "손실 걱정", keywords: ["마이너스", "손실", "잠을 못"], value: 0.75 },
] as const;

type FreeTextField = (typeof FREE_TEXT_SIGNALS)[number]["field"];

export function extractFreeTextSignals(text: string, dismissed: readonly string[] = []): Record<string, number> {
  return Object.fromEntries(
    FREE_TEXT_SIGNALS
      .filter(({ field, keywords }) => !dismissed.includes(field) && keywords.some((keyword) => text.includes(keyword)))
      .map(({ field, value }) => [field, value]),
  );
}

export function freeTextReadings(signals: Record<string, number>): { field: FreeTextField; label: string }[] {
  return FREE_TEXT_SIGNALS.filter(({ field }) => field in signals).map(({ field, label }) => ({ field, label }));
}
