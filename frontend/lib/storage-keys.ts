// 이 모듈을 처음 불러올 때 옛 서비스명(SignalLab) 키를 새 키로 옮기므로, 키는 반드시 여기서 가져와 읽기보다 이전이 먼저 돌게 한다.
export const STORAGE_KEYS = {
  demoSession: "takealook.demo-session.v1",
  profile: "takealook.ips-profile.v1",
  holdings: "takealook.holdings.v1",
  surveyDraft: "takealook.survey-draft.v1",
  surveyAnswers: "takealook.survey-answers.v1",
  watchlist: "takealook.watchlist.v1",
  stockNotes: "takealook.stock-notes.v1",
  signalHorizon: "takealook.signal-horizon.v1",
  ocrAssets: "takealook.ocr-assets.v1",
} as const;

// 2027-02 이후 제거: 옛 키(signallab.*) 이전. 그때쯤이면 옛 키를 가진 브라우저가 남지 않는다.
const LEGACY_PREFIX = "signallab.";
const PREFIX = "takealook.";

type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function migrateStorageKeys(storage: KeyValueStore): void {
  for (const key of Object.values(STORAGE_KEYS)) {
    const legacyKey = LEGACY_PREFIX + key.slice(PREFIX.length);
    const legacy = storage.getItem(legacyKey);
    if (legacy === null) continue;
    if (storage.getItem(key) === null) storage.setItem(key, legacy);
    storage.removeItem(legacyKey);
  }
}

// 사생활 보호 모드 등 저장소 접근이 막히면 이전 없이 넘어간다.
if (typeof window !== "undefined") {
  try {
    migrateStorageKeys(window.localStorage);
  } catch {
    // 저장소를 못 쓰면 옛 값도 읽을 수 없으니 옮길 것이 없다.
  }
}

// 브라우저가 사이트 저장소를 막으면(쿠키·사이트 데이터 차단) localStorage 접근 자체가 예외를 던진다.
export function storageBlocked(): boolean {
  try {
    window.localStorage.getItem(STORAGE_KEYS.holdings);
    return false;
  } catch {
    return true;
  }
}
