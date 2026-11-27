# 권리 이벤트 검토 감소 검증

목표는 공시와 KRX 수치가 함께 맞는 사건만 자동 판정으로 옮기고 기존 자동 판정과 종목 범위를 보존하는 것이다. #478의 `feat/chart-action-segments` (`d99621c`) 위 `feat/chart-action-review`에서 구현했다. 스택 rebase는 하지 않았다.

## 원문 기반 후속 보완

현재 결과다. 시장 검토 **992→965건**, 학습 검토 **826→799건**이다. 신규 자동 27건은 추가상장 원문 보완 5건, 배당 정정 본문 파싱 20건, 영문 병기 회사명 연결 2건이다. 기존 자동 4,191행은 `Reason`·`Evidence`·`FailedCheck`를 포함한 행 전체가 같고, 판정 identity 5,183개·후보 4,807행·상장 구간 3,563개를 보존했다. 각 단계 전체 재판정의 KIND·DART HTTP는 0회다.

| 단계 | 시장 검토 | 학습 검토 | 전체 자동 | 신규 자동 |
|---|---:|---:|---:|---:|
| 6단계 기준선 | 992 | 826 | 4,191 | 0 |
| 추가상장 원문 18개 보완 | 987 | 821 | 4,196 | 5 |
| 배당 정정 본문 파싱 | 967 | 801 | 4,216 | 20 |
| 영문 병기 회사명 별칭 | 965 | 799 | 4,218 | 2 |

**배당 정정 본문.** `61474`·`71474` 정정 문서는 정정표가 최종 표와 같은 수량 라벨을 반복해 필드가 모호했다. 최종 문서이고 `정정항목, 정정전, 정정후` 표와 `주식배당결정` 제목이 각각 하나일 때만 제목 뒤를 본문으로 읽는다. 정정표의 정정 후 셀을 본문 대신 쓰지 않는다. 자회사 공시 검사는 본문을 자르기 전 전체 행에 적용한다. 엘오티베큠 `20161212000241`의 최종 본문은 발행주식 12,011,889주, 배당 590,407주, 주당 0.05주다. 배당 수량은 자기주식 203,734주를 제외한 값이고 파서는 발행주식총수를 바꾸지 않는다.

**회사명 별칭.** 공식 목록 issuer, 최종 본문 회사명, KRX 마스터의 같은 issuer·상장 구간을 확인한 유틸렉스(26305)와 서부티엔디(00673)의 이름만 `issuer_aliases.json`에 추가했다. 괄호 영문명을 일반 규칙으로 지우지 않는다. 유유제약 `20210316000101`의 기타주식 합계 1,294,945주는 두 우선주 시리즈 중 하나로 고르지 않는다.

**추가상장 원문.** `combined_bonus_listing_source_missing` 8사건에 이미 연결된 18개 accession만 KIND에서 수집했다(호출 54회, 모두 200, 요청 시작 간격 0.6초). 무상증자와 같은 날 상장한 CB 전환·유상증자 수량은 사유별로 따로 보존하고 무상 비율로 쓰지 않는다. 남은 3사건(`025620`, `033310`, `115180`)은 추가상장 합계가 KRX 증가와 같지만 원문 전후 총계가 맞지 않거나 없다. 합계만으로 순서를 추론하는 규칙은 추가하지 않았다.

**남긴 조사군.** `notice_parse_failed` 82건, `notice_security_unresolved` 80건, `reduction_notice_pair_missing` 115건(복수 공지 61·한쪽 없음 54, 복수 중 59건은 출자전환·제3자배정·CB 혼합), `official_terms_unmatched` 137건, `official_evidence_missing` 113건, `ex_price_reason_or_form_unsupported` 115건은 단일 사건으로 계산할 근거가 없어 검토로 유지했다. 건수는 후속 보완 전 기준이다.

