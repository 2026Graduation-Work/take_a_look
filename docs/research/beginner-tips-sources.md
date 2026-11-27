# "알고 계셨나요" 팁 레퍼런스 조사 (2026-11-25)

#491 팁 띠와 이용 안내 "초보가 자주 하는 실수"에 넣을 문구의 근거를 모은 기록이다. 문구 정본은 [frontend/lib/beginner-tips.ts](../../frontend/lib/beginner-tips.ts)이고, 이 문서는 **어디서 어떻게 골랐는지**와 **무엇을 다시 확인해야 하는지**만 적는다.

## 고른 기준

1. **초보자가 당연하게 여기지만 틀린 것**이다. 계산 착각(떨어진 만큼 오르면 본전), 투자 습관(오른 것만 판다), 정보 읽기(실적이 좋으면 주가가 오른다), 제도와 비용(판 돈은 바로 뺄 수 있다)으로 나눴다.
2. **숫자나 원문으로 확인할 수 있다.** 계산식이거나, 공공기관 자료, 학술 논문, 원 자료를 밝힌 보도에 있다.
3. **매매 지시가 아니다.** 사실과 연구 결과만 말하고, 행동은 "확인해요" 수준까지만 쓴다(AGENTS.md 사용자 노출 표현 규칙).
4. **반박 형식**으로 쓴다. 흔한 오해를 짚고 바로잡는 글이 일반 설명보다 개념을 바꾸는 데 낫다는 정리([Tippett 2010](https://doi.org/10.1007/s10763-010-9203-x))를 따랐다. 이 서비스에서의 효과는 검증하지 않은 가설이다.

## 말투 기준 (2026-11-25 진세 검토)

- **계산과 법령처럼 100% 확실한 사실만 단정한다.** "-30%면 본전까지 +42.9%", "거래세 0.20%"는 그대로 쓴다.
- **연구 결과와 경향은 완곡하게 쓴다.** "~했대요", "~곤 해요", "~기도 해요", "~분이 많아요"처럼 출처의 범위 안에서 말한다. "~였어요"로 일반화하지 않는다.
- **투자를 부추기거나 겁주는 문구를 쓰지 않는다.** "10개 중 7개가 고점보다 30% 내렸어요", "좋은 기회" 같은 말 대신 개념과 사실을 알려 준다(예: 테마주가 무엇인지, 경보 단계가 무엇인지).
- **행동은 권하지 않고 도움이 되는 방법만 알린다.** "확인해요" 대신 "확인해 보면 좋아요", "확인할 수 있어요".
- **공격적이거나 비꼬는 표현을 쓰지 않는다.** "1%도 안 됐어요" 대신 "생각보다 어려워요"처럼 쓴다.

## 어디서 찾았나

| 층 | 어디 | 쓰는 이유 |
|---|---|---|
| 계산식 | 수익률, 복리, 평단, 세금 계산 | 누구나 다시 계산할 수 있다. 숫자는 테스트로 고정했다 |
| 법령과 제도 | 국가법령정보센터(소득세법, 증권거래세법 시행령) | 세율과 신고 규칙의 원문 |
| 공공기관 | 금융위원회 보도자료와 문답, 금융감독원 소비자경보(KDI 경제정보센터 수록), DART, 파인, 전국투자자교육협의회, FINRA 투자자교육재단, 미국 SEC | 당국이 직접 낸 주의 안내와 교육 자료 |
| 연구 | 자본시장연구원(KCMI), Journal of Finance 등 학술지, Morningstar, J.P. Morgan 자산운용 | 국내 개인 20만 명 거래 자료, 행동재무학 고전 연구 |
| 보도 | 금감원, 거래소, 금융투자협회 자료를 인용한 기사 | 원 자료가 보도로만 공개된 경우. 제목이 아니라 본문 수치를 확인했다 |
| 업계 자료 | 운용사와 금융회사 안내(KB자산운용, KB Think, 토스피드) | 세금 구분처럼 공공 원문이 흩어진 제도 설명 |

다음에 팁을 더 찾을 때도 같은 순서로 본다. 국내 [금감원 소비자경보](https://eiec.kdi.re.kr), [자본시장연구원 보고서](https://www.kcmi.re.kr), 해외 투자자 교육 기관(SEC Investor.gov, FINRA)의 "흔한 실수" 목록이 후보를 가장 많이 준다.

## 검증하며 고친 것

출처 원문을 다시 열어 문장과 대조했다. 원문에 없는 내용은 지웠다.

| 처음 쓴 내용 | 원문 확인 결과 | 고친 내용 |
|---|---|---|
| KCMI 1206: 개인은 보유 종목 수가 적고 중소형주에 쏠린다 | 보고서(최근 개인투자자 주식 매수의 특징 및 평가, 2020)는 2020년 개인이 **중대형주**를 더 많이 샀다고 쓴다. 종목 수 분석은 없다 | 출처에서 빼고 FINRA 조사와 SEC 연설로 바꿨다 |
| J.P. Morgan: 가장 좋은 10일 중 7일이 가장 나쁜 10일과 2주 안 | 2025년판 보도자료에는 이 수치가 없다(2024년판 2차 보도에만 있음) | 원문에 있는 "10일을 놓치면 연 수익률이 50% 가까이 줄었다"로 바꿨다 |
| 금감원 리딩방 경보: 1:1 대화방, AI 딥페이크, 2026-3호 | 수록 페이지 본문에 없다 | 원문의 증권사 직원 사칭, 단체 채팅방, 재직 확인 안내만 남겼다 |
| 커버드콜: 분배금이 1만 원당 919원까지 | 인용한 기사에 없다 | 지웠다 |
| 데이트레이딩: 한 해 번 사람도 다음 해엔 드물다 | 논문은 상위 1% 미만은 이듬해에도 꾸준히 벌었다고 쓴다 | 지우고 "평균 하루 약 0.1% 손실"로 바꿨다 |
| 예금자보호: 5천만 원에서 1억 원 | 인용한 금융위 문답에 이전 한도가 없다 | "2025년 9월 1일부터 1억 원"만 남겼다 |
| 해외 주식: 국내 주식 손익과 합치지 않는다 | 인용한 기사에 없다 | "모든 계좌의 해외 주식 손익을 합친다"로 바꿨다 |
| 2020년 신규 투자자 60% 손실(KCMI 1481) | 6년 전 자료이고, 2025~2026 상승장 자료와 결이 다르다 | 2026년 1월 한 달 코스피 21.4% 대 개인 계좌 평균 4.18%(한국경제, 주요 증권사 의뢰), 2025년 10월 말 NH투자증권 고객 54.6% 평가 손실(연합뉴스 의뢰 보도)로 바꿨다. 증권사 표본이라 전체 개인을 대표하지 않는다 |
| 정치테마주 72%가 고점보다 30% 넘게 하락 | 원문은 맞지만 투자 판단을 부추길 수 있는 표현 | 테마주의 정의와 실적, 변동 폭, 개인 비중 같은 정보로 바꿨다 |
| 액면분할로 회사 값은 같다 | 분할 순간은 맞지만 그 뒤 주가는 다른 이유로 움직인다 | "나누는 순간"으로 범위를 좁히고 분할 뒤 움직임을 함께 적었다 |
| KCMI 1481: 이익 주식을 팔 확률이 두 배 | 보고서 원문 확인. 위험비율 2.18배, 매수 다음 날 이익 41%, 손실 22% 매도 | 수치를 원문대로 적었다 |

같은 대조에서 [초보 투자자 문제 점검](../product/beginner-gap.md) 4번 행의 KCMI 1206 인용("중소형주 비중이 높다")도 원문과 맞지 않음을 찾았다. 그 문서는 이번 범위가 아니라 고치지 않았다.

## 팁 목록

42개. 다시 볼 날은 세율, 결제 주기, 레버리지 규제처럼 바뀌는 제도에만 단다. 이 날이 지나면 원문을 다시 열고 `checkedAt`을 고친다.

| id | 분류 | 띠 문구 | 출처 | 다시 볼 날 |
|---|---|---|---|---|
| loss-recovery | 계산 착각 | -30%가 되면 본전까지 +42.9%가 필요해요 | 계산식 |  |
| up-down-not-even | 계산 착각 | +10% 오른 뒤 -10%면 원금보다 1% 적어요 | 계산식 |  |
| average-return-trap | 계산 착각 | 평균 수익률 +25%인데 돈은 그대로일 수 있어요 | 계산식 |  |
| averaging-down | 계산 착각 | 평단이 낮아져도 손실 금액은 그대로예요 | 계산식 |  |
| rule-of-72 | 계산 착각 | 연 6%면 원금이 두 배 되는 데 약 12년 걸려요 | 계산식 |  |
| real-return | 계산 착각 | 이자 3%에 물가 3%면 실제로 늘어난 건 거의 없어요 | 계산식, [보도](https://www.dt.co.kr/article/11661613) |  |
| price-is-not-size | 계산 착각 | 주가가 낮다고 작은 회사는 아니에요 | 계산식 |  |
| stock-split | 계산 착각 | 액면분할은 한 주를 여러 주로 잘게 나누는 거예요 | 계산식, [보도](https://www.newsis.com/view/NISX20180504_0000300042) |  |
| dividend-why | 계산 착각 | 배당은 회사가 번 이익을 주주와 나누는 방법이에요 | [공공기관](https://www.mofe.go.kr/sisa/dictionary/detail?idx=1149), [보도](https://sgsg.hankyung.com/article/2025061326911), [법령과 제도](https://www.law.go.kr/법령/소득세법/제129조) | 2027-03-01 |
| disposition-effect | 투자 습관 | 오른 주식은 일찍 팔고 내린 주식은 오래 두는 분이 많아요 | [연구](https://www.kcmi.re.kr/report/report_view?report_no=1481), [연구](https://doi.org/10.1111/0022-1082.00072) |  |
| index-vs-account | 투자 습관 | 지수가 크게 올라도 내 계좌는 다르게 움직이곤 해요 | [보도](https://www.hankyung.com/article/2026012272041), [보도](https://kr.investing.com/news/stock-market-news/article-1708696) |  |
| loss-aversion | 투자 습관 | 보통 잃은 아픔을 번 기쁨보다 두 배쯤 크게 느낀대요 | [연구](https://doi.org/10.1007/BF00122574) |  |
| buy-price-anchor | 투자 습관 | 주가는 내가 산 가격을 몰라요 | [연구](https://doi.org/10.1126/science.185.4157.1124), [연구](https://doi.org/10.1111/j.1540-6261.1985.tb05002.x) |  |
| overtrading | 투자 습관 | 자주 사고팔수록 수익이 낮아지는 경향이 있었대요 | [연구](https://ideas.repec.org/a/bla/jfinan/v55y2000i2p773-806.html), [연구](https://www.kcmi.re.kr/report/report_view?report_no=1481) |  |
| day-trading | 투자 습관 | 단타로 꾸준히 수익을 내기는 생각보다 어려워요 | [연구](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html) |  |
| timing-gap | 투자 습관 | 같은 펀드라도 사고파는 때에 따라 연 1.2%p까지 놓치기도 해요 | [연구](https://www.morningstar.com/business/insights/research/mind-the-gap-2025) |  |
| missed-best-days | 투자 습관 | 가장 좋은 10일만 빠져도 연 수익률이 거의 반이 되기도 해요 | [연구](https://am.jpmorgan.com/us/en/asset-management/institutional/about-us/media/press-releases/jp-morgan-asset-management-releases-2025-guide-to-retirement/) |  |
| gamblers-fallacy | 투자 습관 | 많이 떨어졌다고 반등할 차례가 오는 건 아니에요 | [연구](https://doi.org/10.1037/h0031322) |  |
| skewed-returns | 투자 습관 | 시장 전체의 이익은 소수 종목에서 나오는 경우가 많아요 | [연구](https://wpcarey.asu.edu/department-finance/faculty-research/do-stocks-outperform-treasury-bills) |  |
| single-stock-risk | 투자 습관 | 한 종목에 모아 두면 그 회사 일에 더 크게 흔들려요 | [공공기관](https://www.finra.org/media-center/newsreleases/2019/many-us-investors-ill-equipped-manage-personal-finances-especially), [공공기관](https://www.sec.gov/newsroom/speeches-statements/white-finra-2015-national-financial-capability-study) |  |
| survivorship-bias | 투자 습관 | 성공담이 많이 들리는 건 실패담이 덜 들려서이기도 해요 | [연구](https://doi.org/10.1093/rfs/9.4.1097) |  |
| confirmation-bias | 투자 습관 | 내 생각과 맞는 정보만 눈에 들어오기 쉬워요 | [연구](https://www.kcmi.re.kr/report/report_view?report_no=1235) |  |
| algorithm-trust | 투자 습관 | 같은 조언도 알고리즘이 냈다고 하면 더 믿게 된대요 | [연구](https://doi.org/10.1016/j.obhdp.2018.12.005), [연구](https://doi.org/10.1177/0018720810376055) |  |
| theme-stocks | 정보 읽기 | 테마주는 실적보다 이슈에 따라 함께 움직이는 종목이에요 | [보도](https://www.etoday.co.kr/news/view/2470362) |  |
| surge-no-reason | 정보 읽기 | 급등 이유를 물으면 4곳 중 3곳이 '공시할 일 없음'이래요 | [보도](https://www.etoday.co.kr/news/view/2456662) |  |
| market-warning | 정보 읽기 | 투자주의, 투자경고, 투자위험은 거래소의 경보 단계예요 | [업계 자료](https://kbthink.com/stock/market-warning.html), [보도](https://www.etoday.co.kr/news/view/2456662) | 2027-06-01 |
| analyst-sell-rare | 정보 읽기 | 증권사 보고서는 대부분 '매수' 의견으로 나와요 | [보도](https://v.daum.net/v/20250710090223766), [보도](https://biz.newdaily.co.kr/site/data/html/2026/03/18/2026031800103.html) |  |
| low-per-not-chance | 정보 읽기 | PER이 낮은 데에는 여러 이유가 있어요 | [공공기관](https://www.kcie.or.kr/mobile/guide/series/3/60/web_view?series_idx=60&content_idx=1216) |  |
| good-earnings-drop | 정보 읽기 | 실적이 좋아도 주가가 떨어질 수 있어요 | [연구](https://doi.org/10.2307/2490232) |  |
| net-vs-operating | 정보 읽기 | 순이익이 크게 늘어도 본업이 좋아진 건 아닐 수 있어요 | [공공기관](https://dart.fss.or.kr) |  |
| disclosure-first | 정보 읽기 | 뉴스보다 회사가 직접 낸 공시가 원문이에요 | [공공기관](https://dart.fss.or.kr) |  |
| leading-room-scam | 정보 읽기 | 증권사 직원을 사칭하는 불법 리딩방이 있어요 | [공공기관](https://eiec.kdi.re.kr/policy/materialView.do?num=276312), [공공기관](https://fine.fss.or.kr) |  |
| transaction-tax | 제도와 비용 | 주식을 팔 때마다 거래세 0.20%가 빠져요 | [법령과 제도](https://www.law.go.kr/법령/증권거래세법시행령), [보도](https://www.taxtimes.co.kr/news/article.html?no=272624) | 2027-01-01 |
| settlement-t2 | 제도와 비용 | 주식을 판 돈은 2영업일 뒤에 출금할 수 있어요 | [보도](https://www.newsis.com/view/NISX20260318_0003554263), [보도](https://hankyung.com/article/2026110296136) | 2027-11-01 |
| price-limit | 제도와 비용 | 국내 주식은 하루에 위아래 30%까지 움직일 수 있어요 | [보도](https://www.etoday.co.kr/news/view/1127429), [공공기관](https://www.fsc.go.kr/po010107/86973) |  |
| no-deposit-insurance | 제도와 비용 | 주식과 ETF는 예금자보호 대상이 아니에요 | [공공기관](https://fsc.go.kr/po020201/84975) |  |
| leverage-decay | 제도와 비용 | 2배 레버리지는 오래 들수록 2배와 달라지기 쉬워요 | [공공기관](https://www.fsc.go.kr/po010107/86973) | 2027-06-01 |
| covered-call-yield | 제도와 비용 | ETF 이름의 '분배율 12%'는 정해진 수익이 아니에요 | [보도](https://www.segye.com/newsView/20240728509563) |  |
| margin-forced-sale | 제도와 비용 | 빚으로 산 주식은 내 뜻과 상관없이 팔릴 수 있어요 | [보도](https://www.mt.co.kr/article/2026110614220822255) | 2027-02-01 |
| dividend-record-date | 제도와 비용 | 배당 기준일이 꼭 12월 말은 아니에요 | [공공기관](https://www.fsc.go.kr/po010105/79358) |  |
| overseas-stock-tax | 제도와 비용 | 해외 주식 이익은 250만 원 넘는 몫에 22% 세금이에요 | [보도](https://www.seoul.co.kr/news/newsView.php?id=20260525500093), [법령과 제도](https://www.law.go.kr/법령/소득세법/제103조), [법령과 제도](https://www.law.go.kr/법령/소득세법/제110조) | 2027-03-01 |
| etf-tax-differs | 제도와 비용 | 같은 국내 상장 ETF라도 세금이 달라요 | [업계 자료](https://kbam.co.kr/insights/guide/etf-tax-guide-domestic-vs-other-types), [업계 자료](https://toss.im/tossfeed/article/etf-and-tax) | 2027-03-01 |

## 아직 하지 않은 것

- **화면 연결.** 띠, 펼침, 닫기, `/guide` 섹션, 로딩 화면 표시는 #490 머지 뒤 #491에서 한다. 이 목록은 데이터와 테스트만 둔다.
- **띠에 돌릴 묶음.** #491은 14개를 전제로 했다. 42개를 모두 돌릴지, 계산 착각과 투자 습관 위주로 고를지 정해야 한다.
- **사람 검토.** 문구는 근거와 규칙 테스트를 통과했지만, 초보자가 실제로 이해하는지는 사용성 평가에서 확인한다.
