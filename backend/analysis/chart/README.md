# Chart

수정가격·시장 심리 피처를 근거로 H5/H20 상대 스코어와 과거 유사 사례를 제공한다. 자동 매매는 하지 않는다.

- `shared/`: 공급자 호출, 원본 OHLC 보정, 실제 VWAP, 거래일 검증, 정규화, Alpha158, Sigma, 수급 피처, 해시·원자적 저장.
- `experiments/`: 장기 구축·재개, 미래 정보가 필요한 라벨·표본 선택, 학습·평가·백테스트, 검증된 결과의 pack 내보내기.
- `serving/`: 운영 입력 갱신·재실행, pack 검사, 추론·Supabase 저장·발행. 연구 코드와 연구 저장 경로를 참조하지 않는다.
- `workspace/experiments/`, `workspace/serving/`, `workspace/archive/`: 데이터·캐시·산출물. 전체 Git 제외.

재현성: 실험은 시드를 고정하고 공용 평가함수(`experiments/evaluation/`)로만 평가한다. 모델별로 평가 코드를 따로 만들지 않는다.

모든 명령은 `backend/analysis/chart`에서 `python -m experiments...`, `python -m serving...`로 실행한다.

`shared/settings.py`는 실험과 서빙이 함께 쓰는 피처 계산 기본값, 저장 경로, 코드와 설정의 호환성 해시를 정의한다. 같은 가격이 학습과 운영에서 다르게 계산되는 것을 막기 위한 공통 코드다. 입력 열 `Barrier_Up`, `Barrier_Down`의 배수 1.5/1.2는 미래 정답을 정하는 H5/H20 라벨 배수와 별개다. 학습 라벨은 실험 설정의 `labels`, 내보낸 운영 모델에서는 pack manifest의 `horizons.h5/h20.label_barriers`가 정본이다.

`settings.py`는 원문 해시까지 pack 계약에 포함된다. 설명을 추가하는 변경도 기존 pack과의 호환성을 확인해야 하므로, 채점 오류를 고치려고 공통 피처 설정을 바꾸지 않는다.

실험은 `experiments.dataset.collect`로 KRX 원주가, 상장 이력, KIND 공시를 수집하고 검증된 장부를 데이터셋에 고정한다. 여러 데이터셋은 원천 캐시를 공유한다. 전처리는 데이터셋에 고정된 입력을 읽는다. 학습 자료를 열 때는 파일 해시로 내용의 무결성을 확인하고, 처리 엔진과 가격 정책, 피처 순서로 호환성을 확인한다. [실험 수집과 재개](experiments/README.md#환경과-명령)

[서빙 운영](serving/OPERATIONS.md)과 [품질 제한](docs/RESULTS.md#품질-제한)을 확인한다.

공식 Qlib Alpha158로 재학습할 때는 [원본 적용과 모델 호환성](docs/ALPHA158_COMPATIBILITY.md)을 따른다. `preprocessing: qlib_alpha158`는 원본 패키지를 직접 사용한다. 기존 운영 모델은 기존 `shared_v3` 계산을 유지하며, 이 경로는 재학습 전환 때 삭제할 임시 경로다([#464](https://github.com/2026Graduation-Work/take_a_look/issues/464)).

대표 결과와 품질 제한은 [RESULTS.md](docs/RESULTS.md)에 있다. 이전 코드·문서 원문(`archive/`)은 태그 [`v1.1.0`](https://github.com/2026Graduation-Work/take_a_look/tree/v1.1.0/backend/analysis/chart/archive)에 남아 있다.