**검증.** 신규 27건은 최종 원문 셀과 실제 KRX 전후 주식수·종가·기준가로 계수를 다시 계산해 대조했다. 최종 원장을 소켓 차단 상태에서 봉인하고 `read_resolution_snapshot(verify_archive=True)`로 다시 열어 상장 구간 3,563개, 학습 구간 3,219개, 신규 27건 계수, 학습 검토 CSV 799행 바이트 일치를 확인했다. 학습 검토 CSV SHA-256은 `8153cbd9718d6c48d803d482c5518a7f02011e0268d8881de1cec07e1f60964f`, 스냅샷 SHA-256은 `b52912fbe999e03420e756d7dc7fd06381156b2d97d0257e57d08df923a5e8b6`이다. ruff는 통과했고 pytest는 기존 활성 pack 해시 검사 1건을 빼고 모두 통과했다. 단계별 원장·명령·검산 결과와 조사 스크립트는 chart의 `workspace/pr-506-followup/`에 보존했고 저장소에는 커밋하지 않는다.

**알려진 한계.** 11307 무상증자와 주식배당의 가격 계수는 `1/(1+r)`이다. KRX 기준가가 자기주식을 제외한 희석 비율로 정해진 사건에서는 권리락일에 작은 가짜 수익률이 남을 수 있다(엘오티베큠 약 0.1%, 추정). 11308은 KRX 기준가÷직전 종가를 쓰므로 두 정책이 다르다. 이번 범위에서는 바꾸지 않았다.

## 감자(무상) 별도 허용 사유 추가

사용자 승인에 따라 `감자(무상)`을 동의어 치환 없이 별도 허용 사유로 추가했다. 제품 코드 변경은 `REDUCTION_REASONS`의 정확한 문자열 한 개이며, 기존 다섯 검사·허용 오차·최종 공시 확인·실패 처리는 변경하지 않았다. 아래 3단계의 네 사유 유지 기록과 5단계 결과는 추가 전 이력이고, 6단계는 위 후속 보완 전 결과다.

시장 검토 **1,474→992건**, 학습 검토 **1,301→826건**이다. 기존 PR 버전(`60d98e2`) 대비 자동 전환은111건(주식 단위 조정104건, 주식수 불변 재개7건), 학습 대기열 감소는105건이다. 후보·공지 CSV는 이전 PR 산출물과 바이트가 같으며, 판정 identity도 모두 같다. 기존 자동4,080행의 종류·계수·Review·사유·증거·실패명은 행 전체가 동일하다. 기존 PR과 비교해 판정이 바뀐 것은 앞서 집중 검토한111건뿐이다.

무상감자 표기의 기존 검토275건 중 나머지164건은 계속 검토다. 공지 쌍 누락, 실제 시가·거래량, 주식수, 다른 사유 충돌, 평가가격 검사를 완화하지 않았다. 사유 검사를 통과해 더 뒤의 검사에 도달하는 경우에는 `FailedCheck`가 구체적인 실패명으로 바뀔 수 있으며 판정·계수는 그대로다. 보관 원문의 정확한 문자열과 KRX 숫자로 판단하며, 주주별 균등 조건을 새로운 자유문구 파서로 검증하는 기능은 추가하지 않았다. 기존 조건으로 실패하는 차등감자 실례도 검토를 유지한다.

실제 보관70763+70793(`007720`,f=5),32004+32108(`136660`,f=4),액면감액(`027040`,f=1)을 fixture로 고정했다. 변경 전 양성3건이 사유 검사에서 실패했고 변경 후 통과한다. 유상·혼합·명시적 차등 사유, 공지 누락, KRX/공시 주식수, 평가가격, 호가 범위, 시가·거래량, 비최종·미파싱 공시 예외를 검사했다. 실제 차등감자`000040`에도 새 표기를 적용해 기존 `reduction_shares_mismatch`가 유지됨을 확인했다. 새 AddedShares 판정 조건은 추가하지 않았다.

## 측정 범위와 판정 보존

보관 원문과 동일 KRX 입력으로 시장 전체를 단계마다 재판정했다. 파이프라인 HTTP는 각 단계 0회다. `review_corporate_actions`는 request budget 0과 소켓 연결 차단을 함께 적용하며, 기존 자동 행의 Resolution·가격계수·거래량계수·Review와 전체 판정 identity 집합을 비교한다. 사유·증거 변경도 별도로 센다. 기준선의 가격 사건 후보는 4,807건이며 전체 판정 표에는 비가격 구조 사건 376건도 포함된다. 따라서 아래 Resolution 합계는 후보 자동+시장 검토보다 크다.

