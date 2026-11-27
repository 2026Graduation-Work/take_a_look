// 모든 문구는 사람이 쓰고 출처를 단다(LLM 생성 금지). 선정 기준과 레퍼런스 조사는 docs/research/beginner-tips-sources.md.
// 매매 지시, 상승 확률 단정을 쓰지 않는다. 사실, 계산, 연구 결과만 말하고 판단은 사용자가 한다.

export type TipCategory = "계산 착각" | "투자 습관" | "정보 읽기" | "제도와 비용";

export type TipSourceKind = "계산식" | "법령과 제도" | "공공기관" | "연구" | "보도" | "업계 자료";

export interface TipSource {
  kind: TipSourceKind;
  label: string;
  // 계산식만 주소 없이 둘 수 있다.
  url?: string;
}

export interface BeginnerTip {
  id: string;
  category: TipCategory;
  // 띠에 보이는 한 줄(36자 이하)
  title: string;
  summary: string;
  detail: readonly string[];
  // 계산 팁의 식. 화면에 그대로 보인다
  formula?: string;
  // 이 서비스에서 확인할 수 있는 곳(있을 때만)
  inService?: string;
  sources: readonly TipSource[];
  // 출처 원문을 다시 연 날
  checkedAt: string;
  // 제도나 세율처럼 바뀌는 내용은 이 날 전에 다시 확인한다
  reviewBy?: string;
}

const KCMI_1481: TipSource = {
  kind: "연구",
  label: "자본시장연구원, 국내 개인투자자의 행태적 편의와 거래행태(2022)",
  url: "https://www.kcmi.re.kr/report/report_view?report_no=1481",
};

