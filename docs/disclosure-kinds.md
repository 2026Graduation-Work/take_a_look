# 공시 유형표

`backend/analysis/text/value_pipeline/disclosures.py` `KIND_RULES`가 DART 공시 제목(보고서명)으로 유형을 정한다. 위에서부터 처음 맞는 규칙을 쓴다. 화면 이름·쉬운 풀이는 `frontend/lib/copy-glossary.ts` `DISCLOSURE_KIND`.

| 유형 | 제목 규칙(정규식) | 화면 이름 |
|---|---|---|
| market_action | 관리종목·상장폐지·불성실공시·투자주의·투자경고·투자위험·매매거래정지 | 거래 주의 |
| business_risk | 횡령·배임·자본잠식·생산중단·회생절차·부도 | 경영 위험 |
| inquiry | 조회공시·풍문 | 조회 공시 |
| periodic | 사업보고서·반기보고서·분기보고서 | 정기보고서 |
| earnings | (잠정)실적·영업실적·매출액또는손익구조 | 실적 발표 |
| contract | 단일판매·공급계약 | 공급 계약 |
| capital_raise | 유상증자 | 유상증자 |
| bonus_issue | 무상증자 | 무상증자 |
| bond | 전환사채·신주인수권부사채·교환사채 | 사채 발행 |
| buyback | 자기주식·주식소각 | 자사주 |
| dividend | 배당 | 배당 |
| restructure | 합병·분할·영업양수·영업양도·주식교환 | 합병·분할 |
| ownership | 최대주주·주요주주·대량보유 | 지분 변동 |
| lawsuit | 소송 | 소송 |
| investment | 타법인주식·출자증권·채무보증 | 투자·보증 |
| shareholder_meeting | 주주총회·의결권·주주명부 | 주주총회 |
| investor_relations | 기업설명회·실적공시예고 | 기업설명회 |
| securities_filing | 증권발행실적·일괄신고·투자설명서·증권신고서 | 증권 발행 서류 |
| other | 위에 없는 것 | 기타 |

2026-10-07 운영 첫 적재(최근 3일, 295건): 지분 변동 127 · 증권 발행 서류 79 · 공급 계약 17 · 기타 12 · 그 밖 60.