| 단계 | 후보 자동 | 시장 검토 | 학습 검토 | 기준선 대비 신규 자동 | 기존 자동 판정 변경 | HTTP |
|---|---:|---:|---:|---:|---:|---:|
| 기준선 | 3,333 | 1,474 | 1,301 | 0 | 0 | 0 |
| 1 실패 검사명 | 3,333 | 1,474 | 1,301 | 0 | 0 | 0 |
| 2 액면병합 | 3,566 | 1,241 | 1,069 | 233 | 0 | 0 |
| 3 감자 재개 | 3,601 | 1,206 | 1,034 | 268 | 0 | 0 |
| 4 증권 식별 | 3,629 | 1,178 | 1,006 | 296 | 0 | 0 |
| 5 레지스트리만 | 3,629 | 1,178 | 1,006 | 296 | 0 | 0 |
| 5 최종 기능 | 3,704 | 1,103 | 931 | 371 | 0 | 0 |
| 6 무상감자 표기 | 3,815 | 992 | 826 | 482 | 0 | 0 |

기존 자동의 사유·증거 변경도 모든 수용 단계에서 0건이다. 최종 봉인 검증에서 종목 상장 구간 집합을 기준선과 비교했고 전체 제외는 0건이다. 실패한 4단계 첫 시도는 기존 자동 bonus 42건을 검토로 바꿔 폐기했다. 같은 최종 문서의 보통주 확인과 완전 마스터에서 활성 우선주가 없다는 증거를 모두 요구하도록 고친 뒤 전체 재현을 다시 통과했다.

## 단계별 Resolution

| 단계 | unit_change | bonus | rights | reference_reset | tick_rounding | shares_only | segment_break | spac_premerger |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 기준선 | 335 | 746 | 644 | 474 | 410 | 644 | 1824 | 106 |
| 1 실패 검사명 | 335 | 746 | 644 | 474 | 410 | 644 | 1824 | 106 |
| 2 액면병합 | 568 | 746 | 644 | 474 | 410 | 644 | 1591 | 106 |
| 3 감자 재개 | 603 | 746 | 644 | 474 | 410 | 644 | 1556 | 106 |
| 4 증권 식별 | 611 | 755 | 655 | 474 | 410 | 644 | 1528 | 106 |
| 5 레지스트리만 | 611 | 755 | 655 | 474 | 410 | 644 | 1528 | 106 |
| 5 최종 기능 | 611 | 830 | 655 | 474 | 410 | 644 | 1453 | 106 |
| 6 무상감자 표기 | 715 | 830 | 655 | 481 | 410 | 644 | 1342 | 106 |

## 단계별 FailedCheck 상위 10개

실패 검사명은 가장 가까운 규칙에서 처음 실패한 검사다. 다른 사유의 문서도 함께 있으면 분포가 이동할 수 있으므로 한 서식의 영향은 accession과 증거 필드를 정확히 연결해 별도 계산한다. 기준선에는 열이 없어 1,474건 모두 빈 값이다.

### 1 실패 검사명

| FailedCheck | 시장 검토 |
|---|---:|
| `par_shares_exact` | 239 |
| `reduction_reason_conflict` | 216 |
| `notice_security_unresolved` | 153 |
| `official_terms_unmatched` | 132 |
| `reduction_notice_pair_missing` | 114 |
| `official_evidence_missing` | 113 |
| `unsupported_form:11308` | 99 |
| `notice_parse_failed` | 90 |
| `bonus_prior_shares_mismatch` | 56 |
| `unsupported_form:70768` | 42 |

### 2 액면병합

| FailedCheck | 시장 검토 |
|---|---:|
| `reduction_reason_conflict` | 216 |
| `notice_security_unresolved` | 153 |
| `official_terms_unmatched` | 132 |
| `reduction_notice_pair_missing` | 114 |
| `official_evidence_missing` | 113 |
| `unsupported_form:11308` | 99 |
| `notice_parse_failed` | 90 |
| `bonus_prior_shares_mismatch` | 56 |
| `unsupported_form:70768` | 42 |
| `reduction_dart_action_missing` | 35 |

### 3 감자 재개

| FailedCheck | 시장 검토 |
|---|---:|
| `reduction_reason_conflict` | 216 |
| `notice_security_unresolved` | 153 |
| `official_terms_unmatched` | 132 |
| `reduction_notice_pair_missing` | 114 |
| `official_evidence_missing` | 113 |
| `unsupported_form:11308` | 99 |
| `notice_parse_failed` | 90 |
| `bonus_prior_shares_mismatch` | 56 |
| `unsupported_form:70768` | 42 |
| `par_notice_price_mismatch` | 31 |