export const BEGINNER_TIPS: readonly BeginnerTip[] = [
  // ── 계산 착각 ──
  {
    id: "loss-recovery",
    category: "계산 착각",
    title: "-30%가 되면 본전까지 +42.9%가 필요해요",
    summary: "100원이 70원이 되면 70원에서 30원이 올라야 100원이에요. 떨어진 비율만큼 오르면 되는 게 아니에요.",
    detail: [
      "떨어진 뒤에는 줄어든 금액을 기준으로 다시 올라야 해요.",
      "-10%는 +11.1%, -20%는 +25%, -50%는 +100%가 있어야 본전이에요.",
      "손실이 깊을수록 필요한 상승률이 훨씬 빠르게 커져요.",
    ],
    formula: "필요한 상승률 = 1 ÷ (1 − 하락률) − 1",
    inService: "종목 상세의 평단 대비 손익에서 지금 위치를 볼 수 있어요.",
    sources: [{ kind: "계산식", label: "수익률 계산" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "up-down-not-even",
    category: "계산 착각",
    title: "+10% 오른 뒤 -10%면 원금보다 1% 적어요",
    summary: "100원이 110원이 됐다가 10% 내리면 99원이에요. 순서를 바꿔도 결과는 같아요.",
    detail: [
      "같은 비율로 오르고 내려도 제자리로 돌아오지 않아요.",
      "흔들림이 클수록 차이가 커져요. +50% 뒤 -50%면 원금의 75%만 남아요.",
      "그래서 많이 흔들리는 종목은 제자리걸음 같아 보여도 실제로는 줄어들 수 있어요.",
    ],
    formula: "(1 + a) × (1 − a) = 1 − a²",
    sources: [{ kind: "계산식", label: "수익률 계산" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "average-return-trap",
    category: "계산 착각",
    title: "평균 수익률 +25%인데 돈은 그대로일 수 있어요",
    summary: "첫해 +100%, 다음 해 -50%면 두 해 평균은 +25%지만 100원은 다시 100원이에요.",
    detail: [
      "해마다의 수익률을 더해 나누는 평균은 실제로 불어난 돈을 보여 주지 못해요.",
      "실제 결과는 해마다의 배수를 곱해서 봐야 해요. 2배 곱하기 0.5배는 1배예요.",
      "광고나 글에서 '연평균 수익률'을 보면 어떤 방식으로 계산했는지 확인해 보면 좋아요.",
    ],
    formula: "실제 결과 = (1 + 첫해 수익률) × (1 + 다음 해 수익률)",
    sources: [{ kind: "계산식", label: "산술평균과 기하평균" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "averaging-down",
    category: "계산 착각",
    title: "평단이 낮아져도 손실 금액은 그대로예요",
    summary: "1만 원에 10주를 산 뒤 7천 원에 10주를 더 사면 평단은 8,500원이지만 손실은 여전히 3만 원이에요.",
    detail: [
      "더 사기 전 손실은 10만 원 넣고 7만 원이라 3만 원이에요.",
      "더 산 뒤에도 17만 원 넣고 14만 원이라 손실은 3만 원이에요.",
      "평단이 낮아져 본전이 가까워 보이는 건 넣은 돈이 늘었기 때문이에요. 같은 비율로 더 내리면 잃는 금액도 두 배가 돼요.",
    ],
    formula: "평단 = 넣은 돈 합계 ÷ 주식 수 합계",
    sources: [{ kind: "계산식", label: "평균 매입 단가 계산" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "rule-of-72",
    category: "계산 착각",
    title: "연 6%면 원금이 두 배 되는 데 약 12년 걸려요",
    summary: "72를 연 수익률(%)로 나누면 돈이 두 배가 되는 대략적인 햇수예요.",
    detail: [
      "연 6%로 12년을 불리면 실제로 약 2.01배가 돼요.",
      "물가에도 같은 셈이 맞아요. 물가가 연 3%씩 오르면 24년 뒤 같은 돈으로 살 수 있는 양이 절반이 돼요.",
      "'1년에 두 배' 같은 말은 연 100%라는 뜻이라, 얼마나 드문 숫자인지 이 셈으로 견줘 볼 수 있어요.",
    ],
    formula: "두 배가 되는 햇수 ≈ 72 ÷ 연 수익률(%)",
    sources: [{ kind: "계산식", label: "복리 계산(72의 법칙)" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "real-return",
    category: "계산 착각",
    title: "이자 3%에 물가 3%면 실제로 늘어난 건 거의 없어요",
    summary: "통장 숫자가 늘어도 물가가 같이 오르면 살 수 있는 양은 그대로예요.",
    detail: [
      "물가를 뺀 수익률을 실질 수익률이라고 해요. 대략 명목 수익률에서 물가 상승률을 빼서 봐요.",
      "2024년 전국민 금융이해력 조사에서 물가가 구매력에 주는 영향을 묻는 점수는 2년 전 78.3점에서 56.6점으로 떨어졌어요.",
      "투자 수익을 볼 때도 같은 기간 물가와 함께 견줘 보면 좋아요.",
    ],
    formula: "실질 수익률 ≈ 명목 수익률 − 물가 상승률",
    sources: [
      { kind: "계산식", label: "실질 수익률 계산" },
      { kind: "보도", label: "디지털타임스, 한은과 금감원 2024 전국민 금융이해력 조사(2025-04)", url: "https://www.dt.co.kr/article/11661613" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "price-is-not-size",
    category: "계산 착각",
    title: "주가가 낮다고 작은 회사는 아니에요",
    summary: "주가 1천 원 회사가 100만 원 회사보다 클 수 있어요. 회사 크기는 주가에 주식 수를 곱한 시가총액으로 봐요.",
    detail: [
      "주식 수가 많으면 한 주 가격이 낮아도 회사 전체 값은 클 수 있어요.",
      "한 주 가격이 낮다고 더 많이 오르기 쉬운 것도 아니에요. 오르내림은 비율로 같이 계산돼요.",
      "같은 돈이면 몇 주를 샀는지보다 몇 %가 움직였는지가 내 손익을 정해요.",
    ],
    formula: "시가총액 = 주가 × 발행 주식 수",
    sources: [{ kind: "계산식", label: "시가총액 정의" }],
    checkedAt: "2026-11-25",
  },
  {
    id: "stock-split",
    category: "계산 착각",
    title: "액면분할은 한 주를 여러 주로 잘게 나누는 거예요",
    summary: "한 주를 50주로 나누면 주가는 50분의 1, 주식 수는 50배가 돼요. 나누는 순간 회사 전체 값은 그대로예요.",
    detail: [
      "삼성전자는 2018년 50대 1로 액면분할해 265만 원대 주가가 5만 원대로 바뀌었어요.",
      "분할 자체는 회사의 실적이나 가진 자산을 바꾸지 않아요.",
      "다만 분할 뒤 주가는 거래량, 실적, 시장 분위기 같은 다른 이유로 오르기도 하고 내리기도 해요.",
      "무상증자도 비슷하게, 주식 수가 늘어나는 만큼 한 주의 기준 가격이 조정돼요.",
    ],
    formula: "분할 직후 주가 = 분할 전 주가 ÷ 분할 비율",
    sources: [
      { kind: "계산식", label: "액면분할 계산" },
      { kind: "보도", label: "뉴시스, 삼성전자 액면분할 뒤 거래 재개(2018-05-04)", url: "https://www.newsis.com/view/NISX20180504_0000300042" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "dividend-why",
    category: "계산 착각",
    title: "배당은 회사가 번 이익을 주주와 나누는 방법이에요",
    summary: "회사는 번 돈을 사업에 다시 쓰기도 하고 주주에게 나눠 주기도 해요. 배당은 그중 주주에게 돌려주는 몫이에요.",
    detail: [
      "법은 회사가 번 이익 안에서만 배당하도록 정하고 있고, 얼마를 줄지는 이사회나 주주총회에서 정해요.",
      "배당은 자사주 소각과 함께 주주에게 이익을 돌려주는 대표적인 방법으로 꼽혀요.",
      "성장에 돈이 많이 드는 회사는 배당 대신 다시 투자하는 쪽을 고르기도 해서, 배당이 적다고 꼭 나쁜 회사는 아니에요.",
      "배당을 주면 그만큼 회사에 남은 돈이 줄어, 이론상 한 주의 값도 그만큼 조정돼요.",
      "받는 배당에서는 보통 배당소득세 15.4%(지방소득세 포함)를 먼저 떼요.",
    ],
    sources: [
      { kind: "공공기관", label: "기획재정부 시사경제용어사전, 배당", url: "https://www.mofe.go.kr/sisa/dictionary/detail?idx=1149" },
      { kind: "보도", label: "생글생글(한국경제), 배당과 자사주 소각은 대표적 주주친화 정책(2025-06)", url: "https://sgsg.hankyung.com/article/2025061326911" },
      { kind: "법령과 제도", label: "소득세법 제129조(원천징수세율)", url: "https://www.law.go.kr/법령/소득세법/제129조" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-03-01",
  },

  // ── 투자 습관 ──
  {
    id: "disposition-effect",
    category: "투자 습관",
    title: "오른 주식은 일찍 팔고 내린 주식은 오래 두는 분이 많아요",
    summary: "국내 개인투자자 20만 명의 거래를 본 연구에서는 이익 중인 주식을 팔 가능성이 손실 중인 주식의 약 2.2배였대요.",
    detail: [
      "사고 나서 하루 뒤를 보면 이익 중인 주식은 41%, 손실 중인 주식은 22%가 팔렸어요.",
      "미국 1만 계좌 연구에서도 이익은 14.8%, 손실은 9.8%의 비율로 실현해 비슷한 경향이 보였대요.",
      "이런 경향을 처분효과라고 해요. 손실을 확정하는 아픔을 피하고 싶은 마음과 관련이 있다고 봐요.",
      "미리 정해 둔 나만의 다시 볼 기준이 있으면 그때그때의 기분에 덜 휘둘리는 데 도움이 될 수 있어요.",
    ],
    inService: "판단 메모에 처음 산 이유를 적어 두면 나중에 그 이유가 아직 맞는지 견줘 볼 수 있어요.",
    sources: [
      KCMI_1481,
      { kind: "연구", label: "Odean(1998), Are Investors Reluctant to Realize Their Losses?, Journal of Finance", url: "https://doi.org/10.1111/0022-1082.00072" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "index-vs-account",
    category: "투자 습관",
    title: "지수가 크게 올라도 내 계좌는 다르게 움직이곤 해요",
    summary: "2026년 초 코스피가 한 달에 21.4% 오르는 동안, 주요 증권사 개인 고객 계좌의 평균 수익률은 4.18%였대요.",
    detail: [
      "같은 보도에서 최근 3개월은 코스피가 28.3%, 개인 계좌 평균이 12.6%였어요.",
      "코스피가 4,000을 넘은 2025년 10월 말에도 NH투자증권 고객 약 240만 명 중 54.6%는 평가 손실 상태였대요.",
      "코스피는 시가총액이 큰 종목의 움직임이 크게 반영되는 지수라서, 어떤 종목을 얼마나 담았는지에 따라 내 결과는 달라질 수 있어요.",
    ],
    inService: "대시보드 보유 맵에서 내 종목별 비중을 볼 수 있어요.",
    sources: [
      { kind: "보도", label: "한국경제, 주요 증권사 개인 계좌 수익률 분석(2026-01-22)", url: "https://www.hankyung.com/article/2026012272041" },
      { kind: "보도", label: "알파경제, NH투자증권 고객 손익 분석(2025-11-10)", url: "https://kr.investing.com/news/stock-market-news/article-1708696" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "loss-aversion",
    category: "투자 습관",
    title: "보통 잃은 아픔을 번 기쁨보다 두 배쯤 크게 느낀대요",
    summary: "한 실험에서 사람들은 손실을 같은 크기의 이익보다 약 2.25배 크게 느꼈대요.",
    detail: [
      "이를 손실회피라고 해요. 행동경제학에서 가장 많이 확인된 경향 중 하나예요.",
      "그래서 손실 중인 종목은 결정을 미루고, 이익 중인 종목은 서둘러 확정하고 싶어지기 쉬워요.",
      "지금 마음이 손실을 피하려는 쪽인지 한 번 돌아보는 것만으로도 도움이 될 수 있어요.",
    ],
    sources: [
      { kind: "연구", label: "Tversky, Kahneman(1992), Advances in Prospect Theory, Journal of Risk and Uncertainty", url: "https://doi.org/10.1007/BF00122574" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "buy-price-anchor",
    category: "투자 습관",
    title: "주가는 내가 산 가격을 몰라요",
    summary: "내 평단은 나에게만 중요한 숫자예요. 시장은 그 가격을 기준으로 움직이지 않아요.",
    detail: [
      "처음 본 숫자에 판단이 끌려가는 것을 기준점 효과라고 해요.",
      "'본전만 오면'이라는 생각은 회사 상황이 아니라 내가 산 가격에서 나와요.",
      "이 회사를 오늘 처음 본다면 어떻게 볼지 스스로 물어보면 기준점을 잠시 떼어 놓고 볼 수 있어요.",
    ],
    sources: [
      { kind: "연구", label: "Tversky, Kahneman(1974), Judgment under Uncertainty: Heuristics and Biases, Science", url: "https://doi.org/10.1126/science.185.4157.1124" },
      { kind: "연구", label: "Shefrin, Statman(1985), The Disposition to Sell Winners Too Early, Journal of Finance", url: "https://doi.org/10.1111/j.1540-6261.1985.tb05002.x" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "overtrading",
    category: "투자 습관",
    title: "자주 사고팔수록 수익이 낮아지는 경향이 있었대요",
    summary: "미국 6만 6천 가구를 본 연구에서 매매가 가장 잦은 집단의 수익률은 연 11.4%, 같은 기간 시장은 17.9%였대요.",
    detail: [
      "자주 사고팔수록 세금과 수수료가 쌓이고, 때를 잘못 고를 기회도 늘어나요.",
      "국내 연구에서도 2020년 개인의 거래회전율이 연 1,600%에 이르렀고, 수익은 지수에 못 미쳤다고 해요.",
      "자신의 판단을 실제보다 더 믿게 되는 과잉확신이 잦은 매매로 이어진다고 봐요.",
    ],
    sources: [
      { kind: "연구", label: "Barber, Odean(2000), Trading Is Hazardous to Your Wealth, Journal of Finance", url: "https://ideas.repec.org/a/bla/jfinan/v55y2000i2p773-806.html" },
      KCMI_1481,
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "day-trading",
    category: "투자 습관",
    title: "단타로 꾸준히 수익을 내기는 생각보다 어려워요",
    summary: "대만 시장 15년치 데이트레이더를 모두 살펴본 연구에서는, 수수료를 빼고도 꾸준히 수익을 낸 사람이 1%에 못 미쳤대요.",
    detail: [
      "데이트레이딩은 같은 날 같은 종목을 사고파는 거래예요.",
      "평균으로 보면 수수료를 뺀 뒤 하루 약 0.1%씩 손실이었다고 해요.",
      "자주 사고팔수록 수수료와 세금도 함께 쌓여요.",
    ],
    sources: [
      { kind: "연구", label: "Barber, Lee, Liu, Odean(2014), The Cross-Section of Speculator Skill, Journal of Financial Markets", url: "https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "timing-gap",
    category: "투자 습관",
    title: "같은 펀드라도 사고파는 때에 따라 연 1.2%p까지 놓치기도 해요",
    summary: "미국 펀드는 10년간 연 9.9%를 냈지만, 투자자가 실제로 번 돈은 연 8.7%였대요.",
    detail: [
      "오른 뒤에 사고 내린 뒤에 팔면서 생긴 차이예요.",
      "많이 흔들리는 펀드일수록 차이가 커져 연 2.1%p까지 벌어지기도 했대요.",
      "상품의 수익률과 내 수익률은 다를 수 있어요. 언제 들어가고 나왔는지가 함께 결과를 정해요.",
    ],
    sources: [
      { kind: "연구", label: "Morningstar, Mind the Gap(2025년까지 10년 자료)", url: "https://www.morningstar.com/business/insights/research/mind-the-gap-2025" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "missed-best-days",
    category: "투자 습관",
    title: "가장 좋은 10일만 빠져도 연 수익률이 거의 반이 되기도 해요",
    summary: "미국 주식시장 20년 자료에서는 가장 많이 오른 10일만 놓쳐도 연 수익률이 50% 가까이 낮아졌대요.",
    detail: [
      "같은 자료는 가장 좋은 날이 가장 나쁜 날 가까이에 오는 경우가 많다고 설명해요.",
      "급락에 놀라 빠져나오면 바로 이어진 반등일도 함께 놓치기 쉬워요.",
      "오르고 내리는 때를 미리 맞히기는 전문가에게도 쉽지 않은 일이에요.",
    ],
    sources: [
      { kind: "연구", label: "J.P. Morgan Asset Management, 2025 Guide to Retirement", url: "https://am.jpmorgan.com/us/en/asset-management/institutional/about-us/media/press-releases/jp-morgan-asset-management-releases-2025-guide-to-retirement/" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "gamblers-fallacy",
    category: "투자 습관",
    title: "많이 떨어졌다고 반등할 차례가 오는 건 아니에요",
    summary: "동전 앞면이 다섯 번 나와도 다음에 뒷면이 나올 가능성은 그대로예요.",
    detail: [
      "짧은 기간의 결과가 곧 평균으로 돌아갈 거라고 믿는 것을 도박사의 오류라고 해요.",
      "주가가 많이 내린 데에는 이유가 있을 수 있어요. 낙폭 자체는 반등의 근거가 아니에요.",
      "얼마나 떨어졌는지보다 왜 떨어졌는지를 먼저 찾아보면 좋아요.",
    ],
    inService: "종목 상세의 공시와 뉴스에서 최근에 무슨 일이 있었는지 볼 수 있어요.",
    sources: [
      { kind: "연구", label: "Tversky, Kahneman(1971), Belief in the Law of Small Numbers, Psychological Bulletin", url: "https://doi.org/10.1037/h0031322" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "skewed-returns",
    category: "투자 습관",
    title: "시장 전체의 이익은 소수 종목에서 나오는 경우가 많아요",
    summary: "1926년 이후 미국 주식시장이 만든 부는 상위 4% 종목에서 거의 다 나왔대요.",
    detail: [
      "약 2만 6천 종목 중 58%는 상장 기간 전체 수익이 1개월 국채에 미치지 못했다고 해요.",
      "시장 전체는 크게 올랐지만, 그 몫은 아주 적은 종목이 만들었어요.",
      "그래서 한두 종목만 담으면 결과가 시장 전체와 크게 달라질 수 있어요.",
    ],
    sources: [
      { kind: "연구", label: "Bessembinder(2018), Do Stocks Outperform Treasury Bills?, Journal of Financial Economics", url: "https://wpcarey.asu.edu/department-finance/faculty-research/do-stocks-outperform-treasury-bills" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "single-stock-risk",
    category: "투자 습관",
    title: "한 종목에 모아 두면 그 회사 일에 더 크게 흔들려요",
    summary: "한 회사에 생긴 나쁜 일은 여러 종목에 나눠 담으면 일부만 영향을 줘요.",
    detail: [
      "미국 금융이해력 조사의 단골 문항인데, 잘 모르는 사람이 많았대요.",
      "여러 종목을 담으면 한 회사의 사고가 전체에 주는 영향이 작아져요.",
      "종목 수뿐 아니라 같은 업종, 같은 테마에 몰려 있지 않은지도 함께 보면 좋아요.",
    ],
    inService: "대시보드 보유 맵에서 종목별 비중을 볼 수 있어요.",
    sources: [
      { kind: "공공기관", label: "FINRA 투자자교육재단, 미국 투자자 금융이해력 조사(2019)", url: "https://www.finra.org/media-center/newsreleases/2019/many-us-investors-ill-equipped-manage-personal-finances-especially" },
      { kind: "공공기관", label: "미국 SEC 위원장 연설, 2015 National Financial Capability Study 발표", url: "https://www.sec.gov/newsroom/speeches-statements/white-finra-2015-national-financial-capability-study" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "survivorship-bias",
    category: "투자 습관",
    title: "성공담이 많이 들리는 건 실패담이 덜 들려서이기도 해요",
    summary: "사라진 펀드를 빼고 평균을 내면 성과가 실제보다 좋아 보일 수 있어요.",
    detail: [
      "살아남은 것만 보고 판단하는 것을 생존 편향이라고 해요.",
      "미국 펀드 연구에서는 문을 닫은 펀드를 빼면 평균 성과가 실제보다 높게 나왔대요.",
      "'이렇게 해서 벌었다'는 글 뒤에는 같은 방법으로 잃은 사람이 보이지 않을 수 있어요.",
    ],
    sources: [
      { kind: "연구", label: "Elton, Gruber, Blake(1996), Survivorship Bias and Mutual Fund Performance, Review of Financial Studies", url: "https://doi.org/10.1093/rfs/9.4.1097" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "confirmation-bias",
    category: "투자 습관",
    title: "내 생각과 맞는 정보만 눈에 들어오기 쉬워요",
    summary: "취향에 맞는 정보만 받으면 근거는 그대로인데 확신만 커질 수 있어요.",
    detail: [
      "이미 가진 생각을 지지하는 정보를 더 찾고 더 믿는 경향을 확증 편향이라고 해요.",
      "취향에 맞춰 골라 주는 영상과 글은 이 경향을 더 키울 수 있어요.",
      "내 판단과 반대되는 근거를 하나라도 찾아 적어 보면 판단을 점검하는 데 도움이 돼요.",
    ],
    inService: "판단 메모에 반대 근거를 함께 적어 둘 수 있어요.",
    sources: [
      { kind: "연구", label: "자본시장연구원, 유튜브 주식채널의 정보효과와 위험요인(2021)", url: "https://www.kcmi.re.kr/report/report_view?report_no=1235" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "algorithm-trust",
    category: "투자 습관",
    title: "같은 조언도 알고리즘이 냈다고 하면 더 믿게 된대요",
    summary: "사람들은 자동화된 판단을 더 믿고, 그만큼 스스로 확인하는 일을 줄이기 쉬워요.",
    detail: [
      "실험에서 같은 조언이라도 사람보다 알고리즘이 냈다고 할 때 더 많이 따랐대요.",
      "자동화 도구를 쓰면 틀린 결과를 그대로 따라가는 실수도 여러 연구에서 관찰됐어요.",
      "모델 신호는 과거 비슷한 경우의 통계예요. 근거를 함께 보고 최종 판단은 직접 내리는 게 좋아요.",
    ],
    inService: "종목 상세의 '모델이 본 이유'에서 신호의 근거와 과거 범위를 볼 수 있어요.",
    sources: [
      { kind: "연구", label: "Logg, Minson, Moore(2019), Algorithm Appreciation, OBHDP", url: "https://doi.org/10.1016/j.obhdp.2018.12.005" },
      { kind: "연구", label: "Parasuraman, Manzey(2010), Complacency and Bias in Human Use of Automation, Human Factors", url: "https://doi.org/10.1177/0018720810376055" },
    ],
    checkedAt: "2026-11-25",
  },

  // ── 정보 읽기 ──
  {
    id: "theme-stocks",
    category: "정보 읽기",
    title: "테마주는 실적보다 이슈에 따라 함께 움직이는 종목이에요",
    summary: "금감원은 2025년 정치테마주의 평균 영업이익률이 약 1%인데, 하루 주가 변동 폭은 시장 평균의 약 3배였다고 밝혔어요.",
    detail: [
      "테마주는 특정 인물, 정책, 기술 같은 이슈로 묶여 함께 거래되는 종목을 말해요.",
      "같은 자료에서 정치테마주의 개인 거래 비중은 86.9%로, 시장 전체 66.6%보다 높았어요.",
      "이슈가 바뀌면 가격 흐름도 크게 달라질 수 있어서, 회사의 실적과 공시를 함께 보면 판단에 도움이 돼요.",
    ],
    inService: "종목 상세의 '누가 사고팔았나'에서 개인, 외국인, 기관의 매매를 볼 수 있어요.",
    sources: [
      { kind: "보도", label: "이투데이, 금감원과 거래소 정치테마주 점검(2025-05-14)", url: "https://www.etoday.co.kr/news/view/2470362" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "surge-no-reason",
    category: "정보 읽기",
    title: "급등 이유를 물으면 4곳 중 3곳이 '공시할 일 없음'이래요",
    summary: "2024년 거래소가 주가 급변 이유를 물은 116건 중 75%는 회사가 공시할 일이 없다고 답했어요.",
    detail: [
      "주가가 갑자기 크게 움직이면 거래소가 회사에 이유를 공식적으로 묻는데, 이를 조회공시라고 해요.",
      "답이 '중요 공시 없음'이면 회사 안에는 주가를 설명할 새 소식이 없다는 뜻이에요.",
      "같은 해 시장경보 지정 중 32%가 정치인, 반도체 같은 테마와 관련 있었어요.",
    ],
    sources: [
      { kind: "보도", label: "이투데이, 거래소 시장감시위원회 2024 시장경보 분석(2025-03-27)", url: "https://www.etoday.co.kr/news/view/2456662" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "market-warning",
    category: "정보 읽기",
    title: "투자주의, 투자경고, 투자위험은 거래소의 경보 단계예요",
    summary: "거래소는 주가가 짧은 기간에 크게 움직인 종목을 투자주의, 투자경고, 투자위험 순으로 지정해 알려요.",
    detail: [
      "투자경고부터는 살 때 돈을 미리 다 넣어야 하고(증거금 100%) 빚으로 살 수 없어요.",
      "투자위험에 처음 지정되거나 투자경고 중에 더 오르면 거래가 멈출 수 있어요.",
      "지정은 단계를 건너뛸 수 있지만, 풀릴 때는 한 단계씩 내려와요.",
    ],
    inService: "종목 상세 공시에서 '거래 주의' 유형으로 시장경보 지정을 볼 수 있어요.",
    sources: [
      { kind: "업계 자료", label: "KB금융 KB Think, 시장경보제도 안내", url: "https://kbthink.com/stock/market-warning.html" },
      { kind: "보도", label: "이투데이, 거래소 2024 시장경보 분석(2025-03-27)", url: "https://www.etoday.co.kr/news/view/2456662" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-06-01",
  },
  {
    id: "analyst-sell-rare",
    category: "정보 읽기",
    title: "증권사 보고서는 대부분 '매수' 의견으로 나와요",
    summary: "2025년 상반기 국내 20대 증권사 보고서의 매수 의견은 90.4%, 매도 의견은 0.1%였어요.",
    detail: [
      "20곳 중 18곳은 반년 동안 매도 의견을 한 번도 내지 않았어요.",
      "2025년 말 기준 국내 증권사 중 매도 비율이 가장 높은 곳은 1.3%, 외국계는 21.9%였어요.",
      "그래서 의견 한 단어보다 목표 주가와 실적 전망 숫자가 어떻게 바뀌었는지 함께 보면 읽을거리가 더 많아요.",
    ],
    sources: [
      { kind: "보도", label: "주간동아, 금융투자협회 공시 인용(2025-07)", url: "https://v.daum.net/v/20250710090223766" },
      { kind: "보도", label: "뉴데일리, 국내외 증권사 매도 의견 비교(2026-03)", url: "https://biz.newdaily.co.kr/site/data/html/2026/03/18/2026031800103.html" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "low-per-not-chance",
    category: "정보 읽기",
    title: "PER이 낮은 데에는 여러 이유가 있어요",
    summary: "이익이 한 번 크게 늘었거나, 시장이 앞으로 이익이 줄어든다고 보면 PER이 낮게 나오기도 해요.",
    detail: [
      "PER은 주가가 1년 이익의 몇 배인지예요. 이익이 일회성으로 커지면 PER이 갑자기 낮아져요.",
      "업종마다 보통 수준이 달라서 다른 업종끼리 견주면 잘못 읽기 쉬워요.",
      "PER과 함께 이익이 어디서 났는지, 몇 년 동안 어떻게 변했는지를 보면 더 정확히 읽을 수 있어요.",
    ],
    inService: "종목 상세의 재무 탭에서 PER을 코스피 중간값과 견줘 볼 수 있어요.",
    sources: [
      { kind: "공공기관", label: "전국투자자교육협의회, 저PER주라고 사니?", url: "https://www.kcie.or.kr/mobile/guide/series/3/60/web_view?series_idx=60&content_idx=1216" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "good-earnings-drop",
    category: "정보 읽기",
    title: "실적이 좋아도 주가가 떨어질 수 있어요",
    summary: "시장이 미리 기대한 만큼은 발표 전에 이미 주가에 담겨 있곤 해요.",
    detail: [
      "실적 발표 전후 주가를 본 고전 연구에서 이익 정보의 대부분은 발표 전에 이미 주가에 반영돼 있었어요.",
      "그래서 주가는 실적이 좋았는지보다 기대보다 좋았는지에 더 크게 반응하곤 해요.",
      "'좋은 실적'이라는 뉴스 제목만으로 주가 방향을 짐작하기는 어려워요.",
    ],
    sources: [
      { kind: "연구", label: "Ball, Brown(1968), An Empirical Evaluation of Accounting Income Numbers, Journal of Accounting Research", url: "https://doi.org/10.2307/2490232" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "net-vs-operating",
    category: "정보 읽기",
    title: "순이익이 크게 늘어도 본업이 좋아진 건 아닐 수 있어요",
    summary: "건물이나 다른 회사 지분을 팔아 생긴 한 번뿐인 이익도 순이익에 들어가요.",
    detail: [
      "영업이익은 본업으로 번 돈이고, 순이익은 그 밖의 이익과 손실, 세금까지 모두 더하고 뺀 돈이에요.",
      "영업이익은 그대로인데 순이익만 크게 늘었다면 어디서 생긴 이익인지 공시에서 확인해 보면 좋아요.",
      "한 번뿐인 이익은 다음 해에 다시 생기지 않을 수 있어요.",
    ],
    inService: "종목 상세의 재무 탭에서 영업이익률을 볼 수 있어요.",
    sources: [
      { kind: "공공기관", label: "금융감독원 전자공시시스템(DART) 재무제표", url: "https://dart.fss.or.kr" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "disclosure-first",
    category: "정보 읽기",
    title: "뉴스보다 회사가 직접 낸 공시가 원문이에요",
    summary: "상장 회사의 공시는 금융감독원 전자공시시스템(DART)에서 누구나 무료로 볼 수 있어요.",
    detail: [
      "뉴스와 영상은 공시를 요약하거나 해석한 것이라 중요한 조건이 빠질 수 있어요.",
      "유상증자, 전환사채처럼 주식 수가 늘어나는 공시는 기존 주주 몫과 관련이 있어서 원문을 함께 보면 좋아요.",
      "공시 제목과 함께 금액, 조건, 날짜를 보면 내용을 더 정확히 알 수 있어요.",
    ],
    inService: "종목 상세의 공시 목록에서 유형 풀이와 원문 링크를 볼 수 있어요.",
    sources: [
      { kind: "공공기관", label: "금융감독원 전자공시시스템(DART)", url: "https://dart.fss.or.kr" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "leading-room-scam",
    category: "정보 읽기",
    title: "증권사 직원을 사칭하는 불법 리딩방이 있어요",
    summary: "금감원은 2026년 1월 유명 증권사 직원을 사칭하는 불법 리딩방에 소비자경보를 냈어요.",
    detail: [
      "금감원은 주식시장이 뜨거운 때를 틈타 단체 채팅방으로 불러 종목을 찍어 주는 불법 리딩방이 기승이라고 알렸어요.",
      "실제 증권사 직원이라고 소개해도, 그 회사 고객센터에 재직 여부를 직접 물어 확인할 수 있어요.",
      "제도권 금융회사인지는 금융감독원 파인(fine.fss.or.kr)에서 확인할 수 있어요.",
    ],
    sources: [
      { kind: "공공기관", label: "금융감독원 소비자경보, 코스피 및 코스닥 열풍 속 불법 리딩방 주의(2026-01-26)", url: "https://eiec.kdi.re.kr/policy/materialView.do?num=276312" },
      { kind: "공공기관", label: "금융감독원 파인, 제도권 금융회사 조회", url: "https://fine.fss.or.kr" },
    ],
    checkedAt: "2026-11-25",
  },

  // ── 제도와 비용 ──
  {
    id: "transaction-tax",
    category: "제도와 비용",
    title: "주식을 팔 때마다 거래세 0.20%가 빠져요",
    summary: "1,000만 원어치를 팔면 세금만 2만 원이에요. 같은 돈을 1년에 50번 사고팔면 세금만 원금의 약 10%예요.",
    detail: [
      "2026년부터 코스피는 증권거래세 0.05%와 농어촌특별세 0.15%를 합쳐 0.20%예요.",
      "코스닥도 0.20%예요. 여기에 증권사 수수료가 따로 붙어요.",
      "한 번은 작아 보여도 자주 사고팔수록 수익에서 빠지는 몫이 쌓여요.",
    ],
    formula: "1년 거래세 ≈ 매도 금액 × 0.20% × 매도 횟수",
    sources: [
      { kind: "법령과 제도", label: "증권거래세법 시행령(탄력세율)", url: "https://www.law.go.kr/법령/증권거래세법시행령" },
      { kind: "보도", label: "한국세정신문, 2026년 1월부터 증권거래세율 조정(2025-12-01)", url: "https://www.taxtimes.co.kr/news/article.html?no=272624" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-01-01",
  },
  {
    id: "settlement-t2",
    category: "제도와 비용",
    title: "주식을 판 돈은 2영업일 뒤에 출금할 수 있어요",
    summary: "월요일에 팔면 수요일에 돈이 들어와요. 계좌에 금액이 보여도 바로 뺄 수는 없어요.",
    detail: [
      "국내 주식은 거래한 날을 포함해 3영업일째(T+2)에 돈과 주식이 오가요.",
      "주말과 공휴일은 세지 않아서 금요일에 팔면 다음 주 화요일에 들어와요.",
      "거래소는 이를 1영업일(T+1)로 줄이는 계획을 냈어요. 빨라야 2028년 하반기로 예상돼요.",
    ],
    sources: [
      { kind: "보도", label: "뉴시스, 결제주기 T+1 단축 추진(2026-03)", url: "https://www.newsis.com/view/NISX20260318_0003554263" },
      { kind: "보도", label: "한국경제, 거래소와 예탁원 결제주기 단축 로드맵(2026-11)", url: "https://hankyung.com/article/2026110296136" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-11-01",
  },
  {
    id: "price-limit",
    category: "제도와 비용",
    title: "국내 주식은 하루에 위아래 30%까지 움직일 수 있어요",
    summary: "코스피와 코스닥 종목의 하루 가격 변동 한도는 전날 종가의 위아래 30%예요.",
    detail: [
      "2015년 6월 15%에서 30%로 넓어졌어요.",
      "하루에 오르는 쪽도 내리는 쪽도 30%까지 열려 있다는 뜻이에요. 2배 레버리지 상품은 이론상 하루 60%까지 움직일 수 있어요.",
      "급하게 움직이면 잠깐 거래를 멈추는 장치(변동성 완화장치)도 함께 있어요.",
    ],
    sources: [
      { kind: "보도", label: "이투데이, 6월 15일부터 가격제한폭 30%로 확대(2015)", url: "https://www.etoday.co.kr/news/view/1127429" },
      { kind: "공공기관", label: "금융위원회, 단일종목 레버리지 상품 투자 유의사항(2026-05)", url: "https://www.fsc.go.kr/po010107/86973" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "no-deposit-insurance",
    category: "제도와 비용",
    title: "주식과 ETF는 예금자보호 대상이 아니에요",
    summary: "예금자보호는 1억 원까지 예적금을 지켜 주지만, 값이 오르내리는 투자상품은 빠져요.",
    detail: [
      "2025년 9월 1일부터 예금자보호 한도가 1억 원이 됐어요.",
      "펀드 같은 금융투자상품은 보호 대상에서 빠져요. 증권 계좌에 현금으로 남은 예탁금과 그 돈으로 산 주식은 다르게 취급돼요.",
      "주가가 내려 생긴 손실은 누구도 메워 주지 않아요.",
    ],
    sources: [
      { kind: "공공기관", label: "금융위원회, 예금보호한도 상향 주요 문답(2025-07-22)", url: "https://fsc.go.kr/po020201/84975" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "leverage-decay",
    category: "제도와 비용",
    title: "2배 레버리지는 오래 들수록 2배와 달라지기 쉬워요",
    summary: "금융위원회가 든 예에서는 한 미국 종목이 1년간 18% 오를 때, 그 종목의 2배 상품은 36%가 아니라 20% 손실이었어요.",
    detail: [
      "레버리지 상품은 하루 수익률의 2배를 따라가요. 날마다 다시 맞추기 때문에 오래 들면 차이가 쌓여요.",
      "기초 자산이 30% 오른 뒤 30% 내리면 1배는 -9%, 2배는 -36%예요.",
      "그래서 금융위원회는 이 상품이 오래 보유하는 데 맞지 않는다고 안내해요.",
      "처음 사려면 사전교육 2시간을 듣고 기본예탁금 1천만 원이 있어야 해요.",
    ],
    formula: "(1 + 2 × 0.3) × (1 − 2 × 0.3) = 1.6 × 0.4 = 0.64",
    sources: [
      { kind: "공공기관", label: "금융위원회, 단일종목 레버리지 상품 투자 유의사항(2026-05)", url: "https://www.fsc.go.kr/po010107/86973" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-06-01",
  },
  {
    id: "covered-call-yield",
    category: "제도와 비용",
    title: "ETF 이름의 '분배율 12%'는 정해진 수익이 아니에요",
    summary: "금감원은 커버드콜 ETF 이름의 분배율이 운용사의 목표일 뿐 확정 수익이 아니라고 안내했어요.",
    detail: [
      "분배금은 ETF가 가진 자산에서 나가요. 주는 만큼 ETF 가격도 낮아지는데, 이를 분배락이라고 해요.",
      "주가가 크게 오를 때 얻는 몫은 제한되고, 내릴 때는 손실이 그대로 반영돼요.",
      "분배율과 함께 가격 변화와 분배금을 합친 전체 수익을 보면 좋아요.",
    ],
    sources: [
      { kind: "보도", label: "세계일보, 금감원 커버드콜 ETF 유의사항(2024-07)", url: "https://www.segye.com/newsView/20240728509563" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "margin-forced-sale",
    category: "제도와 비용",
    title: "빚으로 산 주식은 내 뜻과 상관없이 팔릴 수 있어요",
    summary: "신용이나 미수로 산 주식이 담보 기준 아래로 내려가면 증권사가 시장에서 강제로 파는데, 이를 반대매매라고 해요.",
    detail: [
      "반대매매는 보통 장이 열리자마자 낮은 가격에 한꺼번에 나가서 손실이 더 커지기 쉬워요.",
      "담보 기준과 유예 방식은 증권사마다 달라서 내 증권사 기준을 따로 확인해 두면 좋아요.",
      "빌린 돈은 수익만큼 손실도 키워요. 가격이 내려도 갚을 돈은 그대로예요.",
    ],
    sources: [
      { kind: "보도", label: "머니투데이, 신용융자 담보비율과 반대매매(2026-11-06)", url: "https://www.mt.co.kr/article/2026110614220822255" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-02-01",
  },
  {
    id: "dividend-record-date",
    category: "제도와 비용",
    title: "배당 기준일이 꼭 12월 말은 아니에요",
    summary: "2023년 제도 개선으로 배당액을 먼저 정하고 배당 받을 주주를 그 뒤에 정할 수 있게 됐어요.",
    detail: [
      "예전에는 연말에 주식을 가지고 있어야 배당을 받았고, 배당액은 이듬해 봄에야 알 수 있었어요.",
      "이제는 회사가 정관과 이사회 결정으로 기준일을 정해서, 회사마다 날짜가 다를 수 있어요.",
      "배당 기준일과 금액은 그 회사의 배당 공시에서 확인할 수 있어요.",
    ],
    sources: [
      { kind: "공공기관", label: "금융위원회, 배당절차 개선방안(2023-01-31)", url: "https://www.fsc.go.kr/po010105/79358" },
    ],
    checkedAt: "2026-11-25",
  },
  {
    id: "overseas-stock-tax",
    category: "제도와 비용",
    title: "해외 주식 이익은 250만 원 넘는 몫에 22% 세금이에요",
    summary: "국내 주식과 달리 해외 주식 매매 이익은 다음 해 5월에 직접 신고하고 세금을 내요.",
    detail: [
      "1년 동안 해외 주식에서 난 이익과 손실을 합친 뒤 250만 원을 빼고 22%를 내요.",
      "1,000만 원을 벌었다면 750만 원의 22%인 165만 원이에요.",
      "여러 증권사 계좌의 해외 주식 손익을 모두 합쳐서 계산해요.",
    ],
    formula: "세금 = (1년 해외 주식 순이익 − 250만 원) × 22%",
    sources: [
      { kind: "보도", label: "서울신문, 서학개미 양도세 가이드(2026-05)", url: "https://www.seoul.co.kr/news/newsView.php?id=20260525500093" },
      { kind: "법령과 제도", label: "소득세법 제103조(양도소득 기본공제)", url: "https://www.law.go.kr/법령/소득세법/제103조" },
      { kind: "법령과 제도", label: "소득세법 제110조(양도소득 확정신고)", url: "https://www.law.go.kr/법령/소득세법/제110조" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-03-01",
  },
  {
    id: "etf-tax-differs",
    category: "제도와 비용",
    title: "같은 국내 상장 ETF라도 세금이 달라요",
    summary: "국내 주식형 ETF는 매매 이익에 세금이 없지만, 해외 주식을 담은 ETF는 15.4%를 떼요.",
    detail: [
      "ETF가 무엇을 담았는지에 따라 세금 규칙이 나뉘어요.",
      "분배금에는 두 경우 모두 보통 15.4%가 붙어요.",
      "매매 이익과 분배금을 합친 금융소득이 1년에 2천만 원을 넘으면 다른 소득과 합쳐 세금을 매겨요.",
    ],
    sources: [
      { kind: "업계 자료", label: "KB자산운용, 국내 상장 ETF 세금 안내", url: "https://kbam.co.kr/insights/guide/etf-tax-guide-domestic-vs-other-types" },
      { kind: "업계 자료", label: "토스피드, ETF 세금 정리", url: "https://toss.im/tossfeed/article/etf-and-tax" },
    ],
    checkedAt: "2026-11-25",
    reviewBy: "2027-03-01",
  },
];
