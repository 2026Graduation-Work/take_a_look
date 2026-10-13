// 모델 근거 항목명(차트 pack 피처명) → 초보자용 쉬운 말 (#257).
// 차트 label_ko는 그대로 두고 화면에서만 덮어쓴다. 기간이 붙는 피처(std_20 등)는 "{n}일"을 채운다.
// 사전에 없으면 차트 label_ko(영문 없는 경우)를, 그것도 없으면 묶음 이름을 쓴다. 원문 피처명은 노출하지 않는다.

const WINDOWED: Record<string, string> = {
  roc: "{n}일 전보다 오른 정도",
  ma: "{n}일 평균 가격과 차이",
  max: "{n}일 최고가와 거리",
  min: "{n}일 최저가와 거리",
  rsv: "{n}일 가격대 속 위치",
  std: "{n}일 주가 출렁임",
  beta: "{n}일 추세 기울기",
  rsqr: "{n}일 추세의 뚜렷함",
  resi: "{n}일 추세선과 거리",
  rank: "{n}일 중 현재가 순위",
  qtlu: "{n}일 높은 가격대",
  qtld: "{n}일 낮은 가격대",
  imax: "{n}일 최고가 시점",
  imin: "{n}일 최저가 시점",
  imxd: "{n}일 고점·저점 간격",
  cntp: "{n}일 중 오른 날 비중",
  cntn: "{n}일 중 내린 날 비중",
  cntd: "{n}일 오른 날·내린 날 차",
  sump: "{n}일 오른 폭 비중",
  sumn: "{n}일 내린 폭 비중",
  sumd: "{n}일 오른 폭·내린 폭 차",
  corr: "{n}일 가격과 거래량 동행",
  cord: "{n}일 등락과 거래량 동행",
  vma: "{n}일 평균 거래량",
  vstd: "{n}일 거래량 출렁임",
  wvma: "{n}일 거래 실린 출렁임",
  vsump: "{n}일 거래량 늘어난 비중",
  vsumn: "{n}일 거래량 줄어든 비중",
  vsumd: "{n}일 거래량 증감 차",
  flow_individual: "{n}일 개인 순매수",
  flow_institution: "{n}일 기관 순매수",
  flow_foreign: "{n}일 외국인 순매수",
};

const FIXED: Record<string, string> = {
  Change: "하루 등락률",
  kmid: "하루 시가 대비 종가",
  kmid_2: "하루 몸통 비중",
  klen: "하루 가격 폭",
  kup: "고가에서 밀린 폭",
  kup_2: "고가에서 밀린 비중",
  klow: "저가에서 오른 폭",
  klow_2: "저가에서 오른 비중",
  ksft: "종가 치우침",
  ksft_2: "종가 치우침 비중",
  open_0: "종가 대비 시가",
  high_0: "종가 대비 고가",
  low_0: "종가 대비 저가",
  vwap_0: "종가 대비 평균 거래가",
  Barrier_Up: "최근 위쪽 변동 범위",
  Barrier_Down: "최근 아래쪽 변동 범위",
};

// 묶음 판단: 사전에 없는 피처의 접두어(토큰)로 고른다.
export function featureGroup(name: string): string {
  const head = name.toLowerCase().split(/[^a-z0-9]+/)[0];
  if (/^(news|sentiment|finbert|headline)/.test(head)) return "뉴스 분위기";
  if (/^(dart|financial|fundamental|revenue|per|pbr|roe|eps|debt)/.test(head)) return "재무";
  if (/^(flow|vma|vstd|wvma|vsum|volume|amount|turnover)/.test(head)) return "거래·수급";
  return "가격 흐름";
}

export function featureLabel(name: string, labelKo?: string | null): string {
  if (FIXED[name]) return FIXED[name];
  const match = /^(.+)_(\d+)$/.exec(name);
  if (match && WINDOWED[match[1]]) return WINDOWED[match[1]].replace("{n}", match[2]);
  if (labelKo?.trim() && !/[A-Za-z_]/.test(labelKo)) return labelKo.trim();
  return featureGroup(name);
}