### 4 증권 식별

| FailedCheck | 시장 검토 |
|---|---:|
| `reduction_reason_conflict` | 218 |
| `official_terms_unmatched` | 137 |
| `reduction_notice_pair_missing` | 115 |
| `official_evidence_missing` | 113 |
| `notice_security_unresolved` | 110 |
| `unsupported_form:11308` | 99 |
| `notice_parse_failed` | 90 |
| `bonus_prior_shares_mismatch` | 58 |
| `unsupported_form:70768` | 42 |
| `par_notice_price_mismatch` | 31 |

### 5 레지스트리만

| FailedCheck | 시장 검토 |
|---|---:|
| `reduction_reason_conflict` | 218 |
| `official_terms_unmatched` | 137 |
| `reduction_notice_pair_missing` | 115 |
| `official_evidence_missing` | 113 |
| `notice_security_unresolved` | 110 |
| `unsupported_form:11308` | 99 |
| `notice_parse_failed` | 90 |
| `bonus_prior_shares_mismatch` | 58 |
| `unsupported_form:70768` | 42 |
| `par_notice_price_mismatch` | 31 |

### 5 최종 기능

| FailedCheck | 시장 검토 |
|---|---:|
| `reduction_reason_conflict` | 218 |
| `official_terms_unmatched` | 137 |
| `ex_price_reason_or_form_unsupported` | 115 |
| `reduction_notice_pair_missing` | 115 |
| `official_evidence_missing` | 113 |
| `notice_parse_failed` | 82 |
| `notice_security_unresolved` | 80 |
| `bonus_prior_shares_mismatch` | 57 |
| `par_notice_price_mismatch` | 31 |
| `par_listing_count` | 28 |

### 6 무상감자 표기

| FailedCheck | 시장 검토 |
|---|---:|
| `official_terms_unmatched` | 137 |
| `ex_price_reason_or_form_unsupported` | 115 |
| `reduction_notice_pair_missing` | 115 |
| `official_evidence_missing` | 113 |
| `notice_parse_failed` | 82 |
| `notice_security_unresolved` | 80 |
| `bonus_prior_shares_mismatch` | 57 |
| `reduction_opening_auction_mismatch` | 54 |
| `reduction_reason_conflict` | 45 |
| `par_notice_price_mismatch` | 31 |

## 11308의 기준선 실패 99건

정확한 증거 연결로 다시 찾은 99건 중 75건이 `bonus`로 전환됐다. 남은 검토는 아래와 같다.

| FailedCheck | 건수 |
|---|---:|
| `combined_bonus_listing_source_missing` | 8 |
| `notice_parse_failed` | 8 |
| `combined_bonus_reference_price_mismatch` | 3 |
| `notice_security_unresolved` | 3 |
| `combined_bonus_listing_session_unavailable` | 1 |
| `ex_price_reason_or_form_unsupported` | 1 |

원문 기반 예제 `126880` 2016-08-03은 가격 `59/76` (5,310/6,840), 거래량 `13/10`이며 `095610` 2016-04-14는 가격 `2/3`, 거래량 `3/2`다. 두 사례 모두 전체 봉인 결과를 `verify_archive=True`로 다시 읽어 확인했다. 실제 전체 coverage에서 테스의 원본4건이 최종20160428000303으로, 제이엔케이히터의 원본2건이 최종20160722000097로 연결된 N→Y 증거도 확인했다. 주식 단위 조정(`bonus`·`unit_change`)의 역수 검증에는 확인된 11308 무상 권리락 예외만 둔다. 일반 bonus와 unit_change의 역수 제약은 유지한다.

최종 기능의 첫 전수 시도도 수용하지 않았다. 70768 복합 사유의 substring 연결로 미보관 배정 공시51건이 새로 선택돼 검토39행이 incomplete로 빠졌고, 정정11307 대상 범위가 무관한 액면변경210120/2025-01-24까지 넓어져 기존 자동1행이 검토로 바뀌었다. 초기와 정정 대상에 같은 순수 BONUS/DIVIDEND 사유 집합을 적용해 연결 범위를 고친 뒤 다시 전체 재현했다. 폐기 결과는 `final-incomplete`에 보존했다.

