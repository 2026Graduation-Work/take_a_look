# 출처·기준 시점 표시 조사 (2026-10-10)

"필요한 것만, 흔들림 없이" 화면 정리(Task 2) 전에, 다른 서비스가 **기준 시점과 출처를 어디에 몇 번** 보여 주는지 확인했다.
직접 열어 본 것과 문서로만 본 것을 나눠 적는다.

| 서비스 | 기준 시점 | 출처 | 확인 방법 |
|---|---|---|---|
| 토스증권 종목 상세(웹, `tossinvest.com/stocks/A005930/analytics`) | 화면 공통 시각은 한 곳("20:45 기준", 시세는 "실시간"). 항목 날짜는 **다를 때만** 그 항목 옆에 붙인다: 상장주식수 "(26년 10월 9일 기준)", 재무 "25년 12월 기준", 산업 비중 "(2020년 12월 기준)" | 데이터 묶음 끝에 한 줄 "출처: FnGuide 및 기업 IR자료". 카드마다 버튼으로 두지 않음 | 2026-10-10 Playwright로 열어 본문 텍스트 추출 |
| Our World in Data 차트(`/grapher/population-unwpp`) | 차트 아래 목록에 "Last updated 2024-07-12" 한 번, "Date range"·"Next expected update" | 같은 목록에 "Data source: UN, World Population Prospects (2024) – processed by Our World in Data" 한 번. 가공 과정·인용은 "Sources and processing"(더 보기)로 접어 둠 | WebFetch로 페이지 구조 확인 |
| FT 차트(사내 차트 프레임 `g-chartframe`, npm 5.3.3) | 제목 아래 부제(`subtitle`)에 단위·기간 | 그래픽마다 **아래쪽 source 한 줄**(`frame.source("Source: FT Research|Graphic: …")`). 출처·주석·크레딧을 같은 줄에 | 패키지 README의 frame API |
| 애플 주식 앱 | 공식 문서(Apple 지원 "Check stocks on iPhone")에서 기준 시각·제공자 표기 위치를 확인하지 못했다 | 〃 | 판정에서 뺌(앱 관찰 없이 기억으로 쓰지 않는다) |

## 가져올 것 / 버릴 것

| 가져올 것 | 근거 | 우리 화면 |
|---|---|---|
| 공통 기준 시점은 **한 곳에 한 번** | 토스 "20:45 기준", OWID "Last updated" | 시장 바 "2026.10.08 기준" 한 번 |
| 항목 날짜는 **공통과 다를 때만** 그 옆에 | 토스 "25년 12월 기준", "(26년 10월 9일 기준)" | 재무 보고서 시점, 뉴스 수집 시각, 2영업일 이상 밀린 데이터만 카드에 날짜 |
| 출처는 **묶음 끝에 한 번**, 글로 | 토스 "출처: FnGuide…", FT 그래픽 아래 source 한 줄, OWID 차트 아래 목록 | 카드별 출처 버튼(SourceLine) 대신 페이지 맨 아래 "데이터 출처·기준" 표 하나 |
| 자세한 가공 설명은 **접어 둔다** | OWID "Sources and processing" | 상세는 "더 알아보기" 안 출처 표, 대시보드는 하단 같은 형식 표 |

| 버릴 것 | 이유 |
|---|---|
| 카드마다 "출처 · 날짜 ▾" 접는 버튼 | 토스·FT·OWID 모두 카드 단위 버튼이 없다. 같은 날짜가 화면에 열 번 넘게 반복돼 정작 다른 날짜가 묻힌다 |
| 마우스를 올려야 보이는 설명 창 | 터치 기기에서 열 방법이 없고, 키보드 포커스로 열리는 창은 Tab 이동 중 화면을 가린다. 누르면 열고 바깥·Esc로 닫는다 |
| 열린 창 안의 또 다른 접는 버튼 | 두 번 눌러야 내용이 보이고, 닫을 때 어느 것을 닫는지 헷갈린다 |
| FT식 그래픽 안 크레딧("Graphic: 이름") | 우리 화면은 기사 그래픽이 아니다 |

출처: [Our World in Data — population-unwpp](https://ourworldindata.org/grapher/population-unwpp) · [FT g-chartframe README(npm)](https://www.npmjs.com/package/g-chartframe) · [토스증권 삼성전자 종목 분석](https://www.tossinvest.com/stocks/A005930/analytics) · [Apple 지원 — Check stocks on iPhone](https://support.apple.com/guide/iphone/check-stocks-iph1ac0b1bc/ios)
