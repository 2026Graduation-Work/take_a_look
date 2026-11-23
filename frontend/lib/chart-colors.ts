// recharts는 색을 SVG 표현 속성(fill, stroke)으로 넘기는데, 속성 안의 var()를 Safari가 확실히 풀지 않아
// 차트가 검게 나올 수 있다. 그래서 토큰 대신 리터럴로 두고, 값은 app/globals.css의 @theme와 같게 맞춘다.
export const CHART = {
  ink: "#1d1d1f",
  muted: "#6e6e73",
  ghost: "#86868b",
  line: "#d2d2d7",
  lineSoft: "#e8e8ed",
  track: "#e8e8ed",
  page: "#f5f5f7",
  edge: "#d2d2d7",

  accent: "#8dc63f",

  priceLine: "#424245",

  // 국내 관례: 상승 적, 하락 청
  up: "#b0342a",
  down: "#274b96",
  sigSp: "#b0342a",
  sigP: "#ad4436",
  sigN: "#6e6e73",
  sigNg: "#4666b5",
  sigNgTint: "#eff2fa",
  sigSn: "#274b96",
} as const;