## 결정과 인계서 대비 차이

| 항목 | 선택 | 근거·대안·검증 상태 |
|---|---|---|
| 규칙 A 단주 | 액면병합은 `floor(이전/f)`와 공시·KRX 이후 주식수 일치를 요구한다. 분할은 정확한 곱을 유지한다 | 신규 233건. 예상 196건의 감사에는 잘못 버림한 분할 5건이 있었고 이들은 검토 유지했다. 감사에서 유효한 병합 191건, 이름 변경 동시 2건, 다른 공시 조합 40건이 자동이 됐다. 기준가 교차 확인도 유지했다 |
| 규칙 B | 인계서의 네 단일 감자 사유와 다섯 검사를 모두 요구한다 | 신규 35건. 예상치 계산을 재현한 201건 중 실제 재개 시가·양수 거래량 미충족 54건, 허용 밖 `감자(무상)` 111건, 다른 미파싱 공시 1건을 제외했다. 초기 204건과 재현 201건의 차이 3건도 있어 예상치를 검증 사실로 쓰지 않는다. 감자와 무상감자는 동의어가 아니므로 허용 사유를 넓히지 않았다. 별도 검산에서 최종 감자(무상) 공지가 있는 stage3 기존 검토275건 중 허용 literal만 메모리에서 추가했을 때111건이 통과함을 재현했다 |
| 기존 재개 규칙 | 감자 전용 경로를 B로 통합하고 일반 장기 정지 후 재개 경로를 유지한다 | 일반 재개는 감자 외 사유에도 적용되며 삭제하면 기존 자동 판정을 바꾼다 |
| 증권 식별과 실패 범위 | 전체 발행사 마스터에서 종류·시리즈·적용일과 코드/ISIN을 교차 검증한다. 확정한 종류만 실패 영향을 받는다 | 종류를 확정하지 못하면 발행사 전체 검토를 유지한다. 비상장 포괄 우선주는 완전 마스터에서 기준일 및 상장 예정일의 활성 0건과 같은 최종 문서의 보통주 확인이 함께 있어야 범위 밖으로 본다. 부분 마스터와 상장일에만 활성인 미래 우선주도 범위 밖으로 생략하지 않는다. 명시 식별자가 있으면 정상 식별 경로를 따르고, 상충하는 식별자와 복수 후보의 모호성은 검토로 남긴다 |
| 70768 | 별도 표 모양으로 파싱한다 | 보관 42건은 무상+배당 또는 유상+배당의 복합 사유다. 70766과 같다고 가정하거나 단일 사건으로 자동화하지 않는다 |
| 정정 체인 | 조회 단계에서 최종 Y 하나를 검증하고 연결된 문서 가족 전체의 최종본 충돌을 막는다 | 문서 선택을 파싱 성공과 분리한다. 철회·취소, 없는/복수 최종본, 서로 다른 서식 간 같은 가족 충돌도 검토 유지한다 |
| 11308 | 유상·무상 절을 분리하고 최종 무상 비율·배정일·신주수·상장일과 KRX를 검증한다 | 순수 무상 권리락 공지의 기준가도 KRX와 일치해야 한다. 두 개의 독립 적격 결정이 있으면 하나를 임의 선택하지 않는다 |
| 추가상장 증거 | 실제 상장 증가가 무상 신주와 정확히 같고 다른 사건의 단서가 없으면 11308+KRX의 두 경로로 확인한다 | 제이엔케이히터의 20160822000294와 테스의 20160502000581 추가상장 본문은 기존 캐시에 없다. 해당 본문을 확인했다고 주장하지 않는다. 순수 무상 제목이면 선택 보조 자료의 누락만으로 기각하지 않는다. 유상/CB/불명/취소 표기, 상장일 중복 또는 수량 불일치가 있으면 보관 추가상장 본문과 합계를 반드시 확인하고 없으면 검토한다 |

직접 정한 수치와 기간은 아래처럼 제한했다.

