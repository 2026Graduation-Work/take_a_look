# Daily serving 일괄 수집 및 무한대 피처 복구

## 운영 실패

- 36945555766 (main): 942종목 수집 완료 후 Infinite feature input으로 실패. 전체 약 80분.
- 원시 시세 조회 3016.9초 / 피처 개별 업로드 1008.2초 / 가격 저장 261.0초 / 가격 조회 227.0초 / 수정주가 조회 156.7초 / 피처 계산 60.3초.
- archived replay 진단 36954429927: `014160 / corr_10`으로 특정. 전체 약 4분16초; DB 가격 패널 83.7초 / 피처 묶음 업로드 3.6초.
- 실제 014160 데이터에서 이전 corr_10=inf, 수정 후 NaN, H5/H20 추론 정상 확인.

## 변경

- raw OHLCV/거래대금은 날짜별 KOSPI 전체 조회. 부족한 시장 날짜는 일괄 backfill.
- 가격은 DB 이력을 재사용. 수정주가 조회는 유지해 과거 수정계수 및 VWAP 보정 반영.
- 새 날짜와 변경된 가격만 market batch upsert.
- 현재 모델 입력 942개를 한 parquet로 보관하고 종목별 metadata는 동일 파일의 stock_code로 연결. 과거 raw 가격은 chart_prices에 계속 누적.
- zero-variance 구간의 무한대 상관계수는 정의 불가능한 값이므로 NaN 유지. 임의 0 대입/모델 재학습 없음.
- 오류 로그에 입력 종목/피처명 포함. 요청 timeout/retry 유지.
- UI/SQL/frozen schema/model artifacts 변경 없음.

## 검증

- chart pytest 196개, ruff 통과. PR #185 CI/CodeQL/Vercel 통과 (source head 98c14e5).
- 실제 삼성전자/셀트리온/거래정지 000040: 기존 종목별 수집과 incremental 수집의 가격/VWAP 일치.
- 회귀 테스트: 신규/수정 가격, missing archive backfill, batch upload, 가격 pagination, 상수 구간 상관계수.
- 수정된 normal daily dry-run **36954970350**, job **110675819501**, as_of 2026-10-01 진행 중.

## 다음 확인

위 normal dry-run 결과부터 확인. 성공한 경우 PR #185 최신 CI 완료 후 merge, main --as-of 2026-10-01 --publish 실행 후 latest view 1884개/날짜 및 4종목 production UI 확인.
Copilot 및 유료 기능 제외. 원본 dirty checkout은 보존하고 /tmp/take-a-look-chart-fix worktree만 사용.
