// 스크린샷 보유 종목 불러오기의 시험 화면(가짜 수치). 실제 계좌 캡처는 쓰지 않는다(AGENTS.md).
// 사용: node tests/fixtures/holdings-ocr/make-screens.mjs → 같은 폴더에 *.png와 answers.json
// A 밝은 표형(종목 한 칸이 2줄), B 어두운 목록형(이름 아래 N주, 오른쪽 평가금과 손익), C PC 웹 표형(평균단가 열).
import { chromium } from "@playwright/test";
import { writeFileSync } from "node:fs";

const OUT = new URL(".", import.meta.url);
const won = (n) => Math.round(n).toLocaleString("ko-KR");
const signed = (n) => `${n > 0 ? "+" : n < 0 ? "-" : ""}${won(Math.abs(n))}`;

// 실제 코스피 종목명 + 지어낸 수량, 평균 매입가, 현재가
const STOCKS = {
  samsung: { code: "005930", name: "삼성전자", qty: 37, avg: 71200, price: 83400 },
  hynix: { code: "000660", name: "SK하이닉스", qty: 5, avg: 182500, price: 241000 },
  hanwha: { code: "012450", name: "한화에어로스페이스", qty: 3, avg: 512000, price: 486500 },
  bio: { code: "207940", name: "삼성바이오로직스", qty: 2, avg: 948000, price: 1012000 },
  kakao: { code: "035720", name: "카카오", qty: 64, avg: 52300, price: 41850 },
  naver: { code: "035420", name: "NAVER", qty: 11, avg: 198700, price: 213500 },
  hyundai: { code: "005380", name: "현대차", qty: 8, avg: 236000, price: 221500 },
  kb: { code: "105560", name: "KB금융", qty: 21, avg: 78400, price: 96200 },
  lgensol: { code: "373220", name: "LG에너지솔루션", qty: 4, avg: 401000, price: 362500 },
  celltrion: { code: "068270", name: "셀트리온", qty: 13, avg: 176300, price: 181900 },
  posco: { code: "005490", name: "POSCO홀딩스", qty: 6, avg: 389000, price: 341000 },
  doosan: { code: "034020", name: "두산에너빌리티", qty: 120, avg: 19870, price: 24350 },
  // 검증용(holdout) 화면에만 쓰는 종목: 규칙을 고칠 때 보지 않은 화면으로 정확도를 따로 잰다
  kia: { code: "000270", name: "기아", qty: 15, avg: 98300, price: 104700 },
  shinhan: { code: "055550", name: "신한지주", qty: 33, avg: 47150, price: 55900 },
  lgchem: { code: "051910", name: "LG화학", qty: 2, avg: 455000, price: 318500 },
  sdi: { code: "006400", name: "삼성SDI", qty: 3, avg: 389500, price: 251000 },
  hanaro: { code: "086790", name: "하나금융지주", qty: 18, avg: 61200, price: 66800 },
  krafton: { code: "259960", name: "크래프톤", qty: 1, avg: 268000, price: 331500 },
  kepco: { code: "015760", name: "한국전력", qty: 40, avg: 21450, price: 25300 },
  hdhi: { code: "329180", name: "HD현대중공업", qty: 2, avg: 287000, price: 402500 },
  meritz: { code: "138040", name: "메리츠금융지주", qty: 6, avg: 101200, price: 118900 },
  korzinc: { code: "010130", name: "고려아연", qty: 1, avg: 512000, price: 776000 },
};
// 마스터에 없는 줄(다루지 않는 종목)
const ETF = [
  { name: "KODEX 200", qty: 10, avg: 35120, price: 37480 },
  { name: "TIGER 미국S&P500", qty: 7, avg: 18950, price: 21030 },
];
const FOREIGN = { name: "애플", qty: "0.015819", value: 5210, pnl: 412, rate: 8.6 };

const metrics = (s) => {
  const value = s.qty * s.price;
  const pnl = s.qty * (s.price - s.avg);
  return { value, pnl, rate: ((s.price / s.avg - 1) * 100).toFixed(2) };
};

let FONT = `"Noto Sans KR","Malgun Gothic",sans-serif`;
const css = () => `*{box-sizing:border-box;margin:0;padding:0}body{font-family:${FONT};-webkit-font-smoothing:antialiased}`;