- 분모 10과 이론 기준가의 2%는 인계서의 승인된 조건이다. 더 큰 분모나 허용 오차 확대로 예상 건수를 맞추는 대안은 채택하지 않았다. 원문 예제 및 경계 테스트와 전체 원장으로 검증했으며, 새로운 복합 사건이 확인되면 해당 근거와 함께 재검토한다.
- 추가상장 목록의 조회 범위는 상장일 기준 공시일 -7~+3일이다. 기존 공지 탐색 정책과 같은 짧은 범위에서 보관 목록만 확인하려는 선택이며, 더 긴 범위는 무관한 사건을 묶을 수 있다. 보관 예제와 합성 중복 상장·철회·미상 본문 사례를 검증했다. 이 범위 밖 실제 추가상장이 확인되면 기간을 넓히기 전에 사건 연결 규칙을 재검토한다. 이 범위의 모든 보조 본문 조회는 `cache_only=True`다.

예상 시장 검토 700~850건에 맞추기 위해 조건을 느슨하게 하지 않았다. 실제 남은 분포와 11308 잔여 검사명을 위에 보고했다. 공시 자체가 없거나 복합 감자의 단위 비율이 유일하지 않은 사건은 계속 검토한다.

## 실행과 근거

chart 디렉터리에서 실행했다. 가상환경 실행 파일은 `/private/tmp/chart-audit-venv/bin/` 아래다.

```sh
ruff check .
pytest -q
python -m experiments.dataset.review_corporate_actions \
  --replay-args "$SOURCE/replay-args.json" \
  --kind-root workspace/corporate-action-review/cache \
  --output workspace/corporate-action-review/final \
  --baseline workspace/corporate-action-review/baseline
```

위 코드는 실제 실행한 명령이다. 다시 재현할 때는 `--output workspace/corporate-action-review/replay-새이름`처럼 아직 발행하지 않은 디렉터리를 지정한다. census는 이미 발행한 출력 경로의 덮어쓰기를 거부한다.

`SOURCE`는 기존 #478의 `workspace/training-krx-validation/market-resolutions/operator-validation/cache-only-tree-7f9518a` 보관 디렉터리다. replay 입력의 절대 경로를 재사용하고 KIND cache는 독립 복제했다. 저장된 `final/replay-input.json`에 실제 argv와 입력 해시가 있다. 감자 사유 가정 비교와 분할 버림 반례는 같은 workspace의 `reduction-reason-counterfactual.py/.log`, `split-floor-counterfactual.py/.log`, 초기 B 분해는 `rule-b-original-audit/`에 보존했다. 단계별 `manifest.json`, `review-summary.json`, 원장 CSV와 테스트 로그는 이 worktree의 `workspace/corporate-action-review/`에 보존했다. 전체 봉인 검증은 보존한 `python workspace/corporate-action-review/final-freeze.py final`로 실행했다. 이 스크립트는 원래 replay 입력의 KRX·마스터·행동 스냅샷·아카이브 경로를 읽어 `freeze_resolution_snapshot`을 호출하고, 소켓을 차단한 상태에서 봉인 재열기와 학습 검토 CSV 및 예제 계수를 assert한다. 크기가 큰 원문·원장은 커밋하지 않았다. 전체 분포와 표 해시는 [기계 판독 결과](corporate-action-review-results.json), 결정 이력은 [정본 로그](corporate-action-review-decisions.tsv)를 본다.

5단계 ruff는 통과했다. 전체 pytest 결과는 `1 failed, 643 passed, 3 skipped, 879 warnings in 192.72s (0:03:12)`다. 실패는 기준선에서도 재현된 `serving/tests/test_regular_session_close.py::test_shared_builder_still_matches_the_active_pack` 한 건으로 활성 pack 해시 불일치다. pack을 바꾸지 않았다.

5단계 시장 산출물을 `freeze_resolution_snapshot`으로 봉인한 뒤 `read_resolution_snapshot(verify_archive=True)`로 읽었다. 3,563개 상장 구간, 학습 3,219개 구간을 보존했고, 봉인 결과의 학습 검토 CSV 931행은 진단 재현 CSV와 바이트 단위로 일치했다. 봉인 중 소켓 연결을 차단했으며 HTTP는 0회였다.

- snapshot SHA-256 `ab3796817140a0b88f019e709f7f27c8b018cfd03731b7978d0a971e2356bac8`
- evidence SHA-256 `70f5ac151376eaba47c4c45ccd2e961bb40ade675f42ce5c3dfbf7e4c6ed7ec9`
- segmentation SHA-256 `3b46a39609c3b07dfe674af7f33b6506e16cfca096a0567ebe11898017924411`

