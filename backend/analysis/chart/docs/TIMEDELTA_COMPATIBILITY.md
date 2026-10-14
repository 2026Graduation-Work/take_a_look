# NumPy 날짜 단위 호환 검증 (2026-10-14)

#107의 generic timedelta 경고는 pandas 2.3.3과 NumPy 2.5.3에서 `pd.Timedelta(days=...)`가 단위 없는 중간 값을 만들며 발생했다. 공용 가격·달력·공급자와 연구의 분할·학습·백테스트에서 일 단위를 `unit="D"`로 명시했다.

공용 소스 파일의 해시가 운영 pack 계약에 포함되므로 소스만 바꾸지 않았다. 보존된 기존 연구 자료를 검증해 새 pack `kospi_shared_v3_flow_train2023_2025_20261014`를 만들고 config를 함께 전환한다. 기존 pack은 보존한다.

- 1,019종목·2,368,027행의 원본·가공·학습 입력 해시, 가격·기본·수급 피처를 기존 v3 결과와 비교했다. rtol=1e-8, atol=1e-10으로 모두 일치했다.
- H5/H20 모델 파일·과거 사례 parquet의 SHA-256과 피처 순서는 이전 10/11 pack과 완전히 같다. 재학습이나 새 성능 주장은 없다.
- source 계약 SHA-256: `ac4d23b4a17d9427efffb079c9a9e0d8f543ae8d6b1620b1f867700cf2faeb88`.
- 새 압축 파일 SHA-256: `20da6a515edc32f5e906116f748484bac0fd224220ad4d9b9c0e1561f9b88086`.
- 상세 근거: `local-pack-validation.json`. 독립 원문과 전체 데이터 비교를 유지했다.
- serving 설치의 CI는 프로젝트 코드의 generic timedelta DeprecationWarning을 오류로 승격한다. 고정한 exchange_calendars 4.13.2 내부의 `pd.Timedelta("1h")` 등에서 같은 외부 경고가 남아 해당 패키지에서 발생하는 경고만 예외로 둔다. 라이브러리 파일은 수정하지 않았다.

변경 전 source와 pack을 각각 섞어 쓰면 계약 검사가 실패한다. 되돌릴 때는 10/11 pack config와 그 builder source가 있는 PR #313 머지 상태를 함께 복원한다. 이번 검증은 날짜 연산·입력·추론 동등성 검사이며 KRX 공급자 접속 성공이나 실제 참가자 평가를 대신하지 않는다.