// A. 밝은 표형: 종목명 | 평가손익/수익률 | 보유수량/평가금액, 맨 아래 지수 바
function formA(rows, { dark = false } = {}) {
  const bg = dark ? "#121417" : "#fff", ink = dark ? "#eef0f3" : "#111", muted = dark ? "#9aa0a8" : "#777";
  const up = dark ? "#ff6b6b" : "#e02020", down = dark ? "#5aa0ff" : "#1a64e0", line = dark ? "#2a2e34" : "#e6e6e6";
  const body = rows.map((s) => {
    const { value, pnl, rate } = metrics(s);
    const color = pnl > 0 ? up : pnl < 0 ? down : ink;
    return `<div class="row"><div class="name">${s.name}</div>
      <div class="col" style="color:${color}"><div>${signed(pnl)}</div><div>${pnl > 0 ? "+" : ""}${rate}%</div></div>
      <div class="col"><div>${won(s.qty)}</div><div>${won(value)}</div></div></div>`;
  }).join("");
  return `<style>${css()}body{background:${bg};color:${ink}}
  .top{padding:20px 20px 12px;font-size:22px;font-weight:600}.sum{padding:8px 20px 16px;display:flex;justify-content:space-between;font-size:16px}
  .head,.row{display:grid;grid-template-columns:32% 34% 34%;border-bottom:1px solid ${line}}
  .head{background:${dark ? "#1c1f24" : "#f2f3f5"};color:${muted};font-size:14px}.head div{padding:6px 10px;text-align:right}.head div:first-child{text-align:left;align-self:center}
  .name{padding:14px 10px;font-size:17px;font-weight:600;word-break:break-all}.col{padding:12px 10px;text-align:right;font-size:17px;line-height:1.5}
  .bar{display:flex;gap:16px;padding:10px 20px;background:${dark ? "#1c1f24" : "#f6f6f6"};font-size:15px}</style>
  <div class="top">주식잔고/손익</div>
  <div class="sum"><span>평가손익</span><span style="color:${down}">-38,250원 -1.21%</span></div>
  <div class="head"><div>종목명</div><div>평가손익<br>수익률</div><div>보유수량<br>평가금액</div></div>
  ${body}
  <div class="bar"><span>KOSPI</span><span style="color:${up}">2,684.31</span><span style="color:${up}">▲ 12.47(0.47%)</span><span style="color:${muted}">장종료</span></div>`;
}

// B. 어두운 목록형: 원형 로고, 이름 아래 N주, 오른쪽 평가금(원) 아래 ±손익(수익률%). 수익률에 부호가 없다
function formB(rows, { dark = true } = {}) {
  const bg = dark ? "#17171c" : "#fff", ink = dark ? "#f2f2f5" : "#191f28", muted = dark ? "#8b8f98" : "#8b95a1";
  const up = dark ? "#f0616d" : "#f04452", down = dark ? "#5b8def" : "#3182f6";
  const item = (name, qty, value, pnl, rate, logo) => {
    const color = pnl > 0 ? up : pnl < 0 ? down : ink;
    return `<div class="row"><div class="logo" style="background:${logo}">${name.slice(0, 2)}</div>
      <div class="left"><div class="nm">${name}</div><div class="q">${qty}주</div></div>
      <div class="right"><div class="v">${won(value)}원</div><div style="color:${color}">${signed(pnl)} (${Math.abs(rate)}%)</div></div></div>`;
  };
  const colors = ["#1f3fa8", "#e8542f", "#2c8c5a", "#7b4bd1", "#d39b1c", "#2a7fc4"];
  const body = rows.map((s, i) => {
    if (s.foreign) return item(s.name, s.qty, s.value, s.pnl, s.rate, "#555");
    const { value, pnl, rate } = metrics(s);
    return item(s.name, won(s.qty), value, pnl, Number(rate).toFixed(1), colors[i % colors.length]);
  }).join("");
  return `<style>${css()}body{background:${bg};color:${ink}}
  .idx{padding:18px 20px;font-size:17px;color:${muted}}.idx b{color:${up};font-weight:600}
  .sec{padding:18px 20px 6px;font-size:18px;font-weight:600}.sec span{color:${up};margin-left:8px}
  .row{display:flex;align-items:center;gap:14px;padding:12px 20px}.logo{width:42px;height:42px;border-radius:50%;color:#fff;font-size:12px;display:flex;align-items:center;justify-content:center;flex:none}
  .left{flex:1;min-width:0}.nm{font-size:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.q{font-size:15px;color:${muted};margin-top:2px}
  .right{text-align:right;font-size:15px}.v{font-size:18px;font-weight:600;margin-bottom:2px}</style>
  <div class="idx">S&amp;P 500 <b>6,812.40</b> <b>+0.5%</b></div>
  <div class="sec">해외주식</div>${item(FOREIGN.name, FOREIGN.qty, FOREIGN.value, FOREIGN.pnl, FOREIGN.rate, "#555")}
  <div class="sec">국내주식<span>+12.4%</span></div>${body}`;
}

