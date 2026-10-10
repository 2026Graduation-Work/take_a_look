// 브라우저 저장 키(모두 localStorage). 쓰는 곳은 반드시 여기서 가져온다 —
// 이 모듈을 처음 불러올 때 옛 서비스명(SignalLab) 키를 새 키로 옮기므로, 읽기보다 이전이 먼저 돈다.
export const STORAGE_KEYS = {
  demoSession: "takealook.demo-session.v1",
  profile: "takealook.ips-profile.v1",
  holdings: "takealook.holdings.v1",
  surveyDraft: "takealook.survey-draft.v1",
  // 마지막으로 저장한 설문 답. "다시 진단"을 지난 답이 채워진 상태로 시작한다(성향과 함께 지운다).
  surveyAnswers: "takealook.survey-answers.v1",
  // 관심 종목·판단 메모. 데모는 여기가 원본, 로그인 사용자는 Supabase 값을 여기에 비춰 둔다(lib/stock-marks.ts).
  watchlist: "takealook.watchlist.v1",
  stockNotes: "takealook.stock-notes.v1",
} as const;

// 2027-02 이후 제거: 옛 키(signallab.*) 이전. 그때쯤이면 옛 키를 가진 브라우저가 남지 않는다.
const LEGACY_PREFIX = "signallab.";
const PREFIX = "takealook.";

type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

// 새 키가 없으면 옛 값을 복사, 있으면 새 값을 유지. 어느 쪽이든 옛 키는 지운다. 여러 번 돌아도 결과가 같다.
export function migrateStorageKeys(storage: KeyValueStore): void {
  for (const key of Object.values(STORAGE_KEYS)) {
    const legacyKey = LEGACY_PREFIX + key.slice(PREFIX.length);
    const legacy = storage.getItem(legacyKey);
    if (legacy === null) continue;
    if (storage.getItem(key) === null) storage.setItem(key, legacy);
    storage.removeItem(legacyKey);
  }
}

// SSR에서는 window가 없어 건너뛴다. 사생활 보호 모드 등 저장소 접근이 막히면 이전 없이 넘어간다.
if (typeof window !== "undefined") {
  try {
    migrateStorageKeys(window.localStorage);
  } catch {
    // 저장소를 못 쓰면 옛 값도 읽을 수 없으니 옮길 것이 없다.
  }
}
