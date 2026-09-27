# 차트 분석 블록

기술적 피처와 3분류 LightGBM으로 profile별 상대 스코어를 생성하고 공용 평가·백테스트를
수행한다.

과거 실험 universe는 `data/universe/security_master.parquet`의 상장 구간을 기준으로
`ListingDate <= Date < DelistingDate` 규칙을 적용한다. 상폐 종목을 제외하거나 현재
상장 목록으로 과거 universe를 대신하지 않는다.

설치, 데이터, 모델, config, 학습, 평가, 추론, 추가 피처, 파일 구조는
[`ONBOARDING.md`](ONBOARDING.md) 하나를 기준으로 한다.

종목 상세 H5/H20 serving의 구현·공개 계약·검증 상태는
[`serving/README.md`](serving/README.md), 실행 절차는
[`serving/OPERATIONS.md`](serving/OPERATIONS.md)를 참고한다.

후속 연구 과제: 과거 KRX 휴장일 표시의 전수 감사와 실제 VWAP 피처의 학습 입력 동등성 검증.
두 항목은 현재 pack의 결과 해석 제한으로 남아 있다.

빠른 검증:

```bash
pip install -r requirements.txt
ruff check .
pytest
```