// C. PC 웹 표형: 종목명, 보유수량, 평균단가, 현재가, 평가금액, 손익
function formC(rows, { dark = false } = {}) {
  const bg = dark ? "#16181d" : "#fff", ink = dark ? "#e9ebee" : "#222", muted = dark ? "#99a" : "#666", line = dark ? "#2b2f36" : "#ddd";
  const up = "#d32f2f", down = "#1565c0";
  const body = rows.map((s) => {
    const { value, pnl, rate } = metrics(s);
    const color = pnl > 0 ? up : pnl < 0 ? down : ink;
    return `<tr><td class="l">${s.name}</td><td>${won(s.qty)}</td><td>${won(s.avg)}</td><td>${won(s.price)}</td><td>${won(value)}</td>
      <td style="color:${color}">${signed(pnl)}</td><td style="color:${color}">${pnl > 0 ? "+" : ""}${rate}%</td></tr>`;
  }).join("");
  return `<style>${css()}body{background:${bg};color:${ink};padding:24px}
  h1{font-size:20px;margin-bottom:14px}table{width:100%;border-collapse:collapse;font-size:14px}
  th{background:${dark ? "#20232a" : "#f4f5f7"};color:${muted};font-weight:500;padding:9px 10px;text-align:right;border-bottom:1px solid ${line}}
  td{padding:9px 10px;text-align:right;border-bottom:1px solid ${line};white-space:nowrap}th.l,td.l{text-align:left}
  .total td{font-weight:700}</style>
  <h1>잔고 조회</h1><table><thead><tr><th class="l">종목명</th><th>보유수량</th><th>평균단가</th><th>현재가</th><th>평가금액</th><th>손익</th><th>수익률</th></tr></thead>
  <tbody>${body}<tr class="total"><td class="l">합계</td><td></td><td></td><td></td><td>${won(rows.reduce((t, s) => t + metrics(s).value, 0))}</td><td></td><td></td></tr></tbody></table>`;
}

const S = STOCKS;
const SCREENS = [
  { id: "A-light", html: formA, rows: [S.samsung, ETF[0], S.hanwha, S.kakao, S.bio, S.naver], avgSource: "computed" },
  { id: "A-dark", html: (r) => formA(r, { dark: true }), rows: [S.hynix, S.lgensol, S.kb, ETF[1], S.celltrion], avgSource: "computed" },
  { id: "B-dark", html: formB, rows: [S.samsung, ETF[0], S.doosan, S.hyundai, S.posco, ETF[1], S.kakao], avgSource: "computed" },
  { id: "B-light", html: (r) => formB(r, { dark: false }), rows: [S.naver, S.hynix, S.bio, S.kb], avgSource: "computed" },
  { id: "C-light", html: formC, rows: [S.samsung, S.hynix, S.hanwha, S.lgensol, ETF[0], S.celltrion, S.posco, S.doosan], avgSource: "label" },
  { id: "C-dark", html: (r) => formC(r, { dark: true }), rows: [S.kakao, S.naver, S.hyundai, S.kb, S.bio], avgSource: "label" },
];

// 검증용: 다른 글꼴(나눔스퀘어), 다른 종목, 더 긴 목록
const ETF2 = [{ name: "KODEX 레버리지", qty: 4, avg: 18750, price: 21340 }, { name: "ACE 미국나스닥100", qty: 9, avg: 16200, price: 17985 }];
const HOLDOUT = [
  { id: "A-light-v2", html: formA, rows: [S.kia, S.shinhan, ETF2[0], S.meritz, S.lgchem, S.hdhi], avgSource: "computed" },
  { id: "A-dark-v2", html: (r) => formA(r, { dark: true }), rows: [S.sdi, S.kepco, S.hanaro, ETF2[1], S.krafton], avgSource: "computed" },
  { id: "B-dark-v2", html: formB, rows: [S.korzinc, S.kia, ETF2[1], S.meritz, S.kepco, S.shinhan], avgSource: "computed" },
  { id: "B-light-v2", html: (r) => formB(r, { dark: false }), rows: [S.hdhi, S.lgchem, ETF2[0], S.hanaro], avgSource: "computed" },
  { id: "C-light-v2", html: formC, rows: [S.kia, S.shinhan, S.lgchem, S.sdi, S.hanaro, ETF2[0], S.krafton, S.kepco, S.hdhi], avgSource: "label" },
  { id: "C-dark-v2", html: (r) => formC(r, { dark: true }), rows: [S.meritz, S.korzinc, S.kia, ETF2[1], S.shinhan], avgSource: "label" },
];