## 검토와 적용 원칙

독립 `gpt-6.2-sol` 검토에서 추가상장 수량의 불연속 조합, 정정 대상의 실패 범위, 미인식 증권 행, 다른 서식과 연결된 최종본 충돌, 표시 제목에만 있는 취소, 미래 상장 우선주, 보조 자료 조회 전 부적격 날짜 검사를 지적했고 모두 회귀 테스트와 원문 재검증으로 닫았다. 최종 후보4807건과 상장 구간3563개, 기존 자동의 모든 종류·계수·Review·사유·증거, 실제 N→Y6건을 보관 receipt·routing·본문까지 독립 검증했다. 같은 제공자의 독립 검토이며 교차 모델 검토로 부르지 않는다. 독립 검토에는 전체 원시 대화 기록이 제공되지 않아 코드·원장·실행 로그를 근거로 삼았다.

**Build the Lever**를 적용해 캐시 전수 재현과 기준선 비교를 다시 실행할 수 있는 CLI로 남겼다. **Explain the Number**를 적용해 예상196/204건과 실제233/35건의 차이를 원장·원문·가정 비교로 분해했다. **Sequence Work into Verifiable Units**를 적용해 단계별 커밋과 전수 재현을 분리했다. **Model the Domain**을 적용해 실패 진단·영향 범위·서식 정보를 타입과 레지스트리로 표현했다. **Attack the Premise**를 적용해 보조 공시를 찾기 전에 같은 순수 검사로 후보의 적격성을 확인하고, 초기와 정정 대상의 배정 공시 연결도 실제 순수 권리락 사유로 통일했다. **Prove It Works**를 적용해 전체 원장 비교와 원문 아카이브 봉인·재열기를 완료했다.

운영 DB·서빙·활성 pack·재학습·정기 실행 설정은 변경하지 않았다. 이 결과는 현재 보관 원문과 KRX 범위에 대한 검증이며 이후 새 서식과 복합 사건을 자동 승인하는 보증은 아니다.

## 6단계 실행과 봉인 검증

chart에서 원래 replay 입력과 독립 cache를 재사용했다. 제품 소스를 고정한 뒤 전체 시장 재현은 한 번 실행했다.

```sh
python -m experiments.dataset.review_corporate_actions \
  --replay-args "$SOURCE/replay-args.json" \
  --kind-root workspace/corporate-action-review/cache \
  --output workspace/corporate-action-review/unpaid-reduction \
  --baseline workspace/corporate-action-review/baseline
python /private/tmp/chart-review-compare-unpaid.py
python workspace/corporate-action-review/unpaid-reduction-review/freeze.py unpaid-reduction
ruff check .
pytest -q
```

위는 실제 실행한 명령이다. 다시 실행할 때는 미발행 출력 경로를 사용한다. `SOURCE`는 앞 절과 같은 원본 보관 경로다. 원장 비교 스크립트는 `unpaid-reduction-review/compare-previous-pr.py`로도 보존했다. 실행 코드·전수/테스트 로그와 원장 비교 JSON은 `workspace/corporate-action-review/unpaid-reduction-review/`에 보존했다. 전체 원장과 봉인은 각각 `unpaid-reduction/`, `unpaid-reduction-official-actions/`에 있다. 원래 baseline과 이전 PR의 `final/`은 그대로 보존했다.

현재 ruff는 통과했다. 전체 pytest는 `1 failed, 686 passed, 3 skipped, 879 warnings in 151.40s (0:02:31)`이며 실패는 앞 절과 동일한 기존 활성 pack 해시 검사1건이다. 봉인 결과를 `read_resolution_snapshot(verify_archive=True)`로 다시 읽고, 상장구간3,563개 보존·학습검토826행 CSV 바이트 일치·새111건의 계수 및 기존11308예제2건을 모두 확인했다. 새 HTTP 호출은0회다.

- snapshot SHA-256 `10632fce8a293412bade6ec40b81054db1aef9221cec3a879940544485d26cd6`
- evidence SHA-256 `70f5ac151376eaba47c4c45ccd2e961bb40ade675f42ce5c3dfbf7e4c6ed7ec9`
- segmentation SHA-256 `cb7175a7d76a0f86d8c33d07e42e61acfc54ecf15f425a13af657b49240b2af2`
