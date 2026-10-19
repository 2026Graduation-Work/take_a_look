// 설문 자유 답 → 보조값. 판정은 규칙(키워드 포함 여부)만 쓰고 LLM은 쓰지 않는다. 키워드 사전은 이 파일 하나.
// 진단 결과 화면에 "자유 답에서 읽은 것"으로 보여 준다. dismissed_signals로 들어온 판정은 보조값에 넣지 않는다(성우 개선 포인트 3).
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

// 저장된 보조값 → 화면에 보일 판정(사전 순서). 사전에 없는 키는 보이지 않는다.
export function freeTextReadings(signals: Record<string, number>): { field: FreeTextField; label: string }[] {
  return FREE_TEXT_SIGNALS.filter(({ field }) => field in signals).map(({ field, label }) => ({ field, label }));
}