// 실제 폰 캡처 조건(2026-10-20 실패 신고): 아이폰 1179×2556, 위 상태 표시줄, 아래 탭 바, 원형 로고, 다크 모드.
// P-A 밝은 표형인데 보유가 전부 ETF, P-B 어두운 목록형에 국내 주식 1종목 + ETF 여러 개 + 해외 지수 줄 + 소수점 해외 주식
const ETF3 = [
  { name: "KODEX 코스닥150", qty: 12, avg: 13250, price: 14080 }, { name: "TIGER 미국나스닥100", qty: 3, avg: 128400, price: 139250 },
  { name: "KODEX 방산TOP10", qty: 20, avg: 21800, price: 24660 }, { name: "RISE 200", qty: 6, avg: 38900, price: 41150 },
  { name: "TIGER 200헬스케어", qty: 15, avg: 9870, price: 9425 },
];
function phone(inner, { dark = false } = {}) {
  const bg = dark ? "#000" : "#fff", ink = dark ? "#fff" : "#000", bar = dark ? "#1c1c1e" : "#f8f8f8", muted = dark ? "#8e8e93" : "#8e8e93";
  return `<style>html,body{height:100%}body{display:flex;flex-direction:column;background:${bg}}
  .status{height:54px;flex:none;display:flex;justify-content:space-between;align-items:center;padding:14px 32px 0;font:600 17px -apple-system,sans-serif;color:${ink}}
  .content{flex:1;overflow:hidden}.tabs{height:84px;flex:none;display:flex;justify-content:space-around;padding-top:10px;background:${bar};font-size:11px;color:${muted}}
  .tabs div{display:flex;flex-direction:column;align-items:center;gap:4px}.tabs i{width:24px;height:24px;border-radius:6px;background:${muted}}</style>
  <div class="status"><span>9:41</span><span>●●● ▮</span></div><div class="content">${inner}</div>
  <div class="tabs"><div><i></i>홈</div><div><i></i>관심</div><div><i></i>발견</div><div><i></i>내 자산</div><div><i></i>전체</div></div>`;
}
const PHONE = [
  { id: "P-A-etf", html: (r) => phone(formA(r)), rows: ETF3.slice(0, 5), avgSource: "computed" },
  { id: "P-B-dark", html: (r) => phone(formB(r), { dark: true }), rows: [S.samsung, ETF3[0], ETF3[2], ETF3[4], ETF3[1]], avgSource: "computed" },
];

const answers = {};
const browser = await chromium.launch();
for (const screen of [...SCREENS, ...HOLDOUT, ...PHONE]) {
  FONT = screen.id.endsWith("-v2") ? `"NanumSquare",sans-serif` : `"Noto Sans KR","Malgun Gothic",sans-serif`;
  const html = `<!doctype html><meta charset="utf-8">${screen.html(screen.rows)}`;
  const isPhone = screen.id.startsWith("P-");
  // 폰 화면은 393×852 @3 = 1179×2556 한 장(스크롤 없이 화면 그대로), 나머지는 390 @3, 1280 @1 전체 길이
  for (const [width, scale] of isPhone ? [[393, 3]] : [[390, 3], [1280, 1]]) {
    const page = await browser.newPage({ viewport: { width, height: isPhone ? 852 : 400 }, deviceScaleFactor: scale });
    await page.setContent(html);
    await page.screenshot({ path: new URL(`${screen.id}-${width}.png`, OUT).pathname, fullPage: !isPhone });
    await page.close();
  }
  answers[screen.id] = {
    form: isPhone ? screen.id.slice(0, 3) : screen.id[0],
    widths: isPhone ? [393] : [390, 1280],
    holdout: screen.id.endsWith("-v2"),
    holdings: screen.rows.filter((row) => row.code).map(({ code, name, qty, avg }) => ({ code, name, quantity: qty, avgBuyPrice: avg, avgSource: screen.avgSource })),
    unsupported: [...screen.rows.filter((row) => !row.code).map(({ name }) => name), ...(/^(P-)?B/.test(screen.id) ? [FOREIGN.name] : [])],
  };
}
await browser.close();
writeFileSync(new URL("answers.json", OUT), `${JSON.stringify(answers, null, 2)}\n`);
console.log(Object.keys(answers).join(", "));
