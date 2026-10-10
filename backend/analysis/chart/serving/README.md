# Serving

일일 운영 입력으로 H5/H20 스코어·근거·과거 유사 사례를 계산하고 기존 Supabase 계약으로 발행한다. 연구 실행과 저장 경로는 사용하지 않는다.

처리는 `shared`의 v3 구현이다. KRX 원본 OHLC에 동일 수정계수를 적용하고 `Amount / RawVolume × AdjustmentFactor`로 실제 수정 VWAP을 계산한다. 수급 결측은 null로 유지하며 기본 H5/H20 모델은 수급 피처를 사용하지 않는다.

pack은 모델·피처 순서·클래스·과거 사례·달력·공통 처리 설정·구현 해시·동봉된 builder 원본을 검사한다. 불일치하면 수집·추론·발행 전에 중단한다. 공개 JSON과 Supabase 테이블·view·RPC 계약은 변경하지 않았다.

실행과 되돌리기는 [OPERATIONS.md](OPERATIONS.md), 해석 제한은 [품질 문서](../docs/DATA_QUALITY.md), 로컬 전환 근거는 [검증 기록](../docs/VALIDATION.md)에 있다.
