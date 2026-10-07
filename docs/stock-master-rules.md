# 종목 마스터 위험 표시 규칙

`backend/analysis/chart/stock_master.py`가 차트 서빙 universe(코스피 전 종목 + 에코프로비엠)로 `stocks`를 넣고 고칩니다. 차트 서빙 워크플로의 마지막 step(`python -m stock_master`)에서 매일 돌고, 행은 지우지 않습니다. 가격은 `chart_prices`(수정주가·거래대금)를 씁니다.

| 표시 | 규칙 | 상수 |
|---|---|---|
| `spac` | 이름에 "스팩" | — |
| `preferred_stock` | 코드 끝자리가 0이 아니고, 이름이 `우`·`우B`·`우(전환)` 등으로 끝남 | `PREFERRED_NAME` |
| `penny_stock` | 최근 종가 1,000원 미만 | `PENNY_CLOSE = 1000` |
| `low_liquidity` | 20거래일 평균 거래대금이 전 종목 하위 10% | `LIQUIDITY_DAYS = 20`, `LOW_LIQUIDITY_QUANTILE = 0.10` |
| `high_volatility` | 연 환산 변동성(최근 250거래일, 일간 로그수익률 표준편차 × √252)이 상위 10% | `VOLATILITY_DAYS = 250`, `HIGH_VOLATILITY_QUANTILE = 0.90` |
| `managed_stock` | KRX KIND 관리종목 목록(공개 페이지)과 종목명이 같음 | `KIND_URL` |
| `risk_grade` | 연 변동성 **절대 기준**: 0.25 미만 → 5(매우 안전), 0.40 미만 → 4, 0.60 미만 → 3, 0.90 미만 → 2, 그 이상 → 1(매우 위험). **대형주(시가총액 상위 100, KRX 상장 목록)는 한 단계 완화**(최대 5). 변동성 데이터가 60거래일 미만이거나 가격이 한 번도 움직이지 않았거나(거래정지 등) `spac`·`managed_stock`이면 1 | `GRADE_VOLATILITY_CUTS = (0.25, 0.40, 0.60, 0.90)`, `LARGE_CAP_RANK = 100`, `MIN_VOLATILITY_DAYS = 60` |

- 등급은 2026-10-08부터 절대 기준이다(그전에는 universe 안 5분위 상대 등급이라, 시장 전체가 흔들리면 대형주도 1이 나왔다). 변동성 계산은 FinanceDataReader 종가로 따로 계산한 값과 같음을 확인했다(삼성전자 0.868, SK하이닉스 1.016, 현대차 0.691, 2026-02~10).
- KIND 목록이나 KRX 상장 목록(시가총액)을 받지 못하면 아무것도 쓰지 않고 실패합니다. 관리종목 여부가 확인되지 않은 종목이 "관리종목 회피"를 통과하지 않게 하려는 것입니다(하드 제약은 보수적으로). 이 경우 전날 값이 그대로 남습니다.
- `low_liquidity`·`high_volatility`의 하위·상위 구간은 그날 universe 전체 기준이라, 종목 수가 바뀌면 같은 값이어도 표시가 달라질 수 있습니다.
- `chart_prices`는 2026-02부터 쌓여 있어, 지금은 "1년" 변동성이 실제로는 약 8개월치입니다.
