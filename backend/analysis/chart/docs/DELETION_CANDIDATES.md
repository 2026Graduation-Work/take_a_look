# 삭제 후보, 이번 작업에서 삭제하지 않음

검사는 chart의 활성 `shared/`, `experiments/`, `serving/` Python 코드와 `.github/` 실행 경로를 기준으로 했다. archive 원문이나 외부 개인 명령까지 사용 여부가 확인된 것은 아니다. 삭제는 별도 검토 대상이다.

## 동일 검사 스크립트

`archive/legacy/check_data_integrity.py`와 `archive/legacy/scratch/check_data_integrity.py`는 전체 SHA-256과 크기가 동일하다. 활성 코드·CI에서 참조하지 않는다. 고정 날짜와 삼성전자 거래일을 사용하므로 현재의 공통 거래일 검증 대신 실행하면 안 된다. 파일별 해시·크기는 [deletion-candidate-evidence.json](deletion-candidate-evidence.json)에 있다.

## 과거 실행 코드와 문서

`archive/legacy/core/`, `scripts/analysis/`, `scripts/batch/`, `result_dashboard/`는 이전 실행 경로다. 원문을 보존했고 활성 진입점은 `python -m experiments...`, `python -m serving...`다. `archive/legacy/price_collector.py`는 공통 추출 전 공급자 원본이며 실행용이 아니다.

`shared/data/providers.py`의 과거 전체 다운로드 CLI 보조 함수는 호환성 검토 후 축소 후보다. 현재 데이터 구축은 `experiments.dataset.collect`, 수집은 `shared.data.prices`를 사용한다. 공통 공급자·수급 함수는 계속 사용하므로 파일 전체를 삭제하는 후보가 아니다.

빈 확장용 모듈은 확인되지 않았다. `__init__.py`와 `train_src/base_model.py`의 추상 메서드는 패키지·학습 인터페이스에 쓰이므로 단순히 비었다는 이유로 삭제하지 않는다.

## 테스트 캐시와 smoke 산출물

`workspace/archive/`의 기존 `.pytest_cache`, `.ruff_cache`, `__pycache__` 보관분과 `workspace/experiments/runs/synthetic_contract_smoke_*`는 검토 후보다. smoke 명칭은 테스트에서 쓰지만 기존 산출물을 읽어 재사용하지 않는다. 보존된 기존 캐시는 경로·코드 변경 후 자동 재연결하지 않았다. 새 코드의 검증 캐시는 별도로 생성한다.

## 데이터 중복 판정 보류

데이터·모델·예측의 전체 해시는 이동 기록에 있다. 연구 데이터, 원본 보관분, 운영 입력, 이전 pack은 같은 내용이어도 재현·출처·롤백 용도가 다르다. 모든 사용처가 확인되지 않은 데이터는 중복 삭제 후보로 지정하지 않았다. 실험→운영으로 명시적으로 복사한 삼성전자 입력도 운영 재실행용이므로 유지한다.

Git의 삭제 표시는 workspace로 이동한 기존 추적 파일의 추적 해제다. 로컬 원본은 보존했다. 전체 이전/이후 경로는 [migration.json](migration.json)과 그 안의 전체 기록 경로에서 확인한다.
